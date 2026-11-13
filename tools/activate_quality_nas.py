"""Activate the real board project's bounded runner and verification task.

This does not create rehearsal projects. Only the board's own task, cases and
project-scoped runner are written; service/identity locations stay private.
"""
import hashlib,json,shlex,subprocess,sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from task_board import lifecycle
from tools.task_board_client import Client
from tools.quality_runner import post
from tools.owned_process import run
ROOT=Path(__file__).resolve().parents[1];E=ROOT/'evidence/evolution-20261114'
NAS='/srv/project-board';SMB=Path('//example-owner/Project Workspace/project-board');URL='http://example-server.example-tailnet.ts.net:18785';TID='upgrade/OPERATIONS-20261114'

def main():
    source=lifecycle.read(SMB/'state/connection.json')['code_root'];commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    assert lifecycle.read(SMB/'state/connection.json')['code_commit']==commit,'Deploy the exact source first'
    owner=Client(URL,lifecycle.read(SMB/'state/_private/roles/board-se.json'),'100.64.0.10')
    def gov(action,p):
        g=owner.call('/api/governance');return owner.call('/api/governance',{'request_id':uuid.uuid4().hex,'expected_revision':g['revision'],'action':action,'payload':p})
    def event(action,p):
        t=owner.call('/api/task?id='+TID);return owner.call('/api/events',{'request_id':uuid.uuid4().hex,'task_id':TID,'action':action,'expected_revision':t['revision'],'scope_version':t['scope_version'],'payload':p})
    ev=[{'path':'repo:docs/DELIVERY-20261114.md@'+commit,'sha256':hashlib.sha256((ROOT/'docs/DELIVERY-20261114.md').read_bytes()).hexdigest()}]
    g=owner.call('/api/governance');member=g['members']['board-se'];gov('member',{'actor':'board-se','role':'owner','scope':member['scope'],'actor_kind':'agent'})
    g=owner.call('/api/governance');knowledge=g['knowledge']
    for material in knowledge.get('materials',[]):
        for filename,route in [('OWNER-GUIDE.md','/help/owner'),('AGENT-QUICKSTART.md','/help/agent')]:
            if route in material['location']:material.update(version=commit,sha256=hashlib.sha256((ROOT/'docs'/filename).read_bytes()).hexdigest())
    for title,path,route in [('时间治理与质量操作','API-OPERATIONS.md','/help/operations'),('项目测试执行器','RUNNER-GUIDE.md','/help/runner')]:
        row={'title':title,'location':URL+route,'version':commit,'sha256':hashlib.sha256((ROOT/'docs'/path).read_bytes()).hexdigest()}
        knowledge['materials']=[m for m in knowledge['materials'] if m['location']!=row['location']]+[row]
    gov('knowledge',knowledge)
    g=owner.call('/api/governance')
    if 'operations@1' not in g['modules']:
        gov('module_plan',{'id':'operations','version':'1','title':'分级治理、时间、质量与资产执行框架','parent':'','goal':'完整交付用户2026-11-14确认的五项能力及NAS运行验收','scope':'本独立产品、项目内操作API、执行器、Web、手册与自动验证','non_goals':'不执行其他消费项目的业务/设备流程','owner':'board-se','path':'隔离实现与反例验证，四种界面渲染，NAS备份回滚重启，受限执行器实跑与回传','inputs':['user-request:20261114','operations-api@1'],'outputs':['operations-schema@1','project-runner-kit@1'],'interfaces':['operations-api@1'],'no_interface_reason':'','risks':'规则误放行、过期证据与进程泄漏；使用范围版本、租约、真实退出结果和清理反例验证','unknowns':[],'planning_tasks':[],'decisions':[],'depends_on':[],'acceptance':'五项能力实际可操作；测试正反例、真实执行、原权限/链与NAS回滚重启通过','stage':'design','evidence':ev})
    g=owner.call('/api/governance');check=g['module_readiness']['operations@1']
    if not check['ready']:gov('module_review',{'ref':'operations@1','scope':check['scope'],'result':'approve','summary':'已按用户确认边界完成实现与隔离验证；以本轮报告和NAS验证为阶段交付依据','evidence':ev})
    task=owner.call('/api/task?id='+TID)
    if task['spec']['work'].get('planning',{}).get('module')!='operations@1':
        spec=task['spec'];spec['work']['planning']={'module':'operations@1','purpose':'execution','question':'','no_interface_reason':''};event('scope',{'spec':spec,'reason':'将真实升级接入已实现的风险、模块和测试门禁；不回填过去工时'})
    if not owner.call('/api/operations')['policy']['enabled']:post(owner,'policy',{'profile':'standard','reason':'公告板自身采用新治理，历史任务保留；当前真实升级按严格风险验收'})
    task=owner.call('/api/task?id='+TID);post(owner,'assess',{'task':TID,'scope':task['scope_hash'],'level':'strict','flags':['permission','production','shared_asset','public_interface'],'reason':'本轮涉及授权门禁、正式NAS发布与共享资产验证，采用严格验证及不同审核身份'})
    if task['status']=='planned':event('claim',{'summary':'按当前已核定范围进行真实发布与运行验收'})
    task=owner.call('/api/task?id='+TID);post(owner,'time_change',{'task':TID,'scope':task['scope_hash'],'mode':'work','phase':'release','reason':'从此刻记录实际发布收尾；此前开发投入未回填，完整性不作确认','rework':False})
    profile=SMB/'state/_private/roles/board-quality.json'
    if not profile.exists():lifecycle.write(profile,{**owner.call('/api/actors',{'actor':'board-quality'}),'url':URL})
    gov('member',{'actor':'board-quality','role':'runner','scope':'仅执行本项目本机批准的自动化验证，不修改开发任务','actor_kind':'agent'})
    environment='NAS Linux Python 3.11';post(owner,'runner',{'actor':'board-quality','environment':environment,'enabled':True,'reason':'本机已授权本项目受信回归套件'})
    op=owner.call('/api/operations')
    definitions=[{'id':'board-regression','version':'1','title':'固定输入完整回归与执行器反例','kind':'automated','priority':'critical','targets':['task:'+TID],'preconditions':'固定Git输入及隔离fixture','inputs':'当前实现提交与无生产状态的测试数据','steps':'运行完整行为回归，含执行器成败、取消、超时与清理','expected':'全部断言通过且不跳过，不改变真实项目数据','environment':environment,'resources':[]},
    {'id':'board-ui','version':'1','title':'真实渲染与角色边界复核','kind':'manual','priority':'critical','targets':['task:'+TID],'preconditions':'实际Edge渲染报告与截图','inputs':'当前代码与隔离状态','steps':'核对桌面/手机、浅深色、真实表单、项目切换与角色拒绝的报告和截图','expected':'无溢出、错误或项目资料泄漏；运行与资产状态对应真实记录','environment':'Edge headless plus reviewer inspection','resources':[]}]
    for definition in definitions:
        ref=definition['id']+'@1'
        if ref not in op['cases']:post(owner,'case',definition)
    op=owner.call('/api/operations');suite='board-regression@1'
    if suite not in op['suites']:post(owner,'suite',{'id':'board-regression','version':'1','commands':[{'case':'board-regression@1','argv':['{python}','-B','-X','utf8','tools/automation_checks.py']}],'environment':environment,'resources':['task-board-regression'],'timeout_seconds':180,'artifact_paths':['automation-results.json','project-runner.zip','evidence/automation-regression/stdout.log','evidence/automation-regression/stderr.log','evidence/automation-regression/processes.jsonl']})
    op=owner.call('/api/operations');suite_hash=op['suites'][suite]['manifest_hash']
    post(owner,'test_plan',{'task':TID,'scope':task['scope_hash'],'cases':['board-regression@1','board-ui@1'],'reason':'完整自动化回归与四种实际界面/授权边界复核，共同覆盖本轮五项交付'})
    bundle=E/('runner-source-'+commit[:12]+'.bundle');code,out,err=run(['git','bundle','create',bundle,'HEAD'],cwd=ROOT,evidence=E,purpose='Versioned input for the board-only NAS runner',timeout=30)
    assert code==0,err
    target=SMB/'runners/task-board';target.mkdir(parents=True,exist_ok=True)
    import shutil
    shutil.copy2(bundle,target/bundle.name);assert hashlib.sha256((target/bundle.name).read_bytes()).digest()==hashlib.sha256(bundle.read_bytes()).digest()
    config={'workspace':NAS+'/runners/task-board/repository','scratch':NAS+'/runners/task-board/scratch','output':NAS+'/runners/task-board/output','resource_root':NAS+'/runners/resource-locks','environment':environment,'approved_suites':{suite:suite_hash}}
    config_path=SMB/'state/_private/runner/task-board.json';lifecycle.write(config_path,config)
    script=f'''import sys,json,os
from pathlib import Path
root=Path({NAS!r});source=Path({source!r});sys.path[:0]=[str(source),str(source/'tools')]
os.environ['PATH']=str(root/'.venv/bin')+':'+os.environ.get('PATH','/usr/bin:/bin')
from owned_process import run
from task_board import lifecycle
e=source/'evidence/runner-activation';e.mkdir(parents=True,exist_ok=True)
repo=Path({config['workspace']!r});marker=repo/'PROJECT-BOARD-RUNNER.json';bundle=root/'runners/task-board'/{bundle.name!r}
def command(args,purpose):
 code,out,err=run(args,cwd=source,evidence=e,purpose=purpose,timeout=30)
 assert code==0,err.decode('utf8',errors='replace')[-1000:]
 return out
if repo.exists():assert marker.exists() and lifecycle.read(marker)=={{'project':'task-board','purpose':'approved regression input'}},'Unknown existing repository'
else:
 repo.mkdir(parents=True);command(['git','init','--bare','--quiet',repo],'Initialize only owned board regression repository');lifecycle.write(marker,{{'project':'task-board','purpose':'approved regression input'}})
command(['git','-C',repo,'fetch','--quiet',bundle,'+HEAD:refs/heads/verified'],'Import exact verified board source bundle')
assert command(['git','-C',repo,'rev-parse','verified'],'Verify runner input').decode().strip()=={commit!r}
for p in [root/'state/_private/roles/board-quality.json',root/'state/_private/runner/task-board.json']:os.chmod(p,0o600)
unit=root/'deploy/project-board-quality.service';link=Path.home()/'.config/systemd/user/project-board-quality.service'
if unit.exists():assert 'board-quality.json' in unit.read_text() and '--watch' in unit.read_text(),'Unknown existing worker service'
unit.write_text('[Unit]\\nDescription=Project-board approved quality runner\\nAfter=network-online.target project-board.service\\n\\n[Service]\\nType=simple\\nWorkingDirectory='+str(source)+'\\nExecStart="'+str(root/'.venv/bin/python')+'" -B -X utf8 "'+str(source/'tools/quality_runner.py')+'" --profile "'+str(root/'state/_private/roles/board-quality.json')+'" --config "'+str(root/'state/_private/runner/task-board.json')+'" --connect-ip 100.64.0.10 --watch\\nRestart=on-failure\\nRestartSec=5\\nTimeoutStopSec=45\\nKillMode=control-group\\nUMask=0077\\nNoNewPrivileges=yes\\nEnvironment=PYTHONDONTWRITEBYTECODE=1\\nEnvironment="PATH='+str(root/'.venv/bin')+':/usr/local/bin:/usr/bin:/bin"\\n\\n[Install]\\nWantedBy=default.target\\n',encoding='utf8')
if link.exists() or link.is_symlink():assert link.resolve()==unit.resolve(),'Unknown worker unit link'
else:link.symlink_to(unit)
command(['systemctl','--user','daemon-reload'],'Load only owned quality unit');command(['systemctl','--user','enable','--now','project-board-quality.service'],'Enable persistent board-only approved runner')
command(['systemctl','--user','restart','project-board-quality.service'],'Read new verified worker source before requesting work')
bundle.unlink()
print(json.dumps({{'runner_service':'project-board-quality.service','repository':str(repo),'source':str(source),'config':str(root/'state/_private/runner/task-board.json'),'profile':str(root/'state/_private/roles/board-quality.json')}}))
'''
    code,out,err=run(['ssh','-i','C:/Users/example-user/.ssh/nas_key','-o','BatchMode=yes','-o','ConnectTimeout=8','-o','StrictHostKeyChecking=yes','example-owner@192.0.2.10',shlex.quote(NAS+'/.venv/bin/python')+' -B -X utf8 -'],input_data=script.encode(),cwd=ROOT,evidence=E,purpose='Activate one persistent project-scoped NAS runner',timeout=70)
    if code:(E/'RUNNER-ACTIVATION-FAILED.log').write_bytes(out+err);raise RuntimeError(err.decode('utf8',errors='replace')[-1800:])
    record=json.loads(out);receipt=post(owner,'run_request',{'tasks':[TID],'scopes':{TID:task['scope_hash']},'suite':suite,'input_anchor':'git:'+commit,'reason':'真实产品升级的NAS固定输入全量运行验收'})
    record.update(run=receipt['run'],input_commit=commit,suite_hash=suite_hash,task=TID);lifecycle.write(E/'RUNNER-ACTIVATION.json',record)
    post(owner,'time_change',{'task':TID,'scope':task['scope_hash'],'mode':'wait','phase':'testing','reason':'等待受限NAS执行器的真实完整回归','rework':False})
    print(json.dumps({'runner':'project-board-quality.service','run':receipt['run'],'task':TID,'input':commit}))
if __name__=='__main__':main()
