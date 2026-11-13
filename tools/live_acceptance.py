"""Post-deployment readback, per-task asset pin, isolation and exact-owner checks."""
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from task_board import lifecycle
from task_board.projects import ProjectHub
from task_board_client import Client,ClientError
from owned_process import run
ROOT=Path(__file__).resolve().parents[1];STATE=ROOT/'state'

def main():
    E=ROOT/'evidence/live'/time.strftime('%Y%m%d-%H%M%S');E.mkdir(parents=True)
    p={**lifecycle.read(STATE/'_private/admin.json'),'url':'http://127.0.0.1:24710'};admin=Client(p['url'],p)
    candidates=[(f,lifecycle.read(f)) for f in (ROOT/'evidence/drill').glob('*/RESULT.json')]
    f,demo=max((f,d) for f,d in candidates if d['complete']);project=demo['project_id'];stamp=project[len('onboarding-'):]
    profile={**lifecycle.read(STATE/'_private/roles'/('demo-owner-'+stamp+'.json')),'url':p['url']};owner=Client(p['url'],profile)
    prefix='/api/projects/task-board';report={'checks':[],'project_id':project,'evidence':str(E)}
    def check(ok,label):
        if not ok:raise AssertionError(label)
        report['checks'].append(label)
    def pg(action,payload):return admin.call(prefix+'/governance',{'request_id':str(uuid.uuid4()),'expected_revision':admin.call(prefix+'/governance')['revision'],'action':action,'payload':payload})
    def shared(c,action,payload,path='/api/shared'):return c.call(path,{'request_id':str(uuid.uuid4()),'action':action,'payload':payload})
    def event(c,action,payload):
        t=c.task(tid) if action!='create' else None
        return c.call('/api/events',{'request_id':str(uuid.uuid4()),'task_id':tid,'action':action,'expected_revision':t['revision'] if t else 0,'scope_version':t['scope_version'] if t else 1,'payload':payload})
    hub=ProjectHub(STATE)
    try:board=lifecycle.read(STATE/'_private/roles/board-se.json')
    except FileNotFoundError:
        board=hub.invite('task-board','board-se');lifecycle.write(STATE/'_private/roles/board-se.json',{**board,'url':lifecycle.read(STATE/'_private/server.json')['public_url']})
        pg('member',{'actor':'board-se','role':'owner','scope':'独立公告板总负责人/SE；项目知识、任务、接口、资产、验收与继承。仅本项目管理权限。'})
    check([x['id'] for x in Client(p['url'],{**board,'url':p['url']}).call('/api/projects')['projects']]==['task-board'],'board owner is project scoped, not global administrator')
    tid='test/task-asset-lock';alias='brief-method';current=owner.call('/api/shared')['consumption'][alias];ref=current['id'];sha=current['sha256']
    evidence=E/'runtime-pins.json';base='0'*40
    code,out,err=run(['git','rev-parse','HEAD'],evidence=E,purpose='freeze deployed independent source anchor',cwd=ROOT,timeout=10);assert code==0;base=out.decode().strip()
    spec={'id':tid,'title':'验证每任务资产锁与显式范围升级','kind':'atomic','description':'项目alias升级不改变既有任务输入；撤回旧锁必须拒绝领取，SE显式scope选择新锁后才继续。','deliverables':[{'id':'D1','label':'真实生产API反例与显式scope迁移回执'}],'registered':True,'claimable':True,'allowed_paths':['evidence/live/'],'depends_on':['test/label'],'source':{'drill_followup':True},'work':{'category':'test','role':'tester','inputs_known':True,'inputs':['runtime API at source '+base],'outputs':['runtime-pins.json'],'contracts':['label-api@2'],'assets':[alias],'resources':[],'couplings':[],'baseline':base,'acceptance':'锁版本不漂移；撤回拒绝；显式scope升级后可执行'}}
    event(owner,'create',{'spec':spec,'reason':'发现并修复每任务资产锁缺口后的运行验收'})
    before=owner.task(tid)['spec']['work']['asset_locks'][alias];check(before['release']==current['release'],'new task freezes the exact consumed release and SHA')
    ev=[{'path':str(ROOT/'templates/agent-brief.md'),'sha256':hashlib.sha256((ROOT/'templates/agent-brief.md').read_bytes()).hexdigest()}]
    pg('asset',{'id':ref,'version':'3','kind':'methodology','source':'Independent generic delegation method, explicit v3','license':current['license'],'sensitivity':'public','sha256':sha,'location':'templates/agent-brief.md','owner':'board-se','shareable':True,'evidence':ev})
    shared(admin,'publish',{'asset':ref+'@3','audience':[project],'shared_location':'repo:project-board/templates/agent-brief.md@sha256:'+sha,'review':'SE explicit v3 review; retain older immutable releases','evidence':ev},prefix+'/shared')
    newref='task-board/'+ref+'@3';shared(owner,'upgrade',{'ref':newref,'alias':alias,'reason':'Consumer owner explicitly approves v3','tests':'Per-task drift counterexample plus content SHA verification'})
    brief=owner.call('/api/brief?task='+tid);check(brief['asset_locks'][alias]==before and brief['assets'][alias]['ref']==before['release'],'project alias upgrade leaves dispatched task and brief on its original bytes')
    shared(admin,'withdraw',{'ref':before['release'],'reason':'Bounded runtime withdrawal rehearsal of demo-only asset','migration':'Only demo project is authorized. Existing task must explicitly scope to approved v3.','evidence':ev},prefix+'/shared')
    try:event(owner,'claim',{'summary':'must refuse withdrawn task input'});raise AssertionError('withdrawn lock silently floated')
    except ClientError as error:check(error.status==409,'withdrawn old task lock is refused although project alias is already v3')
    task=owner.task(tid);spec=task['spec'];spec['work']['asset_locks'][alias]={'release':newref,'sha256':sha,'shared':True}
    event(owner,'scope',{'spec':spec,'reason':'Owner explicitly approves this task input migration to v3; revalidate runtime counterexample'})
    event(owner,'claim',{'summary':'Explicitly scoped v3 and verified own paths/inputs'})
    check(owner.task(tid)['spec']['work']['asset_locks'][alias]['release']==newref,'task input changes only through explicit new scope')
    lifecycle.write(evidence,{'checks':report['checks'],'previous_lock':before,'current_lock':spec['work']['asset_locks'][alias],'source_commit':base})
    ev=[{'path':str(evidence),'sha256':hashlib.sha256(evidence.read_bytes()).hexdigest()}]
    submit=event(owner,'submit',{'summary':'Actual deployed asset-lock counterexamples passed','completeness':'full','deliverable_ids':['D1'],'implementation_commit':base,'evidence':ev,'tests':'Per-task pin, project alias upgrade, withdrawn old pin refusal and explicit scope upgrade passed','remaining':'none','addresses':[]})
    review=Client(p['url'],{**p,'project_id':project})
    event(review,'accept',{'submission':submit['event_id'],'summary':'SE inspected runtime counterexample report and exact source','deliverable_ids':['D1'],'evidence':ev})
    event(review,'merge',{'submission':submit['event_id'],'summary':'Independent source deployed at this Git anchor','commit':base,'evidence':ev})
    event(review,'native',{'submission':submit['event_id'],'summary':'Actual deployed API exercised; readback verified','commit':base,'evidence':ev})
    sampleapp=admin.call('/api/projects/sampleapp/verify');check(sampleapp['tasks']==330 and sampleapp['events']==335 and sampleapp['head_hash']=='df30c6125fae27a53bb9ba721c20922b00caa8c83ea4b16ac5e339506e4a19e6','original sampleapp task/event/hash chain remains unchanged')
    record=lifecycle.read(STATE/'service.json');check(bool(lifecycle.exact_owner(record)) and str(ROOT/'tools/task_board.py') in record['command'],'persistent process exact identity points to independent source')
    for project_id in ('sampleapp','task-board',project):
        check(admin.call('/api/projects/'+project_id+'/verify')['passed'],'task chain verified: '+project_id)
        check(admin.call('/api/projects/'+project_id+'/governance/verify')['passed'],'governance chain verified: '+project_id)
    report.update(passed=True,source_commit=base,sampleapp=sampleapp,owner={'pid':record['pid'],'created':record['created'],'command':record['command']},task_receipt=submit)
    lifecycle.write(E/'RESULT.json',report);print(json.dumps({'passed':True,'checks':len(report['checks']),'evidence':str(E)},ensure_ascii=False))
if __name__=='__main__':main()
