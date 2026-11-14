"""Second-batch behavior across actual project HTTP, Git and local probes."""
from copy import deepcopy
import hashlib,json,time,uuid,unittest
from unittest.mock import patch
from pathlib import Path
from . import test_workflow as workflow
EV=workflow.EV
from . import test_resources as resources
from . import test_planning as planning
from task_board.store import digest
from task_board.coordination import cursor_decode

class CoordinationCase(unittest.TestCase):
    setUp=workflow.WorkflowCase.setUp;tearDown=workflow.WorkflowCase.tearDown
    call=workflow.WorkflowCase.call;gov=workflow.WorkflowCase.gov;member=workflow.WorkflowCase.member;atomic=workflow.WorkflowCase.atomic;event=workflow.WorkflowCase.event
    git=workflow.WorkflowCase.git;action=workflow.WorkflowCase.action;query=workflow.WorkflowCase.query;repository=workflow.WorkflowCase.repository
    op=workflow.WorkflowCase.op;scope=workflow.WorkflowCase.scope;claimed=workflow.WorkflowCase.claimed;submit=workflow.WorkflowCase.submit
    module=planning.PlanningCase.module;resource_payload=resources.ResourcesCase.payload

    def co(self,profile=None,task=''):
        return self.call('/api/projects/alpha/coordination'+('?task='+task if task else ''),profile=profile or self.admin)
    def intake(self,id='discovery',**kw):return {'id':id,'kind':'bug','title':'Observed out-of-scope defect','body':'Keep current work bounded; SE must triage the new finding','sources':[{'kind':'task','id':'new/one'}],**kw}
    def checkpoint(self,**kw):return {**self.scope(),'id':'resume-1','input_anchor':'git:'+'c'*40,'completed':'Parser implemented','remaining':'Boundary verification','tests':'Behavior passed; negative case pending','obstacles':'Waiting for interface decision','resources':[],'next_step':'Read SE decision before boundary test','recheck':'Scope and fixed interface version','session':'fixture-session',**kw}
    def plan(self,**kw):return {**self.scope(),'id':'steps-1','steps':['Implement bounded parser','Verify positive and negative behavior'],'paths':['src/one/parser.py'],'validation':'Actual boundary tests','risks':'Input may differ','stop_conditions':'Stop on public interface drift',**kw}
    def gate(self,**kw):return {**self.scope(),'id':'external','kind':'human','input_anchor':'git:'+'c'*40,'stages':['submit'],'repo':'','checks':[],'app_id':10 if kw.get('kind')=='github_checks' else 0,'pr':0,'not_before':0,'ttl':3600,'reason':'Fixed-input release prerequisite',**kw}
    def observer(self,targets,kinds):
        profile=self.hub.invite('alpha','observer-one');self.member('observer-one','runner')
        result=self.op('observer_authorize',{'actor':'observer-one','targets':targets,'kinds':kinds,'enabled':True,'reason':'Project-specific local approved observation'});self.assertEqual(result[0],201,result[1]);return profile

    def test_discovery_triage_conversion_atomic_and_causal_links_do_not_block(self):
        self.claimed();r=self.op('intake_open',self.intake(),self.a);self.assertEqual(r[0],201,r[1])
        decide={'id':'discovery','expected_version':1,'status':'approved','reason':'Separate defect from original scope','duplicate':'','tasks':[],'modules':[]}
        self.assertEqual(self.op('intake_decide',decide,self.a)[0],403)
        self.assertEqual(self.op('intake_decide',decide)[0],201)
        self.assertEqual(self.op('intake_decide',decide)[0],409)
        spec=deepcopy(self.hub.store('alpha').get('new/one')['spec']);spec.update(id='new/discovered',allowed_paths=['src/new/'])
        result=self.op('intake_convert',{'id':'discovery','expected_version':2,'spec':spec,'reason':'SE-approved separate bounded repair'});self.assertEqual(result[0],201,result[1])
        self.assertEqual(self.hub.store('alpha').get('new/discovered')['status'],'planned')
        self.assertEqual(self.hub.store('alpha').get('new/one')['spec']['depends_on'],[])
        self.assertEqual(self.submit()[0],201)
        data=self.co()[1];self.assertEqual(data['intakes']['discovery']['tasks'],['new/discovered']);self.assertTrue(any(e['relation']=='derived_from' for e in data['links'].values()))
        for suffix in ('verify','operations/verify'):self.assertTrue(self.call('/api/projects/alpha/'+suffix,profile=self.admin)[1]['passed'])

    def test_duplicate_cycles_source_boundaries_and_permission_denial(self):
        self.claimed();self.op('intake_open',self.intake());self.op('intake_open',self.intake('other'))
        p={'id':'discovery','expected_version':1,'status':'duplicate','reason':'Duplicate issue','duplicate':'other','tasks':[],'modules':[]};self.assertEqual(self.op('intake_decide',p)[0],201)
        p.update(id='other',duplicate='discovery');self.assertEqual(self.op('intake_decide',p)[0],409)
        link={'id':'derived','from':{'kind':'intake','id':'other'},'to':{'kind':'task','id':'new/one'},'relation':'derived_from','reason':'Actual observed source'};self.assertEqual(self.op('source_link',link)[0],201)
        self.assertEqual(self.op('source_link',{**link,'id':'cycle','from':link['to'],'to':link['from']})[0],409)
        self.assertEqual(self.op('intake_open',self.intake('foreign',sources=[{'kind':'task','id':'foreign/task'}]),self.a)[0],404)
        for path in ('coordination','coordination/feed','coordination?task=new/one'):self.assertEqual(self.call('/api/projects/alpha/'+path,profile=self.b)[0],404)
        self.member(role='viewer');self.assertEqual(self.op('intake_open',self.intake('viewer'),self.a)[0],403)

    def test_feed_bounded_resume_stable_ids_and_private_resource_metadata(self):
        self.claimed();p=self.resource_payload('manager-only',visibility='managers');p['locations'][0]['location']='/volume1/private-manager-origin';self.assertEqual(self.gov('resource_register',p)[0],201)
        self.assertEqual(self.op('checkpoint',self.checkpoint(),self.a)[0],201)
        t=self.hub.store('alpha').get('new/one');self.event('new/one','progress',{'summary':'Continue after durable checkpoint'})
        data=self.co(self.a,'new/one')[1];self.assertEqual(data['resume']['checkpoint']['task_revision'],t['revision']);self.assertTrue(data['resume']['checkpoint_current'])
        items=[];cursor=''
        for _ in range(30):
            from urllib.parse import urlencode
            status,batch,_=self.call('/api/projects/alpha/coordination/feed?'+urlencode({'cursor':cursor,'limit':2}),profile=self.a);self.assertEqual(status,200,batch);self.assertLessEqual(len(batch['items']),2);self.assertLessEqual(batch['scanned'],200)
            items+=batch['items'];cursor=batch['cursor']
            if not batch['has_more']:break
        self.assertEqual(len({e['id'] for e in items}),len(items));self.assertNotIn('manager-only',json.dumps(items));self.assertNotIn('private-manager-origin',json.dumps(items));self.assertTrue(any(e['action']=='progress' for e in items))
        p={'consumer':'worker','cursor':cursor,'state':'processed'};self.assertEqual(self.op('consumer_ack',p,self.a)[0],409)
        for state in ('delivered','read','processed'):self.assertEqual(self.op('consumer_ack',{**p,'state':state},self.a)[0],201)
        self.assertEqual(self.co(self.a)[1]['consumers']['same-agent']['worker']['processed'],cursor)
        self.assertNotIn('same-agent',self.co()[1]['consumers'])
        spec=deepcopy(t['spec']);spec['description']='Changed scope';self.event('new/one','scope',{'spec':spec,'reason':'Real scope migration'},self.admin)
        self.assertFalse(self.co(self.a,'new/one')[1]['resume']['checkpoint_current'])
        self.assertEqual(self.op('checkpoint',self.checkpoint(id='old',scope=t['scope_hash'],scope_version=t['scope_version']),self.a)[0],409)

    def test_actual_local_consumer_and_lost_ack_exact_replay(self):
        self.claimed();from tools.coordination_client import consume
        from tools.task_board_client import Client,ClientError
        c=Client(self.url,{**self.a,'url':self.url});out=self.state/'consumer';original=c.call;lost=[False]
        def flaky(endpoint,payload=None):
            result=original(endpoint,payload)
            if payload and payload.get('action')=='consumer_ack' and not lost[0]:lost[0]=True;raise ClientError('Lost response')
            return result
        with patch.object(c,'call',flaky):
            with self.assertRaises(ClientError):consume(c,'local',out)
        pending=json.loads((out/'ACK.json').read_text('utf8'));self.assertTrue(original('/api/operations',pending)['replayed'])
        batch=consume(c,'local',out,True);self.assertFalse((out/'ACK.json').exists());self.assertEqual(json.loads((out/'CURSOR.json').read_text('utf8'))['cursor'],batch['cursor'])
        self.assertEqual(self.hub.store('alpha').get('new/one')['owner'],'same-agent')

    def test_task_plan_risk_gates_and_current_contract_context(self):
        self.claimed();self.assertEqual(self.op('execution_policy',{**self.scope(),'required':True,'reason':'SE selects plan review before further execution'})[0],201)
        self.assertEqual(self.submit()[0],409)
        self.assertEqual(self.op('execution_plan',self.plan(paths=['outside.py']),self.a)[0],409)
        self.assertEqual(self.op('execution_plan',self.plan(),self.a)[0],201)
        review={**self.scope(),'plan':'steps-1','result':'approve','reason':'Steps, write scope and verification reviewed'}
        self.assertEqual(self.op('execution_review',review,self.a)[0],403);self.assertEqual(self.op('execution_review',review)[0],201)
        self.assertEqual(self.submit()[0],201)
        t=self.hub.store('alpha').get('new/one');spec=deepcopy(t['spec']);spec['description']='Changed execution scope';self.event('new/one','scope',{'spec':spec,'reason':'Approved new scope'},self.admin)
        self.assertFalse(self.co(task='new/one')[1]['plans']['steps-1']['context_current']);self.assertEqual(self.event('new/one','claim',{'summary':'Cannot use stale plan'})[0],409)

    def test_light_task_does_not_add_plan_approval_and_wip_blocks_new_claims(self):
        self.member();self.gov('module_plan',self.module());binding={'module':'core@1','purpose':'execution','question':'','no_interface_reason':'No public interface'}
        self.atomic(planning=binding);self.atomic('new/two',['src/two/'],planning=binding)
        self.assertEqual(self.op('wip_policy',{'module':'core','limit':1,'mode':'enforce','reason':'One constrained implementation slot'})[0],201)
        # Existing module plan approval is required independently of WIP.
        from . import test_planning as planning
        planning.PlanningCase.charter(self);scope=self.call('/api/projects/alpha/governance',profile=self.admin)[1]['module_readiness']['core@1']['scope'];self.gov('module_review',{'ref':'core@1','scope':scope,'result':'approve','summary':'Actual independent module scope','evidence':EV})
        self.assertEqual(self.event('new/one','claim',{'summary':'Own slot'})[0],201)
        self.assertEqual(self.event('new/two','claim',{'summary':'No second slot'})[0],409)
        self.assertEqual(self.co()[1]['analytics']['wip'][0]['active'],1)

    def test_review_batch_actual_git_anchors_replay_and_incremental_lineage(self):
        self.repository();self.claimed(self.first)
        p={**self.scope(),'id':'batch1','repo':'main','base':self.first,'target':self.feature,'previous':'','summary':'Boundary behavior must be demonstrated','comments':[{'path':'feature.py','line':1,'side':'right','body':'Explain missing negative case','blocking':True,'criterion':''}]}
        rid=uuid.uuid4().hex;rev=self.call('/api/projects/alpha/operations',profile=self.admin)[1]['revision'];result=self.op('review_batch',p,rid=rid,revision=rev);self.assertEqual(result[0],201,result[1]);self.assertTrue(self.op('review_batch',p,rid=rid,revision=rev)[1]['replayed'])
        self.assertIn('batch1-1',self.call('/api/projects/alpha/workflow/task?task=new/one',profile=self.admin)[1]['findings'])
        wrong={**p,'id':'bad','comments':[{**p['comments'][0],'line':999}]};self.assertEqual(self.op('review_batch',wrong)[0],409)
        second={**p,'id':'batch2','previous':'batch1','base':self.first,'target':self.head,'comments':[]};self.assertEqual(self.op('review_batch',second)[0],409)
        second['base']=self.feature;self.assertEqual(self.op('review_batch',second)[0],201)
        self.assertEqual(self.submit(self.head)[0],201);self.assertFalse(self.co(task='new/one')[1]['batches']['batch1']['anchor_current'])
        self.assertEqual(self.op('root_cause',{**self.scope(),'finding':'batch1-1','category':'test_gap','reason':'A reproducible negative case was absent'})[0],201)
        self.assertEqual(self.op('improvement',{'id':'negative-case','finding':'batch1-1','targets':[{'kind':'task','id':'new/one'}],'hypothesis':'Add boundary coverage to reduce recurrence','result':'Not yet verified','runs':[],'evidence':[]})[0],201)
        analytics=self.co()[1]['analytics'];self.assertEqual(analytics['root_causes']['test_gap'],1);self.assertGreater(analytics['intervals']['claim_to_submit']['samples'],0)

    def test_human_and_timer_gates_bind_exact_input_and_never_accept_automatically(self):
        self.claimed();self.assertEqual(self.op('condition_gate',self.gate())[0],201);self.assertEqual(self.submit()[0],409)
        gate=self.co()[1]['gates']['external'];p={'id':'external','gate_hash':gate['gate_hash'],'reason':'Authorized reviewer checked fixed input'}
        self.assertEqual(self.op('gate_confirm',p,self.a)[0],403);self.assertEqual(self.op('gate_confirm',p)[0],201)
        self.assertEqual(self.submit('d'*40)[0],409);self.assertEqual(self.submit()[0],201)
        self.assertEqual(self.hub.store('alpha').get('new/one')['status'],'submitted')
        self.assertEqual(self.op('condition_gate',self.gate(id='timer',kind='timer',not_before=time.time()+3600))[0],201)
        self.assertFalse(self.co()[1]['gates']['timer']['satisfied'])

    def test_github_observation_newest_run_exact_sha_freshness_and_revocation(self):
        self.repository();self.claimed(self.first);self.assertEqual(self.op('condition_gate',self.gate(kind='github_checks',repo='main',checks=['CI'],input_anchor='git:'+self.head))[0],201);profile=self.observer(['external'],['condition'])
        gate=self.co()[1]['gates']['external'];from tools.project_observer import probe_github
        config={'gate_hash':gate['gate_hash'],'repository':'fixture/private','app_id':10}
        runs=[{'id':1,'name':'CI','head_sha':self.head,'app':{'id':10},'status':'completed','conclusion':'success'},{'id':2,'name':'CI','head_sha':self.head,'app':{'id':10},'status':'in_progress','conclusion':None}]
        status,checks,_=probe_github(gate,config,lambda *args:{'check_runs':runs});self.assertEqual(status,'pending')
        runs[1].update(status='completed',conclusion='success');status,checks,_=probe_github(gate,config,lambda *args:{'check_runs':runs});self.assertEqual(status,'passed')
        p={'id':'external','gate_hash':gate['gate_hash'],'status':status,'commit':self.head,'checks':checks,'pr':0,'summary':'Exact repository observed using bounded protocol','evidence':EV}
        self.assertEqual(self.op('condition_observe',{**p,'commit':self.first},profile)[0],409)
        self.assertEqual(self.op('condition_observe',p,profile)[0],201);self.assertTrue(self.co()[1]['gates']['external']['satisfied'])
        with patch('task_board.coordination.time.time',return_value=time.time()+4000):self.assertFalse(self.co()[1]['gates']['external']['satisfied'])
        self.assertEqual(self.op('condition_observe',{**p,'status':'pending','checks':{'CI':'pending'}},profile)[0],201);self.assertFalse(self.co()[1]['gates']['external']['satisfied'])
        self.op('observer_authorize',{'actor':'observer-one','targets':['external'],'kinds':['condition'],'enabled':False,'reason':'Operator revoked observation authority'})
        self.assertEqual(self.op('condition_observe',p,profile)[0],403)

    def test_actual_file_probe_manifest_failure_version_and_resource_privacy(self):
        self.claimed();path=self.state/'actual.txt';path.write_text('Actual local original bytes');sha=hashlib.sha256(path.read_bytes()).hexdigest()
        p=self.resource_payload('original',mutable=False,version='1',integrity={'kind':'file','sha256':sha,'subject':'actual.txt'});p['locations'][0].update(kind='local',location=str(path),machine='fixture');self.assertEqual(self.gov('resource_register',p)[0],201);profile=self.observer(['original'],['resource'])
        from tools.project_observer import observe,probe_resource
        from tools.task_board_client import Client
        entry=self.call('/api/projects/alpha/resources/original',profile=self.a)[1]['entry'];config={'project_id':'alpha','resources':{'original':{'entry_hash':digest(entry),'mode':'file','path':str(path),'ttl':3600}}}
        c=Client(self.url,{**profile,'url':self.url});self.assertIn('revision',observe(c,config,'original',self.state/'observations'))
        self.assertTrue(self.co(self.a)[1]['resource_checks']['original'][-1]['current']);path.write_text('Changed original bytes');self.assertEqual(probe_resource(entry,config['resources']['original'])[0],'mismatch')
        manifest=self.state/'MANIFEST.json';manifest.write_text(json.dumps({'files':{'actual.txt':sha}}));entry2=deepcopy(entry);entry2['integrity']={'kind':'manifest','sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),'subject':'MANIFEST.json'}
        self.assertEqual(probe_resource(entry2,{'entry_hash':digest(entry2),'path':str(manifest),'mode':'manifest'})[0],'mismatch')
        private=self.resource_payload('hidden',visibility='managers');self.gov('resource_register',private)
        self.assertEqual(self.op('intake_open',self.intake('no-leak',sources=[{'kind':'resource','id':'hidden'}]))[0],403)
        self.assertNotIn('hidden',json.dumps(self.co(self.a)[1]));self.assertNotIn('observer-one',self.co(self.a)[1]['observers'])
        p.update(expected_version=1,title='Version changed');self.gov('resource_update',p);self.assertFalse(self.co(self.a)[1]['resource_checks']['original'][-1]['current'])

    def test_input_validation_rejects_malformed_public_boundaries(self):
        self.claimed()
        for p in [self.intake(sources={}),self.intake(id='../bad'),self.intake(kind='unknown')]:self.assertEqual(self.op('intake_open',p)[0],400)
        self.assertEqual(self.call('/api/projects/alpha/coordination/feed?cursor=invalid',profile=self.a)[0],400)
        self.assertEqual(self.op('checkpoint',self.checkpoint(resources=['unregistered']),self.a)[0],409)
        self.assertEqual(self.op('condition_gate',self.gate(ttl=999999))[0],400)
        self.assertEqual(self.op('execution_plan',self.plan(paths=['../secret']),self.a)[0],400)

    def test_explicit_light_plan_adoption_does_not_add_approval(self):
        self.claimed();self.op('assess',{'task':'new/one','scope':self.scope()['scope'],'level':'light','flags':[],'reason':'Reversible internal change'})
        self.op('execution_policy',{**self.scope(),'required':True,'reason':'Record planning preference without defeating light policy'})
        self.assertFalse(self.co(task='new/one')[1]['resume']['plan_required']);self.assertEqual(self.submit()[0],201)

    def test_gate_replacement_is_explicit_and_keeps_old_record(self):
        self.claimed();self.op('condition_gate',self.gate());gate=self.co()[1]['gates']['external'];self.assertEqual(self.submit()[0],409)
        p={'id':'external','gate_hash':gate['gate_hash'],'reason':'SE replaces obsolete prerequisite after checking impact'}
        self.assertEqual(self.op('gate_retire',p,self.a)[0],403);self.assertEqual(self.op('gate_retire',p)[0],201)
        self.assertTrue(self.co()[1]['gates']['external']['retired']);self.assertFalse(self.co()[1]['gates']['external']['satisfied']);self.assertEqual(self.submit()[0],201)

    def test_resource_reclassification_hides_discovery_and_observation_history(self):
        self.claimed();p=self.resource_payload('reclassify');self.gov('resource_register',p);self.op('intake_open',self.intake(sources=[{'kind':'resource','id':'reclassify'}]))
        self.assertIn('discovery',self.co(self.a)[1]['intakes']);p.update(expected_version=1,visibility='managers');self.gov('resource_update',p)
        self.assertNotIn('discovery',self.co(self.a)[1]['intakes']);self.assertIn('discovery',self.co()[1]['intakes'])
        feed=self.call('/api/projects/alpha/coordination/feed?limit=100',profile=self.a)[1];self.assertNotIn('discovery',json.dumps(feed['items']))

    def test_downloaded_observer_kit_is_standalone_and_github_sources_fail_closed(self):
        import zipfile,io,sys
        from task_board.help import observer_kit
        from tools.owned_process import run
        out=self.state/'standalone-observer';out.mkdir()
        with zipfile.ZipFile(io.BytesIO(observer_kit())) as z:
            self.assertFalse(any('_private' in name for name in z.namelist()));z.extractall(out)
        code,stdout,stderr=run([sys.executable,'-B',str(out/'tools/project_observer.py'),'--help'],cwd=out,evidence=self.state/'kit-evidence',purpose='Downloaded standalone read-only observation kit',timeout=15)
        self.assertEqual(code,0,stderr.decode());self.assertIn(b'--target',stdout)
        self.repository();self.claimed(self.first);self.op('condition_gate',self.gate(kind='github_checks',repo='main',checks=['CI'],input_anchor='git:'+self.head));gate=self.co()[1]['gates']['external']
        from tools.project_observer import probe_github
        fake={'id':50,'name':'CI','head_sha':self.head,'app':{'id':999},'status':'completed','conclusion':'success'}
        status,_,_=probe_github(gate,{'gate_hash':gate['gate_hash'],'repository':'fixture/private'},lambda *a:{'check_runs':[fake]});self.assertEqual(status,'pending')
        with self.assertRaises(ValueError):probe_github(gate,{'gate_hash':gate['gate_hash'],'repository':'fixture/private','app_id':999},lambda *a:{'check_runs':[fake]})

    def test_coverage_links_actual_cases_runs_and_anchored_findings(self):
        self.claimed();self.op('criteria_plan',workflow.WorkflowCase.plan(self))
        case={'id':'boundary','version':'1','title':'Actual boundary observation','kind':'manual','priority':'normal','targets':['task:new/one'],'preconditions':'Known exact fixture','inputs':'Actual fixed input','steps':'Exercise positive and negative behavior','expected':'Reject invalid and preserve valid','environment':'fixture','resources':[]}
        self.assertEqual(self.op('case',case)[0],201);self.op('test_plan',{'task':'new/one','scope':self.scope()['scope'],'cases':['boundary@1'],'reason':'Known acceptance coverage'})
        run=self.op('manual_run',{'tasks':['new/one'],'scopes':{'new/one':self.scope()['scope']},'input_anchor':'git:'+'c'*40,'reason':'Observed actual fixture','results':[{'case':'boundary@1','status':'passed','exit_code':None,'seconds':1,'summary':'Observed behavior'}],'evidence':EV,'artifacts':[]});self.assertEqual(run[0],201,run[1])
        self.op('criteria_claim',{**self.scope(),'plan':'accept-v1','criterion':'AC1','input_anchor':'git:'+'c'*40,'summary':'Observed required boundary','runs':[run[1]['run']],'evidence':EV},self.a)
        finding={**self.scope(),'id':'boundary-finding','criterion':'AC1','description':'Independent potential defect','acceptance':'Verify counterexample','blocking':True,'anchor':{'commit':'c'*40,'path':'src/one/check.py','line':1,'resource':''},'previous':''};self.op('review_open',finding)
        coverage=self.co()[1]['analytics']['coverage'];self.assertEqual(len(coverage),1);self.assertEqual(coverage[0]['cases'],['boundary@1']);self.assertEqual(coverage[0]['runs'],[run[1]['run']]);self.assertEqual(coverage[0]['findings'],['boundary-finding']);self.assertTrue(coverage[0]['current_scope'])
