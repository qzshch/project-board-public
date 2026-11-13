"""New-project, distinct-role NAS drill with real Git commits and repair loop."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from task_board import lifecycle
from task_board.projects import ProjectHub
from task_board.governance import Governance
from task_board.store import digest
from task_board_client import Client, ClientError
from owned_process import run

ROOT=Path(__file__).resolve().parents[1];STATE=ROOT/'state'
def main():
    stamp=time.strftime('%Y%m%d-%H%M%S');E=ROOT/'evidence/drill'/stamp;E.mkdir(parents=True)
    project='onboarding-'+stamp.lower();report={'project_id':project,'checks':[],'remote':[],'complete':False};profiles={};scratch=E/'artifact-repo';scratch.mkdir();private=E/'_private';private.mkdir()
    settings=lifecycle.read(STATE/'_private/server.json');public=settings['public_url'];local='http://127.0.0.1:'+str(settings['port'])
    admin_profile={**lifecycle.read(STATE/'_private/admin.json'),'url':local};admin=Client(local,admin_profile)
    def dump(path,value):lifecycle.write(path,value)
    def check(ok,label):
        if not ok:raise AssertionError(label)
        report['checks'].append(label)
    def process(args,purpose,cwd=ROOT,input_data=None,timeout=50):
        code,out,err=run(args,cwd=cwd,evidence=E,purpose=purpose,input_data=input_data,timeout=timeout,env={**os.environ,'GIT_TERMINAL_PROMPT':'0','GCM_INTERACTIVE':'never'})
        if code or (not out and err):raise RuntimeError(err.decode('utf8',errors='replace')[:1200])
        return out.decode('utf8').strip()
    def git(*args):return process(['git',*args],'owned demo Git repository',scratch)
    def client(profile):return Client(local,{**profile,'url':local})
    def gov(c,action,payload):return c.call('/api/governance',{'request_id':str(uuid.uuid4()),'expected_revision':c.call('/api/governance')['revision'],'action':action,'payload':payload})
    def event(c,tid,action,payload):
        task=c.task(tid) if action!='create' else None
        return c.call('/api/events',{'request_id':str(uuid.uuid4()),'task_id':tid,'action':action,'expected_revision':task['revision'] if task else 0,'scope_version':task['scope_version'] if task else 1,'payload':payload})
    def remote(actor,mode,**data):
        packet={'mode':mode,'profile':{**profiles[actor],'url':public},'url':public,'connect_ip':settings['network_ownership']['connect_ip'],'client_source':(ROOT/'tools/task_board_client.py').read_text('utf8'),**data}
        source=(ROOT/'tools/remote_agent.py').read_text('utf8');command='python3 -c '+shlex.quote(source)
        result=json.loads(process(['ssh','-i','C:/Users/example-user/.ssh/nas_key','-o','BatchMode=yes','-o','ConnectTimeout=8','-o','StrictHostKeyChecking=yes','example-owner@192.0.2.10',command],'scoped remote '+actor+' '+mode,input_data=json.dumps(packet,ensure_ascii=False).encode(),timeout=50))
        dump(E/(actor+'-'+mode+'-'+str(len(report['remote']))+'.json'),result);report['remote'].append({'actor':actor,'mode':mode,'host':result['remote_host'],'checks':len(result['checks'])});return result
    def create_task(owner,tid,category,role,paths,baseline,depends=(),contracts=(),assets=()):
        spec={'id':tid,'title':tid+' demo atom','kind':'atomic','description':'Only the project-specific frozen input and delegated paths; no other project data.','deliverables':[{'id':'D1','label':'Actual artifact and behavior/counterexample evidence'}],'registered':True,'claimable':True,'allowed_paths':paths,'depends_on':list(depends),'source':{'demo':True},'work':{'category':category,'role':role,'inputs_known':True,'inputs':['spec@'+input_sha],'outputs':['artifact:'+tid],'contracts':list(contracts),'assets':list(assets),'resources':[],'couplings':[],'baseline':baseline,'acceptance':'Actual source, receipt, SHA and test results; known failure must be repaired'}}
        event(owner,tid,'create',{'spec':spec,'reason':'New-project no-history onboarding drill'});return spec
    def artifact_commit(branch,base,result,message):
        if branch in git('branch','--format=%(refname:short)').splitlines():git('switch',branch)
        else:git('switch','-c',branch,base)
        for name,item in result['artifacts'].items():
            path=scratch/name;assert path.resolve().is_relative_to(scratch.resolve());path.parent.mkdir(parents=True,exist_ok=True);path.write_text(item['content'],encoding='utf8',newline='\n');assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
        git('add','--',*result['artifacts'].keys());git('commit','-m',message);return git('rev-parse','HEAD')
    def submit(actor,tid,result,commit,addresses=()):
        # Local copy is immutable evidence; remote Agent submits its own result
        # with the exact real Git artifact commit, never a fabricated anchor.
        record=E/(actor+'-artifacts-'+commit[:12]+'.json');dump(record,result)
        payload={'summary':'Actual remote candidate; '+('tests passed' if result['tests']['passed'] else 'known test failure retained for review/repair'),'completeness':'full','deliverable_ids':['D1'],'evidence':[{'path':str(record),'sha256':hashlib.sha256(record.read_bytes()).hexdigest()}],'tests':json.dumps(result['tests'],ensure_ascii=False),'remaining':'none' if result['tests']['passed'] else 'repair behavior failure before acceptance','addresses':list(addresses)}
        return remote(actor,'submit',task_id=tid,payload=payload,implementation_commit=commit)['receipt']
    def accept(owner,tid,receipt,evidence_path):
        return event(owner,tid,'accept',{'submission':receipt['event_id'],'summary':'Reviewed actual artifacts/test results and role scope','deliverable_ids':['D1'],'evidence':[{'path':str(evidence_path),'sha256':hashlib.sha256(evidence_path.read_bytes()).hexdigest()}]})
    def merge(owner,tid,submission,branch):
        git('switch','main');git('merge','--no-ff',branch,'-m','Merge reviewed '+branch);commit=git('rev-parse','HEAD')
        event(owner,tid,'merge',{'submission':submission['event_id'],'summary':'Actual Git branch integration','commit':commit,'evidence':[{'path':str(E/'processes.jsonl'),'sha256':hashlib.sha256((E/'processes.jsonl').read_bytes()).hexdigest()}]});return commit
    input_spec={'function':'normalize_label(value:str)->str','behavior':['strip outer whitespace','lowercase Unicode','TypeError for non-str','ValueError for empty after stripping']};input_sha=digest(input_spec)
    fixed="def normalize_label(value):\n    if not isinstance(value, str):\n        raise TypeError('str required')\n    result = value.strip().lower()\n    if not result:\n        raise ValueError('nonempty required')\n    return result\n"
    broken=fixed.replace('value.strip().lower()','value.lower()')
    owner=None
    try:
        definition=E/'project-definition.json';dump(definition,{'id':project,'name':'新项目角色接入演练 '+stamp,'description':'独立示例；真实NAS角色客户端、产物、返修与交接验收；不是业务生产任务'})
        process([sys.executable,'-B','-X','utf8',ROOT/'tools/new_project.py','--definition',definition,'--owner','demo-lead','--out',private/'initial-owner.json'],'create independent demo project and scoped owner')
        profiles['demo-lead']=lifecycle.read(private/'initial-owner.json');owner=client(profiles['demo-lead'])
        for actor,role in [('demo-heir','se'),('demo-research','researcher'),('demo-dev','developer'),('demo-doc','documenter'),('demo-test','tester')]:
            profiles[actor]=owner.call('/api/actors',{'actor':actor})
            gov(owner,'member',{'actor':actor,'role':role,'scope':'Only this onboarding project and assigned atomic task'})
        knowledge={'background':'A new session can onboard without prior chat history.','goals':'Research, implement, document, test, repair, merge and hand off a small pure function.','non_goals':'No game/device actions or other projects private data.','constraints':'Independent Git branches and delegated paths; no secrets in artifacts; frozen interface and asset versions.','materials':[{'title':'Input specification','location':'SE-provided stdin packet','version':'1','sha256':input_sha}],'entries':[]};gov(owner,'knowledge',knowledge)
        git('init','-b','main');git('config','user.name','Project Board Demo');git('config','user.email','demo@project-board.local');(scratch/'README.md').write_text('Formal onboarding evidence repository.\n',encoding='utf8');git('add','README.md');git('commit','-m','Freeze initial demo baseline');base=git('rev-parse','HEAD')
        evidence_file=E/'input-spec.json';dump(evidence_file,input_spec);ev=[{'path':str(evidence_file),'sha256':hashlib.sha256(evidence_file.read_bytes()).hexdigest()}]
        contract={'id':'label-api','version':'1','owner':'demo-lead','signature':'normalize_label(value:str)->str','units':'Unicode string','errors':'TypeError for non-str, ValueError for whitespace only','transaction':'pure function','idempotency':'same input same output','source':'input-spec@'+input_sha,'producers':['impl/label'],'consumers':['docs/label','test/label'],'compatibility':'v1 fixed; destructive changes need impact confirmation','evidence':ev};gov(owner,'contract_freeze',contract)
        # Publish only a newly authored generic method; no business resource is
        # promoted or copied. Publisher audit explicitly fixes this audience.
        source=(ROOT/'templates/agent-brief.md').read_bytes();sha=hashlib.sha256(source).hexdigest();ref='brief-method-'+stamp
        publisher_prefix='/api/projects/task-board'
        def pg(action,payload):
            return admin.call(publisher_prefix+'/governance',{'request_id':str(uuid.uuid4()),'expected_revision':admin.call(publisher_prefix+'/governance')['revision'],'action':action,'payload':payload})
        def shared(c,action,payload,prefix='/api'):
            return c.call(prefix+'/shared',{'request_id':str(uuid.uuid4()),'action':action,'payload':payload})
        pg('asset',{'id':ref,'version':'1','kind':'methodology','source':'Independently authored generic agent-brief template','license':'Internal use by explicitly authorized projects','sensitivity':'public','sha256':sha,'location':'templates/agent-brief.md','owner':'root','shareable':True,'evidence':ev})
        shared(admin,'publish',{'asset':ref+'@1','audience':[project],'shared_location':'https://github.com/example-owner/project-board/blob/'+process(['git','rev-parse','HEAD'],'source baseline')+'/templates/agent-brief.md','review':'SE reviewed generic scope, provenance, internal license, sensitivity, hash and explicit consumer','evidence':ev},publisher_prefix)
        shared(owner,'consume',{'ref':'task-board/'+ref+'@1','alias':'brief-method','reason':'Demo owner pins reviewed method v1','tests':'Content SHA verified: '+sha})
        research_spec=create_task(owner,'research/spec','research','researcher',['research/'],base)
        rr=remote('demo-research','generate',task_id='research/spec',role='researcher',files={'research/spec.json':json.dumps(input_spec,ensure_ascii=False,indent=2)+'\n'})
        rc=artifact_commit('research',base,rr,'Record reviewed input research');rs=submit('demo-research','research/spec',rr,rc);accept(owner,'research/spec',rs,E/'input-spec.json');research_main=merge(owner,'research/spec',rs,'research')
        create_task(owner,'impl/label','backend','developer',['src/label/'],research_main,['research/spec'],['label-api@1'],['brief-method'])
        create_task(owner,'docs/label','documentation','documenter',['docs/label/'],research_main,['research/spec'],['label-api@1'],['brief-method'])
        br=remote('demo-dev','generate',task_id='impl/label',role='developer',files={'src/label/normalize.py':broken},code=broken)
        check(not br['tests']['passed'],'Known failing candidate preserves actual failing tests')
        bc=artifact_commit('development',research_main,br,'Candidate with whitespace failure');bs=submit('demo-dev','impl/label',br,bc)
        event(owner,'impl/label','request_changes',{'submission':bs['event_id'],'reason':'Actual tests demonstrate whitespace normalization bug','findings':[{'description':'Outer whitespace is not removed before lowercase/empty validation','acceptance':'All four behavior/counterexample tests pass for the exact code SHA'}]})
        # Documentation can execute while backend repair remains active because
        # write paths are disjoint and both consume a frozen read-only contract.
        dr=remote('demo-doc','generate',task_id='docs/label',role='documenter',files={'docs/label/README.md':'# Label API v1\n\nnormalize_label(value:str) strips whitespace and lowercases Unicode. Non-str raises TypeError; empty raises ValueError. Pure and idempotent.\n'})
        dc=artifact_commit('documentation',research_main,dr,'Document frozen API v1');ds=submit('demo-doc','docs/label',dr,dc);accept(owner,'docs/label',ds,E/'input-spec.json');merge(owner,'docs/label',ds,'documentation')
        check(owner.call('/api/task?id=impl/label')['status']=='changes_requested','Independent documentation merges while implementation is in repair')
        fr=remote('demo-dev','generate',task_id='impl/label',role='developer',files={'src/label/normalize.py':fixed},code=fixed)
        check(fr['tests']['passed'],'Repaired exact code passes real remote behavior tests')
        fc=artifact_commit('development',research_main,fr,'Repair whitespace handling');finding=owner.task('impl/label')['findings'][0]['id'];fs=submit('demo-dev','impl/label',fr,fc,[finding])
        check(owner.task('impl/label')['findings'][0]['open'],'Resubmission alone does not close finding');accept(owner,'impl/label',fs,E/('demo-dev-artifacts-'+fc[:12]+'.json'));check(not owner.task('impl/label')['findings'][0]['open'],'Reviewer acceptance closes addressed finding');integrated=merge(owner,'impl/label',fs,'development')
        create_task(owner,'test/label','test','tester',['tests/label/'],integrated,['impl/label','docs/label'],['label-api@1'],['brief-method'])
        git('switch','main');exact_code=(scratch/'src/label/normalize.py').read_text('utf8');check(exact_code==fixed,'Merged source exactly matches remotely tested fixed code')
        test_source='import unittest\n# Behavioral cases: strip, Unicode lowercase, empty rejection, non-str rejection.\n'
        tr=remote('demo-test','generate',task_id='test/label',role='tester',files={'tests/label/README-test-cases.py':test_source},code=exact_code);check(tr['tests']['passed'] and tr['tests']['run']==4,'Independent tester verifies integrated exact source on NAS')
        tc=artifact_commit('testing',integrated,tr,'Record independent behavior cases');ts=submit('demo-test','test/label',tr,tc);accept(owner,'test/label',ts,E/('demo-test-artifacts-'+tc[:12]+'.json'));final_commit=merge(owner,'test/label',ts,'testing')
        for tid in ('research/spec','impl/label','docs/label','test/label'):
            task=owner.task(tid);event(owner,tid,'native',{'submission':task['latest_submission']['id'],'summary':'Real integrated artifact execution on NAS; exact tested source SHA retained','commit':task['last_merge']['commit'],'evidence':[{'path':str(E/('demo-test-artifacts-'+tc[:12]+'.json')),'sha256':hashlib.sha256((E/('demo-test-artifacts-'+tc[:12]+'.json')).read_bytes()).hexdigest()}]})
        # A provider update cannot float consumer references.
        pg('asset',{'id':ref,'version':'2','kind':'methodology','source':'Same generic method plus explicit second-version metadata','license':'Internal use by explicitly authorized projects','sensitivity':'public','sha256':sha,'location':'templates/agent-brief.md','owner':'root','shareable':True,'evidence':ev})
        shared(admin,'publish',{'asset':ref+'@2','audience':[project],'shared_location':'repo:project-board/templates/agent-brief.md@sha256:'+sha,'review':'Explicit v2 review; v1 remains unchanged','evidence':ev},publisher_prefix)
        check(owner.call('/api/shared')['consumption']['brief-method']['release'].endswith('@1'),'Provider v2 publication leaves consumer pinned to v1')
        shared(owner,'upgrade',{'ref':'task-board/'+ref+'@2','alias':'brief-method','reason':'Consumer owner explicitly approves v2','tests':'Same content hash verified and independent integration tests passed'})
        # Complete interface impact confirmations through distinct identities.
        gov(owner,'contract_freeze',{**contract,'version':'2','compatibility':'future v2; migration recorded'})
        gov(owner,'contract_propose',{'id':'label-v2','contract':'label-api@1','replacement':'label-api@2','migration':'All completed consumers retain v1 audit; future scopes must explicitly select v2. No silent rewriting.','tests':'Re-run four behavioral cases for every migrated implementation and dependent task.'})
        change=owner.call('/api/governance')['changes']['label-v2'];impact_hash=digest(change['impact'])
        try:gov(owner,'contract_execute',{'id':'label-v2'});raise AssertionError('Unconfirmed change executed')
        except ClientError as e:check(e.status==409,'Destructive switch refused before all impact confirmations')
        for actor in change['required']:
            payload={'id':'label-v2','impact_hash':impact_hash,'summary':'Reviewed own consumer scope, migration and tests'}
            if actor in ('demo-dev','demo-doc','demo-test'):remote(actor,'confirm',payload=payload)
            else:gov(client(profiles[actor]),'contract_confirm',payload)
        gov(owner,'contract_execute',{'id':'label-v2'});check(owner.call('/api/governance')['changes']['label-v2']['executed'],'Confirmed change executed with preserved impact audit')
        gov(owner,'package',{'id':'onboarding-package','tasks':['research/spec','impl/label','docs/label','test/label'],'source':'New project drill, not imported historical completion','unknown':'none in this bounded example; other project relations remain unknown'})
        gov(owner,'handoff_propose',{'to':'demo-heir','risks':'All four tasks runtime accepted; label-api@1 retired for future work, v2 frozen; asset pinned to v2.','materials':['input-spec@'+input_sha,'label-api@2'],'reason':'A new session inherits this project'})
        h=owner.call('/api/governance')['handoff'];heir=client(profiles['demo-heir']);gov(heir,'handoff_accept',{'scope':h['scope'],'summary':'Read project materials, task receipts, asset pins and interface migration; accept ownership'})
        try:gov(owner,'decision',{'summary':'old owner write','reason':'must fail','evidence':ev});raise AssertionError('Old owner retained management')
        except ClientError as e:check(e.status==403,'Accepted handoff revokes former owner management')
        dump(STATE/'_private/roles'/('demo-owner-'+stamp+'.json'),{**profiles['demo-heir'],'url':public})
        report.update(final_artifact_commit=final_commit,task_head=heir.call('/api/snapshot')['head'],governance=heir.call('/api/governance/verify'),remote_files_remaining=False,new_owner='demo-heir',scoped_owner_profile=str(STATE/'_private/roles'/('demo-owner-'+stamp+'.json')))
        git('bundle','create',str(E/'artifacts.bundle'),'--all');check(not git('status','--porcelain'),'All demo source is committed and preserved in the formal Git bundle')
        report['complete']=True
    finally:
        report['revoked']=[]
        for actor in profiles:
            if actor=='demo-heir' and report['complete']:continue
            try:admin.call('/api/projects/'+project+'/actors/revoke',{'actor':actor,'reason':'Remote onboarding drill completed or failed; revoke temporary role identity'});report['revoked'].append(actor)
            except ClientError as err:report.setdefault('cleanup_errors',[]).append({'actor':actor,'status':err.status})
        identity_file=private/'initial-owner.json'
        if identity_file.exists():identity_file.unlink()
        if report['complete']:
            assert scratch.resolve().is_relative_to(E.resolve()) and not scratch.is_symlink() and not any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()) for p in scratch.rglob('*'));shutil.rmtree(scratch);report['local_scaffold_removed']=not scratch.exists()
        else:report['preserved_failure_scaffold']=str(scratch)
        dump(E/'RESULT.json',report)
    print(json.dumps({'complete':report['complete'],'project_id':project,'evidence':str(E),'checks':len(report['checks']),'remote_operations':len(report['remote']),'new_owner':report.get('new_owner')},ensure_ascii=False))
if __name__=='__main__':main()
