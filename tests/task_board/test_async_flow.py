"""Independent HTTP and real Git proofs of the bounded async collaboration flow."""
import json,uuid,unittest
from copy import deepcopy
from . import test_git_tracking as gf,test_worker_access as wf,test_workflow as flow
from . import test_governance as gov_fixture

class AsyncFlowCase(unittest.TestCase):
    setUp=gf.GitCase.setUp;tearDown=gf.GitCase.tearDown;call=gf.GitCase.call
    gov=gf.GitCase.gov;atomic=gf.GitCase.atomic;event=gf.GitCase.event
    git=gf.GitCase.git;action=gf.GitCase.action;repository=gf.GitCase.repository
    op=flow.WorkflowCase.op;open=wf.WorkerAccessCase.open;seed=wf.WorkerAccessCase.seed;join=wf.WorkerAccessCase.join;worker=wf.WorkerAccessCase.worker
    def s(self,tid='new/one'):
        t=self.hub.store('alpha').get(tid);return {'task':tid,'scope':t['scope_hash'],'scope_version':t['scope_version']}
    def ready(self,tid='new/one',**work):
        self.open();p=self.worker();self.atomic(tid,**work);r=self.event(tid,'claim',{'summary':'Pick published scope'},p);self.assertEqual(r[0],201,r[1]);return p
    def delivery(self,tid,p,commit='c'*40,**kw):
        return self.event(tid,'submit',{'summary':'Synthetic fixture output, not business evidence','completeness':'full','deliverable_ids':['D1'],'implementation_commit':commit,'evidence':gov_fixture.EV,'tests':'Fixture admission observation only','remaining':'none','addresses':[],**kw},p)
    def accept(self,tid):
        t=self.hub.store('alpha').get(tid);return self.event(tid,'accept',{'submission':t['latest_submission']['id'],'summary':'Fixture SE reviewed exact current result','deliverable_ids':['D1'],'evidence':gov_fixture.EV},self.admin)
    def open_thread(self,p,kind='blocker',pause=False,id='question',tid='new/one'):
        return self.op('thread_open',{**self.s(tid),'id':id,'kind':kind,'title':'Question within current boundary','body':'Record uncertainty without modifying approved scope','to':['SE'],'pause':pause,'affected_step':'implementation'},p)
    def test_blocker_and_deviation_can_queue_without_se_reply_but_not_accept(self):
        for i,kind in enumerate(('blocker','deviation')):
            tid='work/'+kind;p=self.ready(tid,resources=[]);self.assertEqual(self.open_thread(p,kind,id='q'+str(i),tid=tid)[0],201)
            r=self.delivery(tid,p);self.assertEqual(r[0],201,r[1]);self.assertEqual(self.accept(tid)[0],409)
            wfdata=self.call('/api/projects/alpha/workflow/task?task='+tid,profile=p)[1];self.assertTrue(wfdata['delivery_readiness']['candidate_received']);self.assertFalse(wfdata['delivery_readiness']['ready_for_acceptance'])
            self.assertEqual(self.op('thread_resolve',{'thread':'q'+str(i),'summary':'Worker cannot dismiss review obstacle'},p)[0],403)
            self.assertEqual(self.op('thread_resolve',{'thread':'q'+str(i),'summary':'SE actually reviewed recorded issue'})[0],201);self.assertEqual(self.accept(tid)[0],201)
    def test_worker_can_wait_then_continue_before_reply_including_discussion(self):
        p=self.ready();self.assertEqual(self.open_thread(p,'discussion',pause=True)[0],201)
        self.assertEqual(self.op('thread_wait',{'thread':'question','pause':False,'summary':'Continue safe independent part'},p)[0],201)
        self.assertEqual(self.event('new/one','progress',{'summary':'Continue within fixed scope'},p)[0],201);self.assertEqual(self.delivery('new/one',p)[0],201);self.assertEqual(self.accept('new/one')[0],201)
    def test_wait_choice_is_owned_current_scope_and_does_not_override_se_stop(self):
        p=self.ready();other=self.worker();self.open_thread(p)
        self.assertEqual(self.op('thread_wait',{'thread':'question','pause':True,'summary':'Not my wait'},other)[0],403)
        self.assertEqual(self.op('thread_decide',{'thread':'question','decision':'stop','summary':'Formal stop of this scope','reference':''})[0],201)
        self.assertEqual(self.op('thread_wait',{'thread':'question','pause':False,'summary':'Cannot override stop'},p)[0],409)
        self.assertEqual(self.op('time_change',{'task':'new/one','scope':self.s()['scope'],'mode':'work','phase':'implementation','reason':'Cannot override stop','rework':False},p)[0],409)
        self.assertEqual(self.delivery('new/one',p)[0],201);self.assertEqual(self.accept('new/one')[0],409)
    def test_candidate_collects_missing_criteria_and_tests_without_self_acceptance(self):
        p=self.ready();plan={**self.s(),'id':'criteria','items':[{'id':'A','deliverable':'D1','expected':'Observed boundary','method':'manual'}],'defaults':'','git_required':False,'repo':'','reason':'SE fixes expected result'};self.assertEqual(self.op('criteria_plan',plan)[0],201)
        self.assertEqual(self.delivery('new/one',p)[0],201);self.assertEqual(self.accept('new/one')[0],409)
        t=self.hub.store('alpha').get('new/one');self.assertEqual(self.event('new/one','accept',{'submission':t['latest_submission']['id'],'summary':'No self approval','deliverable_ids':['D1'],'evidence':gov_fixture.EV},p)[0],403)
        self.assertEqual(self.delivery('new/one',p,test_runs=['foreign-or-missing'])[0],404)
    def test_submission_human_gate_moves_to_accept_not_disappears(self):
        p=self.ready();gate={**self.s(),'id':'approval','kind':'human','input_anchor':'git:'+'c'*40,'stages':['submit'],'repo':'','checks':[],'app_id':0,'pr':0,'not_before':0,'ttl':3600,'reason':'Explicit SE approval remains required before acceptance'};self.assertEqual(self.op('condition_gate',gate)[0],201)
        self.assertEqual(self.delivery('new/one',p)[0],201);self.assertEqual(self.accept('new/one')[0],409)
    def test_light_local_automation_is_worker_statement_without_extra_plan_or_executor(self):
        self.open();p=self.worker();self.gov('knowledge',{'background':'One bounded project','goals':'Small edits','non_goals':'External impact','constraints':'Fixed task paths','materials':[],'entries':[],'history_notes':'No prior materials','resource_notes':'Independent fixture resources'});self.atomic();self.op('policy',{'profile':'light','reason':'Ordinary bounded project'});self.op('assess',{'task':'new/one','scope':self.s()['scope'],'level':'light','flags':[],'reason':'SE reviewed reversible module-local change'})
        claimed=self.event('new/one','claim',{'summary':'Ready ordinary task'},p);self.assertEqual(claimed[0],201,claimed[1])
        v={'method':'automated','status':'passed','summary':'Synthetic local log fixture','reason':'Local evidence reviewed by SE, not a platform attestation'};self.assertEqual(self.delivery('new/one',p,verification=v)[0],201)
        data=self.call('/api/projects/alpha/workflow/task?task=new/one',profile=p)[1];self.assertEqual(data['delivery_readiness']['verification_origin'],'worker_statement');self.assertEqual(self.accept('new/one')[0],201)
        ops=self.call('/api/projects/alpha/operations',profile=p)[1];self.assertFalse(ops['test_plans']);self.assertFalse(ops.get('cv_attempt_policies',{}));self.assertFalse(ops.get('co_plans',{}));self.assertFalse(ops['implementation_plans'] if 'implementation_plans' in ops else {})
    def test_light_known_failed_verification_can_queue_but_cannot_pass(self):
        self.gov('knowledge',{'background':'Project','goals':'Goal','non_goals':'Other','constraints':'Bounded','materials':[],'entries':[],'history_notes':'No prior materials','resource_notes':'Independent fixture resources'});p=self.ready();self.op('policy',{'profile':'light','reason':'Bounded'});self.op('assess',{'task':'new/one','scope':self.s()['scope'],'level':'light','flags':[],'reason':'Bounded local edit'})
        self.assertEqual(self.delivery('new/one',p,verification={'method':'automated','status':'failed','summary':'Actual fixture declared failed','reason':'Report failed work for review'})[0],201);self.assertEqual(self.accept('new/one')[0],409)
    def test_knowledge_dependency_unlocks_reviewed_version_and_graph(self):
        p=self.ready('up/research',category='research');self.atomic('down/work',paths=['src/down/']);down=self.hub.store('alpha').get('down/work')['spec'];down['depends_on']=['up/research'];self.event('down/work','scope',{'spec':down,'reason':'Consume reviewed knowledge'},self.admin)
        self.assertEqual(self.event('down/work','claim',{'summary':'Not ready'},p)[0],409);self.delivery('up/research',p);self.assertEqual(self.accept('up/research')[0],201);self.assertEqual(self.event('down/work','claim',{'summary':'Consume current reviewed result'},p)[0],201)
        history=self.call('/api/projects/alpha/history?task=down/work',profile=p)[1]['events'];lock=next(e['payload']['dependency_locks'] for e in reversed(history) if e['kind']=='claim');self.assertEqual(lock['up/research']['kind'],'knowledge');self.assertEqual(lock['up/research']['input_anchor'],'git:'+'c'*40)
        graph=self.call('/api/projects/alpha/governance',profile=p)[1];edge=next(e for e in graph['graph'] if e['from']=='up/research' and e['to']=='down/work');self.assertEqual(edge['required_stage'],'accepted');self.assertTrue(edge['ready'])
    def code_pair(self,merge_commit=None):
        self.repository();p=self.ready('up/code',baseline=self.first);self.atomic('down/code',paths=['src/down/'],baseline=self.before_merge);down=self.hub.store('alpha').get('down/code')['spec'];down['depends_on']=['up/code'];self.assertEqual(self.event('down/code','scope',{'spec':down,'reason':'Code dependency'},self.admin)[0],201);self.delivery('up/code',p,self.feature);self.assertEqual(self.accept('up/code')[0],201)
        if merge_commit is not False:
            t=self.hub.store('alpha').get('up/code');r=self.event('up/code','merge',{'submission':t['latest_submission']['id'],'summary':'SE records merge','commit':merge_commit or self.merge,'evidence':gov_fixture.EV},self.admin);self.assertEqual(r[0],201,r[1])
        return p
    def test_code_dependency_requires_merge_and_consuming_baseline(self):
        p=self.code_pair(False);self.assertEqual(self.event('down/code','claim',{'summary':'Accepted is not merged'},p)[0],409);t=self.hub.store('alpha').get('up/code');self.event('up/code','merge',{'submission':t['latest_submission']['id'],'summary':'Merge current implementation','commit':self.merge,'evidence':gov_fixture.EV},self.admin)
        r=self.event('down/code','claim',{'summary':'Old baseline cannot consume merge'},p);self.assertEqual(r[0],409);self.assertIn('基线',r[1]['error'])
        down=self.hub.store('alpha').get('down/code')['spec'];down['work']['baseline']=self.head;self.event('down/code','scope',{'spec':down,'reason':'SE pins baseline containing actual merge'},self.admin);self.assertEqual(self.event('down/code','claim',{'summary':'Known merged input'},p)[0],201);self.assertTrue(self.hub.store('alpha').verify()['passed'])
    def test_recorded_merge_that_does_not_contain_implementation_stays_blocked(self):
        self.repository();p=self.ready('up/code',baseline=self.first);self.atomic('down/code',paths=['down/'],baseline=self.head);s=self.hub.store('alpha').get('down/code')['spec'];s['depends_on']=['up/code'];self.event('down/code','scope',{'spec':s,'reason':'Actual code requirement'},self.admin);self.delivery('up/code',p,self.feature);self.accept('up/code');t=self.hub.store('alpha').get('up/code');self.event('up/code','merge',{'submission':t['latest_submission']['id'],'summary':'Fixture intentionally wrong merge record','commit':self.before_merge,'evidence':gov_fixture.EV},self.admin);self.assertEqual(self.event('down/code','claim',{'summary':'Cannot consume false record'},p)[0],409)
    def test_explicit_code_dependency_cannot_be_downgraded_and_unknown_is_not_guessed(self):
        self.open();self.atomic('up/code');self.atomic('down/code',paths=['down/']);s=self.hub.store('alpha').get('down/code')['spec'];s.update(depends_on=['up/code'],dependency_requirements={'up/code':{'kind':'knowledge','stage':'accepted'}});self.assertEqual(self.event('down/code','scope',{'spec':s,'reason':'No downgrade'},self.admin)[0],400)
        s['dependency_requirements']={'up/code':{'kind':'code','stage':'accepted'}};self.assertEqual(self.event('down/code','scope',{'spec':s,'reason':'No stage downgrade'},self.admin)[0],400)
    def test_peer_cannot_submit_another_workers_work_or_change_wait(self):
        p=self.ready();other=self.worker();self.open_thread(p);self.assertEqual(self.delivery('new/one',other)[0],403);self.assertEqual(self.call('/api/projects/beta/operations',{'request_id':'x','expected_revision':0,'action':'thread_wait','payload':{'thread':'question','pause':False,'summary':'Cross project'}},p)[0],404)
    def test_candidate_does_not_block_independent_worker_task(self):
        p=self.ready(resources=[]);self.open_thread(p);self.assertEqual(self.delivery('new/one',p)[0],201)
        self.atomic('next/independent',paths=['other/'],resources=[])
        r=self.event('next/independent','claim',{'summary':'Work independently while first candidate awaits SE'},p);self.assertEqual(r[0],201,r[1])
        self.assertEqual(self.hub.store('alpha').get('new/one')['status'],'submitted')
    def test_discussion_author_cannot_dismiss_formal_stop_and_wait_scope_is_exact(self):
        p=self.ready();self.open_thread(p,'discussion');self.op('thread_decide',{'thread':'question','decision':'stop','summary':'SE stops current scope','reference':''})
        self.assertEqual(self.op('thread_resolve',{'thread':'question','summary':'Cannot dismiss SE stop'},p)[0],403)
        self.assertEqual(self.op('thread_wait',{'thread':'question','pause':'false','summary':'Wrong type'},p)[0],400)
        s=self.hub.store('alpha').get('new/one')['spec'];s['description']='New approved scope';self.event('new/one','scope',{'spec':s,'reason':'SE re-plans'},self.admin)
        self.assertEqual(self.op('thread_wait',{'thread':'question','pause':False,'summary':'Old thread not current'},p)[0],409)
    def test_changed_dependency_after_claim_requires_scope_but_comment_does_not(self):
        p=self.ready('up/knowledge',category='documentation');self.delivery('up/knowledge',p);self.accept('up/knowledge')
        self.atomic('down/use',paths=['down/']);s=self.hub.store('alpha').get('down/use')['spec'];s['depends_on']=['up/knowledge'];self.event('down/use','scope',{'spec':s,'reason':'Consume reviewed source'},self.admin);self.assertEqual(self.event('down/use','claim',{'summary':'Pin exact source'},p)[0],201)
        self.open_thread(p,'discussion',tid='up/knowledge');self.assertEqual(self.delivery('down/use',p)[0],201)
        self.assertTrue(self.call('/api/projects/alpha/workflow/task?task=down/use',profile=p)[1]['delivery_readiness']['ready_for_acceptance'])
        old=self.hub.store('alpha').get('up/knowledge')['latest_submission']['id'];self.assertEqual(self.event('up/knowledge','reopen',{'submission':old,'reason':'Changed knowledge needs re-review','findings':[{'description':'Update source','acceptance':'Review new result'}]},self.admin)[0],201)
        findings=[f['id'] for f in self.hub.store('alpha').get('up/knowledge')['findings'] if f['open']];self.delivery('up/knowledge',p,commit='d'*40,addresses=findings);self.assertEqual(self.accept('up/knowledge')[0],201);self.assertEqual(self.accept('down/use')[0],409)
        edge=next(e for e in self.call('/api/projects/alpha/governance',profile=p)[1]['graph'] if e['to']=='down/use' and e['type']=='hard');self.assertFalse(edge['ready']);self.assertIn('锚点',''.join(edge['blockers']))
    def test_native_override_requires_runtime_accepted_source(self):
        p=self.code_pair();s=self.hub.store('alpha').get('down/code')['spec'];s['work']['baseline']=self.head;s['dependency_requirements']={'up/code':{'stage':'native_accepted','repo':'main'}};self.event('down/code','scope',{'spec':s,'reason':'Requires actual runtime accepted source'},self.admin)
        self.assertEqual(self.event('down/code','claim',{'summary':'Not native yet'},p)[0],409)
        t=self.hub.store('alpha').get('up/code');r=self.event('up/code','native',{'submission':t['latest_submission']['id'],'summary':'SE records actual fixture runtime check','commit':self.merge,'evidence':gov_fixture.EV},self.admin);self.assertEqual(r[0],201,r[1]);self.assertEqual(self.event('down/code','claim',{'summary':'Native fixed source'},p)[0],201)
    def test_stopped_attempt_candidate_queues_before_se_selection(self):
        from . import test_convergence as cv
        for name in ('member','scope','claimed','ok','cv'):
            setattr(self,name,getattr(cv.ConvergenceCase,name).__get__(self))
        lease=cv.ConvergenceCase.attempts(self)
        self.ok('attempt_finish',{'attempt':'try1','lease':lease,'status':'candidate','input_anchor':'git:'+'c'*40,'runs':[],'evidence':gov_fixture.EV,'stopped':True,'summary':'Stopped result ready before SE choice'},self.a)
        self.assertEqual(self.delivery('new/one',self.a,attempt_id='try1')[0],201);self.assertEqual(self.accept('new/one')[0],409)
        self.ok('attempt_select',{**self.scope(),'attempt':'try1','reason':'SE selects already queued exact candidate','evidence':gov_fixture.EV});self.assertEqual(self.accept('new/one')[0],201)
    def test_explicit_failed_platform_run_can_queue_but_never_pass(self):
        from . import test_operations as ops
        for name in ('charter','member','atomic','assess','scope','case','set_plan','manual','case_payload','ops','op'):
            setattr(self,name,getattr(ops.OperationsCase,name).__get__(self))
        ops.OperationsCase.adopt(self);self.case();self.set_plan();run=self.manual(results=[{'case':'check@1','status':'failed','exit_code':None,'seconds':1,'summary':'Actual fixture failure'}]);self.assertEqual(run[0],201,run[1]);self.event('new/one','claim',{'summary':'Report failed candidate'},self.a)
        result=ops.OperationsCase.submit(self,test_runs=[run[1]['run']]);self.assertEqual(result[0],201,result[1]);self.assertEqual(self.accept('new/one')[0],409)
    def test_dependency_and_wait_public_shapes_fail_without_server_errors(self):
        p=self.ready();self.open_thread(p)
        for thread in ({},[],None,7):self.assertEqual(self.op('thread_wait',{'thread':thread,'pause':False,'summary':'Invalid thread type'},p)[0],400)
        for depends,requirements in [([{}],{}),(['new/one'],[]),(['new/one'],{'missing':{'kind':'code'}}),(['new/one'],{'new/one':{'stage':[]}})]:
            s=deepcopy(self.hub.store('alpha').get('new/one')['spec']);s.update(depends_on=depends,dependency_requirements=requirements);self.assertEqual(self.event('new/one','scope',{'spec':s,'reason':'Invalid dependency schema'},self.admin)[0],400)
    def test_multiple_repositories_require_explicit_consumption_repository(self):
        p=self.code_pair();self.assertEqual(self.action('bind',{'id':'second','repository':'fixture/second','title':'Second approved repository','reason':'Ambiguous project mirror choice'})[0],201)
        s=self.hub.store('alpha').get('down/code')['spec'];s['work']['baseline']=self.head;self.event('down/code','scope',{'spec':s,'reason':'Fixed baseline but no repository chosen'},self.admin)
        r=self.event('down/code','claim',{'summary':'Do not guess repo'},p);self.assertEqual(r[0],409);self.assertIn('仓库',r[1]['error'])
        s['dependency_requirements']={'up/code':{'repo':'main'}};self.event('down/code','scope',{'spec':s,'reason':'SE pins correct repository'},self.admin);self.assertEqual(self.event('down/code','claim',{'summary':'Known repo'},p)[0],201)
    def test_dependency_reopen_after_consumer_acceptance_blocks_baseline_merge(self):
        p=self.ready('up/doc',category='documentation');self.delivery('up/doc',p);self.accept('up/doc');self.atomic('down/code',paths=['down/']);s=self.hub.store('alpha').get('down/code')['spec'];s['depends_on']=['up/doc'];self.event('down/code','scope',{'spec':s,'reason':'Fixed knowledge prerequisite'},self.admin);self.event('down/code','claim',{'summary':'Consume accepted knowledge'},p);self.delivery('down/code',p);self.assertEqual(self.accept('down/code')[0],201)
        t=self.hub.store('alpha').get('up/doc');self.assertEqual(self.event('up/doc','reopen',{'submission':t['latest_submission']['id'],'reason':'Accepted knowledge found defective','findings':[{'description':'Wrong input assumption','acceptance':'Reassess source'}]},self.admin)[0],201)
        t=self.hub.store('alpha').get('down/code');r=self.event('down/code','merge',{'submission':t['latest_submission']['id'],'summary':'Do not baseline stale consumer','commit':'c'*40,'evidence':gov_fixture.EV},self.admin);self.assertEqual(r[0],409);self.assertIn('依赖',r[1]['error'])
