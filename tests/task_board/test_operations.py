"""Actual HTTP tiers, timing, quality and curated-asset counterexamples."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch
import uuid
from . import test_planning as planning
from .test_workflow import candidate_blocked
from .test_governance import EV
from task_board.operations import Operations
from task_board.store import digest


class OperationsCase(unittest.TestCase):
    setUp=planning.PlanningCase.setUp
    tearDown=planning.PlanningCase.tearDown
    call=planning.PlanningCase.call
    gov=planning.PlanningCase.gov
    event=planning.PlanningCase.event
    atomic=planning.PlanningCase.atomic
    member=planning.PlanningCase.member
    charter=planning.PlanningCase.charter
    module=planning.PlanningCase.module
    plan=planning.PlanningCase.plan
    snap=planning.PlanningCase.snap
    review=planning.PlanningCase.review
    binding=planning.PlanningCase.binding

    def ops(self):return self.call('/api/projects/alpha/operations',profile=self.admin)[1]

    def op(self,action,payload,profile=None,revision=None,rid=None):
        return self.call('/api/projects/alpha/operations',{'request_id':rid or uuid.uuid4().hex,'expected_revision':self.ops()['revision'] if revision is None else revision,'action':action,'payload':payload},profile or self.admin)

    def scope(self,tid='new/one'):return self.hub.store('alpha').get(tid)['scope_hash']

    def assess(self,tid='new/one',level='light',flags=None):
        return self.op('assess',{'task':tid,'scope':self.scope(tid),'level':level,'flags':flags or [],'reason':'Reviewed actual bounded impact'})

    def adopt(self,profile='light'):
        self.charter();self.member();self.atomic();self.assertEqual(self.op('policy',{'profile':profile,'reason':'Explicit project adoption'})[0],201);self.assertEqual(self.assess()[0],201)

    def case(self,kind='manual',version='1'):
        p={'id':'check','version':version,'title':'Behavior and counterexample','kind':kind,'priority':'normal','targets':['task:new/one'],'preconditions':'Fixed input','inputs':'Known sample','steps':'Exercise boundary behavior','expected':'Reject invalid input, preserve expected output','environment':'fixture','resources':[]}
        r=self.op('case',p);self.assertEqual(r[0],201,r[1]);return p

    def set_plan(self,cases=None,tid='new/one'):
        return self.op('test_plan',{'task':tid,'scope':self.scope(tid),'cases':cases or ['check@1'],'reason':'Targeted behavior coverage'})

    def request(self,**kw):
        return self.op('run_request',{'tasks':['new/one'],'scopes':{'new/one':self.scope()},'input_anchor':'git:'+'c'*40,'reason':'Execute fixed version','suite':'suite@1',**kw})

    def runner(self):
        self.rp=self.hub.invite('alpha','quality-runner')
        self.gov('member',{'actor':'quality-runner','role':'runner','scope':'Only approved test work'})
        self.op('runner',{'actor':'quality-runner','environment':'fixture','enabled':True,'reason':'Local operator grants approved suites'})

    def suite(self,argv=None,resources=None):
        return self.op('suite',{'id':'suite','version':'1','commands':[{'case':'check@1','argv':argv or ['{python}','-c','print(1)']}],'environment':'fixture','resources':resources or [],'timeout_seconds':10,'artifact_paths':[]})

    def submit(self,**kw):
        return self.event('new/one','submit',{'summary':'Actual delivered change','completeness':'full','deliverable_ids':['D1'],'implementation_commit':'c'*40,'evidence':[],'verification':{'method':'inspection','summary':'Checked rendered output and differences','reason':'Reversible internal change'},'remaining':'None',**kw})

    def manual(self,**kw):
        return self.op('manual_run',{'tasks':['new/one'],'scopes':{'new/one':self.scope()},'input_anchor':'git:'+'c'*40,'reason':'Observed actual behavior','results':[{'case':'check@1','status':'passed','exit_code':None,'seconds':4,'summary':'Observed expected result'}],'evidence':EV,'artifacts':[],**kw})

    def test_light_delivery_has_no_extra_report_and_scope_change_invalidates_assessment(self):
        self.adopt();self.assertEqual(self.event('new/one','claim',{'summary':'Read scope'})[0],201)
        result=self.submit();self.assertEqual(result[0],201,result[1])
        self.assertEqual(self.event('new/one','accept',{'submission':result[1]['event_id'],'summary':'Verified bounded change','deliverable_ids':['D1'],'evidence':[]},self.admin)[0],201)
        spec=self.hub.store('alpha').get('new/one')['spec'];spec['description']='Changed actual scope'
        self.event('new/one','scope',{'spec':spec,'reason':'New scope'},self.admin)
        self.assertEqual(self.event('new/one','claim',{'summary':'Cannot keep old exemption'})[0],409)
        self.assertEqual(self.assess(level='light',flags=['permission'])[0],409)

    def test_worker_cannot_set_policy_and_foreign_ops_never_leak(self):
        self.adopt();self.assertEqual(self.op('policy',{'profile':'light','reason':'Self exempt'},self.a)[0],403)
        self.assertEqual(self.call('/api/projects/alpha/operations',profile=self.b)[0],404)
        self.assertEqual(self.op('time_change',{'task':'new/one','scope':self.scope(),'mode':'work','phase':'implementation','reason':'Not assigned','rework':False},self.a)[0],403)
        self.runner();self.assertEqual(self.op('policy',{'profile':'strict','reason':'No'},self.rp)[0],403)
        self.assertEqual(self.event('new/one','claim',{'summary':'Runner cannot develop'},self.rp)[0],403)

    def test_time_sessions_exclude_waiting_and_preserve_corrections_and_estimates(self):
        self.adopt();self.event('new/one','claim',{'summary':'Begin'})
        base={'task':'new/one','scope':self.scope(),'phase':'implementation','reason':'Known work','rework':False}
        with patch('task_board.operations.time.time',return_value=1000):r=self.op('time_change',{**base,'mode':'work'},self.a);sid=r[1]['session']
        with patch('task_board.operations.time.time',return_value=1060):self.op('time_change',{**base,'mode':'wait','reason':'Reviewer queue'},self.a)
        with patch('task_board.operations.time.time',return_value=1180):self.op('time_change',{**base,'mode':'stop'},self.a)
        result=self.ops()['time_report'];self.assertEqual(result['work_seconds'],60);self.assertEqual(result['wait_seconds'],120)
        self.assertEqual(self.op('time_correct',{'session':sid,'seconds':30,'reason':'Included idle time'},self.a)[0],403)
        self.assertEqual(self.op('time_correct',{'session':sid,'seconds':61,'reason':'Cannot exceed wall interval'})[0],400)
        self.op('time_correct',{'session':sid,'seconds':30,'reason':'Confirmed idle interval'})
        self.assertEqual(self.ops()['time_report']['work_seconds'],30)
        unknown=next(t for t in self.ops()['time_report']['tasks'] if t['task']=='plan/same');self.assertIsNone(unknown['work_seconds'])
        estimate={'task':'new/one','scope':self.scope(),'low':5,'likely':10,'high':20,'due':'2026-11-15T00:00:00+08:00','size':'small','uncertainty':'low','context':'Python, fixed tools','reason':'Compare similar bounded work'}
        self.assertEqual(self.op('estimate',estimate)[0],201);self.op('estimate',{**estimate,'likely':12,'reason':'New discovery'})
        self.assertEqual(len(self.ops()['estimates']['new/one']),2);self.assertIsNone(self.ops()['time_report']['forecasts']['new/one']['p80_minutes'])

    def test_immutable_cases_and_run_results_must_match_input_and_scope(self):
        self.adopt();self.case();self.assertEqual(self.op('case',self.case_payload())[0],409)
        self.set_plan();run=self.manual();self.assertEqual(run[0],201,run[1]);rid=run[1]['run']
        self.event('new/one','claim',{'summary':'Implement'})
        # Escalate without changing task scope: complete planning is required for
        # future dispatch, and structured current runs are required for delivery.
        self.assess(level='standard')
        candidate_blocked(self,self.submit(evidence=EV))
        self.assertEqual(self.submit(evidence=EV,test_runs=[rid],implementation_commit='d'*40)[0],409)
        self.plan();self.review();spec=self.hub.store('alpha').get('new/one')['spec'];spec['work']['planning']=self.binding()
        self.event('new/one','scope',{'spec':spec,'reason':'Adopt reviewed module'},self.admin);self.assess(level='standard');self.set_plan();rid=self.manual()[1]['run'];self.event('new/one','claim',{'summary':'Current approved version'})
        result=self.submit(evidence=EV,test_runs=[rid]);self.assertEqual(result[0],201,result[1])

    def case_payload(self):return {'id':'check','version':'1','title':'duplicate','kind':'manual','priority':'normal','targets':[],'preconditions':'one','inputs':'one','steps':'one','expected':'one','environment':'fixture','resources':[]}

    def test_runner_lease_cancellation_expiry_and_nonzero_pass_rejection(self):
        self.adopt();self.case('automated');self.set_plan();suite=self.suite();self.runner();r=self.request();self.assertEqual(r[0],201,r[1]);rid=r[1]['run']
        claim=self.op('run_claim',{'run':rid,'suite_hash':suite[1]['manifest_hash']},self.rp);self.assertEqual(claim[0],201,claim[1]);lease=claim[1]['lease']['id']
        self.assertEqual(self.op('run_claim',{'run':rid,'suite_hash':suite[1]['manifest_hash']},self.rp)[0],409)
        bad={'run':rid,'lease':lease,'status':'passed','results':[{'case':'check@1','status':'passed','exit_code':1,'seconds':1,'summary':'Forged pass'}],'artifacts':[],'evidence':EV,'environment':'fixture','summary':'False'}
        self.assertEqual(self.op('run_finish',bad,self.rp)[0],400)
        self.op('run_cancel',{'run':rid,'reason':'No longer needed'});self.assertTrue(self.op('run_heartbeat',{'run':rid,'lease':lease},self.rp)[1]['cancel'])
        self.assertEqual(self.op('run_finish',{**bad,'results':[{**bad['results'][0],'exit_code':0}]},self.rp)[0],409)
        self.assertEqual(self.op('run_finish',{**bad,'status':'cancelled','results':[{**bad['results'][0],'status':'cancelled','exit_code':-1}]},self.rp)[0],201)
        rid=self.request()[1]['run']
        with patch('task_board.operations.time.time',return_value=1000):old=self.op('run_claim',{'run':rid,'suite_hash':suite[1]['manifest_hash']},self.rp)[1]['lease']['id']
        with patch('task_board.operations.time.time',return_value=1031):new=self.op('run_claim',{'run':rid,'suite_hash':suite[1]['manifest_hash']},self.rp)[1]['lease']['id']
        self.assertNotEqual(old,new);self.assertEqual(self.op('run_heartbeat',{'run':rid,'lease':old},self.rp)[0],409)

    def test_request_idempotence_stale_revisions_and_append_only_chain(self):
        request={'profile':'light','reason':'Adopt'};rid=uuid.uuid4().hex
        self.assertEqual(self.op('policy',request,revision=0,rid=rid)[0],201)
        self.assertTrue(self.op('policy',request,revision=0,rid=rid)[1]['replayed'])
        self.assertEqual(self.op('policy',{**request,'reason':'Changed'},revision=0,rid=rid)[0],409)
        self.assertEqual(self.op('policy',request,revision=0)[0],409)
        self.assertTrue(Operations(self.hub.store('alpha')).verify()['passed'])
        with self.hub.store('alpha').connection() as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM operations_events')

    def test_asset_refinement_validation_and_private_registration_are_atomic(self):
        self.adopt();self.event('new/one','claim',{'summary':'Implement bounded asset'});submission=self.submit()
        self.event('new/one','accept',{'submission':submission[1]['event_id'],'summary':'Source checked','deliverable_ids':['D1'],'evidence':[]},self.admin)
        self.case();self.set_plan();sha='b'*64
        rid=self.manual(artifacts=[{'path':'method.txt','sha256':sha,'location':'private/verified/method.txt'}])[1]['run']
        candidate={'id':'method','version':'1','title':'Reusable method','kind':'methodology','source_tasks':['new/one'],'source_scopes':{'new/one':self.scope()},'problem':'Repeatable issue','applicability':'Local inputs','exclusions':'Other systems','dependencies':[],'owner':'root'}
        self.assertEqual(self.op('candidate',candidate)[0],201)
        self.assertEqual(self.op('candidate_promote',{'ref':'method@1','summary':'Too early','evidence':EV})[0],409)
        self.op('candidate_refine',{'ref':'method@1','input_anchor':'git:'+'c'*40,'artifact_path':'method.txt','sha256':sha,'license':'Internal','sensitivity':'private','location':'private/verified/method.txt','shareable':False,'summary':'Removed project-specific assumptions'})
        self.assertEqual(self.op('candidate_validate',{'ref':'method@1','runs':[rid],'summary':'Verified applicable cases'})[0],201)
        self.assertEqual(self.op('candidate_promote',{'ref':'method@1','summary':'Register verified private asset','evidence':EV})[0],201)
        self.assertEqual(self.snap()['assets']['method@1']['sha256'],sha)
        self.assertTrue(Operations(self.hub.store('alpha')).verify()['passed'])

    def test_real_runner_exports_fixed_commit_hashes_artifacts_and_cleans_scratch(self):
        from tools.quality_runner import execute
        from tools.task_board_client import Client
        from tools.owned_process import run
        root=self.state/'runner-fixture';repo=root/'repository';repo.mkdir(parents=True);logs=root/'evidence';scratch=root/'scratch';out=root/'output'
        for command in (['git','init',repo],['git','-C',repo,'config','user.email','fixture@invalid'],['git','-C',repo,'config','user.name','Fixture']):
            code,_,err=run(command,cwd=self.state,evidence=logs,purpose='Isolated runner fixture repository');self.assertEqual(code,0,err)
        (repo/'artifact.txt').write_text('Verified reusable bytes',encoding='utf8')
        (repo/'check.py').write_text("from pathlib import Path\nassert Path('artifact.txt').read_text()=='Verified reusable bytes'\n",encoding='utf8')
        for command in (['git','-C',repo,'add','.'],['git','-C',repo,'commit','-m','Fixed test input']):
            code,_,err=run(command,cwd=self.state,evidence=logs,purpose='Freeze isolated test input');self.assertEqual(code,0,err)
        _,commit,_=run(['git','-C',repo,'rev-parse','HEAD'],cwd=self.state,evidence=logs,purpose='Read fixed fixture version');commit=commit.decode().strip()
        self.adopt();self.case('automated');self.set_plan();self.runner()
        suite={'id':'suite','version':'1','commands':[{'case':'check@1','argv':['{python}','check.py']}],'environment':'fixture','resources':[],'timeout_seconds':10,'artifact_paths':['artifact.txt']}
        manifest=self.op('suite',suite)[1]['manifest_hash'];rid=self.request(input_anchor='git:'+commit)[1]['run']
        config={'workspace':str(repo),'scratch':str(scratch),'output':str(out),'environment':'fixture','approved_suites':{'suite@1':manifest}}
        profile={**self.rp,'url':self.url};client=Client(self.url,profile)
        self.assertEqual(execute(client,config,rid)['status'],'passed')
        result=self.ops()['runs'][rid];self.assertEqual(result['artifacts'][0]['sha256'],hashlib.sha256(b'Verified reusable bytes').hexdigest());self.assertEqual(list(scratch.iterdir()),[])
        # The published kit must run without the project-board package on sys.path.
        import io,zipfile
        from task_board.help import runner_kit
        kit=root/'standalone-kit';kit.mkdir()
        with zipfile.ZipFile(io.BytesIO(runner_kit())) as archive:archive.extractall(kit)
        profile_path=root/'runner-profile.json';profile_path.write_text(json.dumps(profile),encoding='utf8');config_path=root/'runner-config.json';config_path.write_text(json.dumps(config),encoding='utf8')
        kitid=self.request(input_anchor='git:'+commit)[1]['run']
        code,stdout,stderr=run([sys.executable,'-B',kit/'tools/quality_runner.py','--profile',profile_path,'--config',config_path,'--run',kitid],cwd=kit,evidence=logs,purpose='Actual standalone downloaded runner kit',timeout=30)
        self.assertEqual(code,0,stderr.decode());self.assertEqual(self.ops()['runs'][kitid]['status'],'passed')
        processes=list(out.rglob('processes.json'));self.assertTrue(processes);self.assertTrue(all(r['exited'] for r in json.loads(processes[0].read_text('utf8'))))
        # A later failure must not inherit the previous successful result.
        failed={**suite,'version':'2','commands':[{'case':'check@1','argv':['{python}','-c','raise SystemExit(2)']}],'artifact_paths':[]}
        config['approved_suites']['suite@2']=self.op('suite',failed)[1]['manifest_hash']
        failid=self.request(suite='suite@2',input_anchor='git:'+commit)[1]['run'];self.assertEqual(execute(client,config,failid)['status'],'failed')
        self.assertEqual(self.ops()['runs'][failid]['results'][0]['exit_code'],2)
        spawn="import subprocess,sys,time,os; subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],creationflags=0x08000000 if os.name=='nt' else 0); time.sleep(30)"
        slow={**failed,'version':'3','commands':[{'case':'check@1','argv':['{python}','-c',spawn]}],'timeout_seconds':1}
        config['approved_suites']['suite@3']=self.op('suite',slow)[1]['manifest_hash']
        slowid=self.request(suite='suite@3',input_anchor='git:'+commit)[1]['run'];self.assertEqual(execute(client,config,slowid)['status'],'timeout')
        import time
        cancelled={**slow,'version':'4','timeout_seconds':10};config['approved_suites']['suite@4']=self.op('suite',cancelled)[1]['manifest_hash'];cancelid=self.request(suite='suite@4',input_anchor='git:'+commit)[1]['run'];start=time.monotonic()
        self.assertEqual(execute(client,config,cancelid,lambda:time.monotonic()-start>.8)['status'],'cancelled')
        self.assertEqual(list(scratch.iterdir()),[])
        for path in out.rglob('processes.json'):self.assertTrue(all(r['exited'] for r in json.loads(path.read_text('utf8'))),str(path))
        # The same execution/hash record can validate a real shareable candidate.
        self.event('new/one','claim',{'summary':'Bounded source'})
        submitted=self.submit(implementation_commit=commit)
        self.event('new/one','accept',{'submission':submitted[1]['event_id'],'summary':'Real source and runtime reviewed','deliverable_ids':['D1'],'evidence':[]},self.admin)
        assetsha=hashlib.sha256(b'Verified reusable bytes').hexdigest()
        candidate={'id':'verified','version':'1','title':'Reusable tested bytes','kind':'test_data','source_tasks':['new/one'],'source_scopes':{'new/one':self.scope()},'problem':'Stable fixture','applicability':'Same schema','exclusions':'Secrets','dependencies':[],'owner':'root'}
        self.op('candidate',candidate)
        self.op('candidate_refine',{'ref':'verified@1','input_anchor':'git:'+commit,'artifact_path':'artifact.txt','sha256':assetsha,'license':'MIT','sensitivity':'public','location':result['artifacts'][0]['location'],'shareable':True,'summary':'Removed project coupling'})
        self.assertEqual(self.op('candidate_validate',{'ref':'verified@1','runs':[rid],'summary':'Actual approved fixture behavior and SHA'})[0],201)
        self.assertEqual(self.op('candidate_promote',{'ref':'verified@1','summary':'Validated immutable bytes','evidence':EV})[0],201)
        request={'request_id':uuid.uuid4().hex,'action':'publish','payload':{'asset':'verified@1','audience':['beta'],'shared_location':'approved/fixture/verified@1','review':'Reviewed license, absence of private data and actual validation','evidence':EV}}
        self.assertEqual(self.call('/api/projects/alpha/shared',request,self.admin)[0],201)
        self.assertEqual(len(self.call('/api/projects/beta/shared',profile=self.b)[1]['releases']),1)

    def test_strict_manual_verification_and_acceptance_are_independent(self):
        self.adopt();self.plan();self.review();spec=self.hub.store('alpha').get('new/one')['spec'];spec['work']['planning']=self.binding()
        self.event('new/one','scope',{'spec':spec,'reason':'Bind formal module'},self.admin);self.assess(level='strict',flags=['permission']);self.case();self.set_plan();self.event('new/one','claim',{'summary':'Strict scope'})
        own=self.manual()[1]['run']
        # The root tester is independent of same-agent, so its manual run is valid.
        self.assertEqual(self.submit(evidence=EV,test_runs=[own])[0],201)
        self.member(role='owner')
        latest=self.hub.store('alpha').get('new/one')['latest_submission']['id']
        payload={'submission':latest,'summary':'Cannot self approve','deliverable_ids':['D1'],'evidence':EV}
        self.assertEqual(self.event('new/one','accept',payload,self.a)[0],409)
        self.assertEqual(self.event('new/one','accept',payload,self.admin)[0],201)

    def test_test_resources_stay_locked_until_cancel_acknowledged(self):
        self.adopt();self.case('automated');self.set_plan();suite=self.suite(resources=['test-port']);self.runner()
        a=self.request()[1]['run'];b=self.request()[1]['run'];h=suite[1]['manifest_hash']
        lease=self.op('run_claim',{'run':a,'suite_hash':h},self.rp)[1]['lease']['id']
        self.assertEqual(self.op('run_claim',{'run':b,'suite_hash':h},self.rp)[0],409)
        self.op('run_cancel',{'run':a,'reason':'Stop current attempt'})
        self.assertEqual(self.op('run_claim',{'run':b,'suite_hash':h},self.rp)[0],409)
        self.op('run_finish',{'run':a,'lease':lease,'status':'cancelled','results':[{'case':'check@1','status':'cancelled','exit_code':-1,'seconds':0,'summary':'Stopped'}],'artifacts':[],'evidence':EV,'environment':'fixture','summary':'Cancelled and reaped'},self.rp)
        self.assertEqual(self.op('run_claim',{'run':b,'suite_hash':h},self.rp)[0],201)

    def test_history_forecast_uses_completed_declared_matching_samples(self):
        self.adopt()
        for i in range(6):
            tid='sample/'+str(i);self.atomic(tid,[f'sample/{i}/']);self.assess(tid)
            self.op('estimate',{'task':tid,'scope':self.scope(tid),'low':1,'likely':20,'high':90,'due':'','size':'small','uncertainty':'low','context':'same controlled toolchain','reason':'Known bounded work'})
            self.event(tid,'claim',{'summary':'Track explicit work'},self.admin)
            base={'task':tid,'scope':self.scope(tid),'phase':'implementation','reason':'Known work','rework':False}
            with patch('task_board.operations.time.time',return_value=10000+i*10000):self.op('time_change',{**base,'mode':'work'})
            with patch('task_board.operations.time.time',return_value=10000+i*10000+(i+1)*600):self.op('time_change',{**base,'mode':'stop'})
            self.op('time_complete',{'task':tid,'scope':self.scope(tid),'summary':'Complete fixture record'})
            result=self.event(tid,'submit',{'summary':'Delivered','completeness':'full','deliverable_ids':['D1'],'implementation_commit':'c'*40,'evidence':[],'remaining':'None','verification':{'method':'inspection','summary':'Observed expected result','reason':'Small reversible work'}},self.admin)
            self.assertEqual(result[0],201,result[1]);self.event(tid,'accept',{'submission':result[1]['event_id'],'summary':'Checked','deliverable_ids':['D1'],'evidence':[]},self.admin)
        f=self.ops()['time_report']['forecasts']['sample/0'];self.assertEqual(f['samples'],5);self.assertEqual(f['p50_minutes'],40);self.assertEqual(f['p80_minutes'],50)

    def test_restoring_same_scope_content_does_not_restore_old_exemptions_or_runs(self):
        self.adopt();self.case();self.set_plan();rid=self.manual()[1]['run'];original=self.hub.store('alpha').get('new/one')['spec'];changed=deepcopy(original);changed['description']='Temporary different scope'
        self.event('new/one','scope',{'spec':changed,'reason':'New work'},self.admin);self.event('new/one','scope',{'spec':original,'reason':'Restore same content as a new version'},self.admin)
        self.assertFalse(self.ops()['effective']['new/one']['assessed']);self.assertEqual(self.assess()[0],201);self.event('new/one','claim',{'summary':'Current version'})
        self.assertEqual(self.submit(test_runs=[rid],verification={'method':'automated','summary':'Old run cannot stand in','reason':'Fixed cases'})[0],409)

    def test_case_updates_do_not_float_old_plans_and_withdrawal_blocks_old_results(self):
        self.adopt();self.case();self.set_plan();rid=self.manual()[1]['run'];p=self.case_payload();p.update(version='2',priority='critical',targets=['task:new/one']);self.assertEqual(self.op('case',p)[0],201)
        self.assertEqual(self.ops()['test_plans']['new/one']['cases'],['check@1']);self.assertEqual(self.ops()['suggested_cases']['new/one'],['check@2'])
        self.atomic('unrelated/one',['unrelated/']);self.assertEqual(self.ops()['suggested_cases']['unrelated/one'],[])
        self.assertEqual(self.op('case_retire',{'ref':'check@1','mode':'withdrawn','reason':'Expected behavior was wrong'})[0],201)
        self.event('new/one','claim',{'summary':'Current scope'})
        candidate_blocked(self,self.submit(test_runs=[rid],verification={'method':'automated','summary':'Cannot use withdrawn proof','reason':'Known defect'}))

    def test_cross_project_forecast_only_uses_explicit_fixed_shared_benchmark_bytes(self):
        self.adopt();document=json.dumps({'schema':1,'unit':'minutes','groups':[{'category':'backend','size':'small','uncertainty':'low','context':'portable reviewed setup','samples':6,'p50_minutes':30,'p80_minutes':45}]},ensure_ascii=False,indent=2)+'\n';sha=hashlib.sha256(document.encode()).hexdigest()
        asset={'id':'benchmark','version':'1','kind':'methodology','source':'Explicit old reviewed aggregate reference','license':'MIT','sensitivity':'public','sha256':sha,'location':'fixture/benchmark.json','owner':'root','shareable':True,'evidence':EV}
        self.assertEqual(self.gov('asset',asset,project='beta')[0],201)
        publish={'request_id':uuid.uuid4().hex,'action':'publish','payload':{'asset':'benchmark@1','audience':['alpha'],'shared_location':'approved/benchmark.json','review':'Reviewed context and aggregate fields only','evidence':EV}}
        self.assertEqual(self.call('/api/projects/beta/shared',publish,self.admin)[0],201)
        self.assertEqual(self.op('benchmark_import',{'asset':'bench','document':document,'reason':'Cannot import before explicit consumption'})[0],409)
        self.call('/api/projects/alpha/shared',{'request_id':uuid.uuid4().hex,'action':'consume','payload':{'alias':'bench','ref':'beta/benchmark@1','reason':'Explicitly approved version','tests':'Reviewed aggregate data and SHA'}},self.admin)
        self.assertEqual(self.op('benchmark_import',{'asset':'bench','document':document+' ','reason':'Wrong bytes'})[0],409)
        self.assertEqual(self.op('benchmark_import',{'asset':'bench','document':document,'reason':'Same controlled setup'})[0],201)
        self.op('estimate',{'task':'new/one','scope':self.scope(),'low':1,'likely':20,'high':60,'due':'','size':'small','uncertainty':'low','context':'portable reviewed setup','reason':'Use fixed shared reference'})
        f=self.ops()['time_report']['forecasts']['new/one'];self.assertEqual(f['p80_minutes'],45);self.assertEqual(f['source'],'beta/benchmark@1')
        self.call('/api/projects/beta/shared',{'request_id':uuid.uuid4().hex,'action':'withdraw','payload':{'ref':'beta/benchmark@1','reason':'Reference withdrawn','migration':'Choose a reviewed replacement','evidence':EV}},self.admin)
        self.assertIsNone(self.ops()['time_report']['forecasts']['new/one']['p80_minutes'])

    def test_noncode_light_delivery_uses_real_artifact_anchor_without_git_or_extra_report(self):
        self.adopt();self.atomic('docs/one',['docs/'],category='documentation',baseline='artifact:sha256:'+'b'*64);self.assess('docs/one');self.event('docs/one','claim',{'summary':'Bounded document work'})
        r=self.event('docs/one','submit',{'summary':'Updated document','completeness':'full','deliverable_ids':['D1'],'artifact':{'ref':'verified/report.txt','sha256':'d'*64},'evidence':[],'remaining':'None','verification':{'method':'inspection','summary':'Compared document differences and content','reason':'Reversible internal documentation'}})
        self.assertEqual(r[0],201,r[1]);self.assertEqual(self.hub.store('alpha').get('docs/one')['latest_submission']['implementation_commit'],'')
        self.assertEqual(self.event('docs/one','accept',{'submission':r[1]['event_id'],'summary':'Actual artifact inspected','deliverable_ids':['D1'],'evidence':[]},self.admin)[0],201)
