"""Third-batch real HTTP transactions, authority, Git and continuation."""
from copy import deepcopy
import json,time,unittest
from unittest.mock import patch
from . import test_coordination as fixture
from . import test_planning as planning
from task_board.store import digest
EV=fixture.EV

class ConvergenceCase(unittest.TestCase):
    setUp=fixture.CoordinationCase.setUp;tearDown=fixture.CoordinationCase.tearDown
    call=fixture.CoordinationCase.call;gov=fixture.CoordinationCase.gov;member=fixture.CoordinationCase.member;atomic=fixture.CoordinationCase.atomic;event=fixture.CoordinationCase.event
    git=fixture.CoordinationCase.git;action=fixture.CoordinationCase.action;query=fixture.CoordinationCase.query;repository=fixture.CoordinationCase.repository
    op=fixture.CoordinationCase.op;scope=fixture.CoordinationCase.scope;claimed=fixture.CoordinationCase.claimed;submit=fixture.CoordinationCase.submit
    module=planning.PlanningCase.module;charter=planning.PlanningCase.charter
    def cv(self,profile=None,task=''):
        return self.call('/api/projects/alpha/convergence'+('?task='+task if task else ''),profile=profile or self.admin)
    def ok(self,action,p,profile=None):
        result=self.op(action,p,profile);self.assertEqual(result[0],201,(action,result[1]));return result[1]
    def draft(self,id='batch',items=None):
        return {'id':id,'version':'1','title':'Bounded related changes','items':items or [{'key':'module','kind':'module_plan','payload':self.module(knowledge_refs=[])}],'references':[],'reason':'Complete original planning only','evidence':EV}
    def preview(self,ref='batch@1',modules=None):return self.ok('draft_preview',{'ref':ref,'approve_modules':modules or ['core@1'],'approve_rules':[]})
    def publish(self,ref='batch@1',h=None):return self.op('draft_publish',{'ref':ref,'manifest_hash':h or self.cv()[1]['drafts'][ref]['preview']['manifest_hash'],'reason':'Reviewed complete effects','evidence':EV})
    def prepared(self,code=False):
        self.member();self.charter();self.gov('module_plan',self.module(knowledge_refs=[]))
        g=self.call('/api/projects/alpha/governance',profile=self.admin)[1];self.gov('module_review',{'ref':'core@1','scope':g['module_readiness']['core@1']['scope'],'result':'approve','summary':'Actual module reviewed','evidence':EV})
        self.atomic(baseline=self.first if code else 'a'*40,category='backend' if code else 'documentation',planning={'module':'core@1','purpose':'execution','question':'','no_interface_reason':'Bounded internal task'})
        if code:
            t=self.hub.store('alpha').get('new/one');s=deepcopy(t['spec']);s['allowed_paths']=['feature.py'];self.event('new/one','scope',{'spec':s,'reason':'Match actual isolated Git file'},self.admin)
    def rule(self,**kw):return {'id':'internal','version':'1','title':'Approved internal work','module':'core@1','paths':['src/one/'],'categories':['documentation'],'level':'light','repo':'','contracts':[],'assets':{},'default_items':['Keep original scope'],'cases':[],'plan_mode':'module_covered','expires_at':int(time.time())+86400,'reason':'Module already covers the plan','evidence':EV,**kw}
    def bind(self,rule=None):
        self.ok('rule_register',rule or self.rule());state=self.cv()[1]['rules']['internal@1']['readiness'];self.ok('rule_review',{'ref':'internal@1','context_hash':state['context_hash'],'result':'approve','reason':'SE checked fixed boundaries','evidence':EV})
        return self.ok('rule_bind',{**self.scope(),'ref':'internal@1','reason':'Use approved bounded rule'},self.a)
    def attempts(self):
        self.claimed();self.ok('workspace_register',{'id':'ws','task':'new/one','location':'G:/fixture/isolated','machine':'fixture','branch':'codex/fixture','paths':['src/one/'],'resources':[],'reason':'Independent authorized workspace'})
        self.ok('attempt_policy',{**self.scope(),'actors':['same-agent'],'workspaces':['ws'],'max_parallel':1,'lease_seconds':30,'reason':'Opt in to conservative continuation'})
        return self.ok('attempt_open',{**self.scope(),'id':'try1','workspace':'ws','reason':'First bounded approach'},self.a)['lease']
    def test_draft_preview_no_writes_and_atomic_publish_replay(self):
        self.member();self.charter();before=self.call('/api/projects/alpha/governance',profile=self.admin)[1]['revision'];self.ok('draft_save',self.draft(),self.a)
        self.assertEqual(self.op('draft_preview',{'ref':'batch@1','approve_modules':['core@1'],'approve_rules':[]},self.a)[0],403)
        self.preview();g=self.call('/api/projects/alpha/governance',profile=self.admin)[1];self.assertEqual(g['revision'],before);self.assertNotIn('core@1',g['modules'])
        self.assertEqual(self.publish()[0],201);g=self.call('/api/projects/alpha/governance',profile=self.admin)[1];self.assertTrue(g['module_readiness']['core@1']['ready']);self.assertEqual(self.publish()[0],409)
        for suffix in ('verify','operations/verify','governance/verify'):self.assertTrue(self.call('/api/projects/alpha/'+suffix,profile=self.admin)[1]['passed'])
    def test_draft_invalid_late_item_rolls_back_and_bad_shapes_reject(self):
        self.member();self.charter();items=self.draft()['items']+[{'key':'bad','kind':'case','payload':{'id':'incomplete'}}];self.ok('draft_save',self.draft(items=items))
        self.assertEqual(self.op('draft_preview',{'ref':'batch@1','approve_modules':[],'approve_rules':[]})[0],400);self.assertNotIn('core@1',self.call('/api/projects/alpha/governance',profile=self.admin)[1]['modules'])
        for val in ({},None,[{}]):
            self.assertEqual(self.op('draft_save',self.draft('bad',items=[{'key':'m','kind':'module_plan','payload':self.module(knowledge_refs=val)}]))[0],400)
    def test_preview_precise_invalidation_and_dependency_cycle(self):
        self.member();self.charter();self.ok('draft_save',self.draft());self.preview();g=self.call('/api/projects/alpha/governance',profile=self.admin)[1]['knowledge'];g['history_notes']='Unrelated history update';self.gov('knowledge',g);self.assertEqual(self.publish()[0],201)
        self.ok('draft_save',self.draft('next',items=[{'key':'m','kind':'module_plan','payload':self.module('2',knowledge_refs=[])}]));self.preview('next@1',['core@2']);g['constraints']='Changed production boundary';self.gov('knowledge',g);r=self.publish('next@1');self.assertEqual(r[0],409);self.assertIn('章程',str(r[1]))
        items=[{'key':'a','kind':'module_plan','payload':self.module(id='a',depends_on=['b@1'],knowledge_refs=[])},{'key':'b','kind':'module_plan','payload':self.module(id='b',depends_on=['a@1'],knowledge_refs=[])}]
        self.ok('draft_save',self.draft('cycle',items=items));self.assertEqual(self.op('draft_preview',{'ref':'cycle@1','approve_modules':[],'approve_rules':[]})[0],409)
    def test_rule_reuse_creates_fixed_criteria_without_per_card_assessment(self):
        self.prepared();self.bind();op=self.call('/api/projects/alpha/operations',profile=self.a)[1];self.assertTrue(op['effective']['new/one']['assessed']);self.assertEqual(op['effective']['new/one']['level'],'light');self.assertNotIn('new/one',op['assessments']);self.assertTrue(op['wf_plan_heads']['new/one'])
        self.assertEqual(self.event('new/one','claim',{'summary':'Within approved boundary'})[0],201)
        self.ok('rule_retire',{'ref':'internal@1','reason':'New unknown boundary'});self.assertFalse(self.cv()[1]['bindings']['new/one']['readiness']['valid']);self.assertEqual(self.submit()[0],409)
    def test_rule_rejects_scope_flags_outside_path_and_expiry(self):
        self.prepared();self.ok('assess',{'task':'new/one','scope':self.scope()['scope'],'level':'strict','flags':['unknown_impact'],'reason':'Unknown actual impact'})
        self.ok('rule_register',self.rule());state=self.cv()[1]['rules']['internal@1']['readiness'];self.ok('rule_review',{'ref':'internal@1','context_hash':state['context_hash'],'result':'approve','reason':'Known boundary only','evidence':EV});self.assertEqual(self.op('rule_bind',{**self.scope(),'ref':'internal@1','reason':'Must not override unknown impact'},self.a)[0],409)
        self.assertEqual(self.op('rule_register',self.rule(id='danger',paths=['auth/']))[0],409)
        with patch('task_board.convergence.time.time',return_value=time.time()+90000):self.assertIn('规则已到期',self.cv()[1]['rules']['internal@1']['readiness']['reasons'])
    def test_actual_git_rule_rejects_unapproved_changed_path(self):
        self.repository();self.prepared(True);self.bind(self.rule(paths=['feature.py'],categories=['backend'],repo='main'))
        self.assertEqual(self.event('new/one','claim',{'summary':'Actual Git bounded work'})[0],201)
        from task_board.convergence import rule_delivery
        from task_board.operations import load
        from task_board.governance import load as gov,tasks
        from task_board.store import BoardError
        store=self.hub.store('alpha')
        with store.connection() as db:
            v=load(db);g=gov(db);ts=tasks(db);rule_delivery(store,db,v,ts['new/one'],{'implementation_commit':self.feature},g,ts)
            with self.assertRaises(BoardError):rule_delivery(store,db,v,ts['new/one'],{'implementation_commit':self.head},g,ts)
    def test_expired_attempt_holds_resources_and_old_callbacks_rejected(self):
        lease=self.attempts();p={'attempt':'try1','lease':lease}
        with patch('task_board.convergence.time.time',return_value=time.time()+60):
            self.assertEqual(self.cv()[1]['attempts']['try1']['effective_status'],'needs_recovery');self.assertEqual(self.op('attempt_heartbeat',p,self.a)[0],409)
            self.assertEqual(self.op('attempt_open',{**self.scope(),'id':'try2','workspace':'ws','reason':'Cannot steal old workspace'},self.a)[0],409)
            self.ok('attempt_recover',{'attempt':'try1','stopped':False,'machine':'fixture','summary':'Old worker not yet confirmed stopped','evidence':EV});self.assertEqual(self.op('attempt_open',{**self.scope(),'id':'try2','workspace':'ws','reason':'Still reserved'},self.a)[0],409)
            self.ok('attempt_recover',{'attempt':'try1','stopped':True,'machine':'fixture','summary':'Verified exact process stopped, workspace and resources released','evidence':EV})
        self.ok('attempt_open',{**self.scope(),'id':'try2','workspace':'ws','reason':'Confirmed safe new attempt'},self.a)
        self.assertEqual(self.op('attempt_heartbeat',p,self.a)[0],409);self.assertEqual(self.event('new/one','progress',{'summary':'Old callback','attempt_id':'try1','attempt_lease':lease})[0],409)
    def test_sessions_candidates_selected_exact_input_and_hidden_lease(self):
        lease=self.attempts();self.assertNotIn('id',self.cv()[1]['attempts']['try1']['lease']);self.assertEqual(self.cv(self.a)[1]['attempts']['try1']['lease']['id'],lease)
        self.ok('session_attach',{'attempt':'try1','lease':lease,'id':'s1','session':'session-ref','tool':'codex','model':'unknown','machine':'fixture','previous':'','checkpoint':'','reason':'Continue same bounded approach'},self.a)
        self.assertEqual(self.op('attempt_select',{**self.scope(),'attempt':'try1','reason':'Still running','evidence':EV})[0],409)
        self.ok('attempt_finish',{'attempt':'try1','lease':lease,'status':'candidate','input_anchor':'git:'+'c'*40,'runs':[],'evidence':EV,'stopped':True,'summary':'Stopped exact process, candidate ready'},self.a)
        selection=self.ok('attempt_select',{**self.scope(),'attempt':'try1','reason':'SE chooses exact bounded candidate','evidence':EV})
        self.assertEqual(self.submit()[0],409)
        p={'summary':'Selected actual candidate','completeness':'full','deliverable_ids':['D1'],'implementation_commit':'d'*40,'evidence':EV,'tests':'Actual check','remaining':'none','attempt_id':'try1','selection_id':selection['selection_id']}
        self.assertEqual(self.event('new/one','submit',p)[0],409);p['implementation_commit']='c'*40;self.assertEqual(self.event('new/one','submit',p)[0],201)
        self.assertEqual(self.hub.store('alpha').get('new/one')['latest_submission']['attempt_id'],'try1')
        checkpoint=fixture.CoordinationCase.checkpoint(self,input_anchor='git:'+'c'*40,attempt_id='try1',selection_id=selection['selection_id'])
        self.ok('checkpoint',checkpoint,self.a);self.assertEqual(self.op('checkpoint',{**checkpoint,'id':'old-selection','selection_id':'wrong'},self.a)[0],409)
    def template(self,**kw):return {'id':'starter','version':'1','title':'Bounded starter','description':'Planning only','parameters':['owner'],'items':[{'key':'m','kind':'module_plan','payload':self.module(owner='${owner}',knowledge_refs=[])}],'resource_categories':['research'],'reason':'Reuse approved defaults',**kw}
    def test_template_immutable_parameterized_draft_requires_se_and_no_secrets(self):
        self.member();self.charter();self.ok('template_register',self.template());tpl=self.cv()[1]['templates']['starter@1'];self.ok('template_review',{'ref':'starter@1','definition_hash':tpl['definition_hash'],'result':'approve','reason':'SE checked portable defaults'})
        self.ok('template_instantiate',{'template':'starter@1','id':'instance','version':'1','parameters':{'owner':'root'},'reason':'New approved-boundary draft','evidence':EV},self.a)
        self.assertNotIn('core@1',self.call('/api/projects/alpha/governance',profile=self.admin)[1]['modules']);self.preview('instance@1');self.assertEqual(self.publish('instance@1')[0],201)
        self.assertEqual(self.op('template_register',self.template())[0],409)
        for key in ('token','members','connection'):
            tpl=self.template(id='bad');tpl['items'][0]['payload'][key]='private-value';self.assertEqual(self.op('template_register',tpl)[0],400)
        self.assertEqual(self.op('template_register',self.template(items=[{'key':'m','kind':'module_plan','payload':self.module(owner='root',knowledge_refs=[])}]))[0],400)
    def test_context_workbench_permissions_and_durable_sources(self):
        self.claimed();status,data,_=self.call('/api/projects/alpha/convergence/context?task=new/one',profile=self.a);self.assertEqual(status,200,data);self.assertEqual(data['sha256'],digest({k:v for k,v in data.items() if k!='sha256'}));self.assertTrue(all(s['sha256']==digest(s['summary']) for s in data['sources']));self.assertIn('changes',data)
        for path in ('convergence','convergence/context?task=new/one','convergence/template?ref=starter@1'):self.assertEqual(self.call('/api/projects/alpha/'+path,profile=self.b)[0],404)
        self.assertEqual(self.cv(self.a)[1]['workbench']['my_tasks'][0]['id'],'new/one');self.member(role='viewer');self.assertEqual(self.op('draft_save',self.draft(),self.a)[0],403)
    def test_batch_orders_module_before_new_tasks_and_task_dependencies(self):
        self.claimed();self.charter();spec=deepcopy(self.hub.store('alpha').get('new/one')['spec']);spec.update(id='new/first',allowed_paths=['new/first/']);spec['work']['planning']={'module':'core@1','purpose':'execution','question':'','no_interface_reason':'No shared interface'}
        second=deepcopy(spec);second.update(id='new/second',allowed_paths=['new/second/'],depends_on=['new/first'])
        case={'id':'module-check','version':'1','title':'Bounded module check','kind':'manual','priority':'normal','targets':['module:core@1'],'preconditions':'Approved module','inputs':'Fixed version','steps':'Inspect actual behavior','expected':'Bounded goal achieved','environment':'Fixture','resources':[]}
        items=[{'key':'second','kind':'task_create','payload':{'spec':second,'reason':'Dependent bounded task'}},{'key':'rule','kind':'rule_register','payload':self.rule(cases=['module-check@1'])},{'key':'case','kind':'case','payload':case},{'key':'first','kind':'task_create','payload':{'spec':spec,'reason':'Independent bounded task'}},self.draft()['items'][0]]
        self.ok('draft_save',self.draft(items=items));preview=self.ok('draft_preview',{'ref':'batch@1','approve_modules':['core@1'],'approve_rules':['internal@1']});order=preview['order'];self.assertLess(order.index('module'),order.index('case'));self.assertLess(order.index('case'),order.index('rule'));self.assertLess(order.index('first'),order.index('second'));self.assertEqual(self.publish()[0],201);self.assertEqual(self.hub.store('alpha').get('new/second')['spec']['depends_on'],['new/first']);self.assertTrue(self.cv()[1]['rules']['internal@1']['readiness']['valid'])
    def test_task_scope_after_preview_cannot_be_silently_overwritten(self):
        self.claimed();s=deepcopy(self.hub.store('alpha').get('new/one')['spec']);s['description']='Proposed scope';items=[{'key':'scope','kind':'task_scope','payload':{'spec':s,'reason':'SE review proposal'}}]
        self.ok('draft_save',self.draft(items=items));self.ok('draft_preview',{'ref':'batch@1','approve_modules':[],'approve_rules':[]});self.event('new/one','progress',{'summary':'Actual newer task evidence'});self.assertEqual(self.publish()[0],409)
    def test_rule_specific_implementation_review_is_not_bypassed_by_light_reuse(self):
        self.prepared();self.bind(self.rule(plan_mode='se_review'));self.assertEqual(self.event('new/one','claim',{'summary':'Missing approved implementation plan'})[0],409)
    def test_checkpoint_requires_current_attempt_fence(self):
        lease=self.attempts();p=fixture.CoordinationCase.checkpoint(self)
        self.assertEqual(self.op('checkpoint',p,self.a)[0],404);p.update(attempt_id='try1',attempt_lease=lease);self.ok('checkpoint',p,self.a)
        self.assertEqual(self.op('checkpoint',{**p,'id':'stale','attempt_lease':'wrong'},self.a)[0],409)
    def test_scope_change_preserves_old_workspace_exclusion_and_history(self):
        self.attempts();s=deepcopy(self.hub.store('alpha').get('new/one')['spec']);s['allowed_paths']=['new/scope/'];self.event('new/one','scope',{'spec':s,'reason':'SE changes approved scope'},self.admin)
        self.assertEqual(self.cv()[1]['attempts']['try1']['effective_status'],'needs_recovery');self.atomic('new/two',['src/one/']);self.assertEqual(self.event('new/two','claim',{'summary':'Cannot overwrite old live scope'})[0],409)
    def test_template_export_is_exact_and_reclassification_hides_draft_feed(self):
        self.claimed();self.ok('template_register',self.template());t=self.cv()[1]['templates']['starter@1'];self.ok('template_review',{'ref':'starter@1','definition_hash':t['definition_hash'],'result':'approve','reason':'Portable definition checked'})
        status,data,_=self.call('/api/projects/alpha/convergence/template?ref=starter@1',profile=self.a);self.assertEqual(status,200);import hashlib
        self.assertEqual(data['sha256'],hashlib.sha256(data['document'].encode()).hexdigest());self.assertEqual(json.loads(data['document']),data['definition'])
        p=fixture.resources.ResourcesCase.payload(self,'source',visibility='project');self.gov('resource_register',p);self.ok('draft_save',{**self.draft(),'references':[{'kind':'resource','id':'source'}]},self.a)
        self.assertIn('batch@1',self.cv(self.a)[1]['drafts']);p.update(expected_version=1,visibility='managers');self.gov('resource_update',p);self.assertNotIn('batch@1',self.cv(self.a)[1]['drafts']);feed=self.call('/api/projects/alpha/coordination/feed?limit=100',profile=self.a)[1];self.assertFalse(any(e['action']=='draft_save' for e in feed['items']))
    def test_public_input_shapes_and_project_role_separation(self):
        self.claimed()
        for action,p in [('draft_save',self.draft(items=[{}])),('template_import',{'asset':'none','document':{},'reason':'No object strings'}),('rule_register',self.rule(assets=[])),('attempt_policy',{**self.scope(),'actors':[],'workspaces':[],'max_parallel':1,'lease_seconds':5,'reason':'Invalid'})]:
            self.assertIn(self.op(action,p)[0],(400,404,409))
        for role in ('runner','restorer','tracker'):
            self.member(role=role);self.assertEqual(self.op('draft_save',self.draft(),self.a)[0],403)
    def test_parallel_candidates_use_independent_workspaces_and_preserve_unselected(self):
        self.claimed()
        for n in ('a','b'):
            self.ok('workspace_register',{'id':n,'task':'new/one','location':'G:/fixture/'+n,'machine':'fixture','branch':'codex/'+n,'paths':['src/one/'],'resources':[],'reason':'Independent fixture workspace'})
        self.ok('attempt_policy',{**self.scope(),'actors':['same-agent'],'workspaces':['a','b'],'max_parallel':2,'lease_seconds':300,'reason':'Compare two bounded paths'})
        leases={n:self.ok('attempt_open',{**self.scope(),'id':n,'workspace':n,'reason':'Alternative path '+n},self.a)['lease'] for n in ('a','b')}
        for n in ('a','b'):self.ok('attempt_finish',{'attempt':n,'lease':leases[n],'status':'candidate','input_anchor':'git:'+'c'*40,'runs':[],'evidence':EV,'stopped':True,'summary':'Actual fixture stopped with candidate retained'},self.a)
        self.ok('attempt_select',{**self.scope(),'attempt':'b','reason':'Selected better bounded result','evidence':EV});d=self.cv()[1];self.assertEqual(d['attempts']['a']['status'],'superseded');self.assertIsNotNone(d['attempts']['a']['result']);self.assertEqual(d['attempts']['b']['status'],'selected')
    def test_shared_template_requires_explicit_sha_consumption_and_reapproval(self):
        from . import test_governance as governance
        import hashlib
        self.member();definition=self.template();document=json.dumps(definition,ensure_ascii=False,sort_keys=True,indent=2)+'\n';sha=hashlib.sha256(document.encode()).hexdigest()
        governance.GovernanceCase.asset(self,sha256=sha);governance.GovernanceCase.shared(self,'publish',{'asset':'method@1','audience':['beta'],'shared_location':'https://shared.invalid/approved-template.json','review':'Portable authored template, MIT and exact bytes verified','evidence':EV})
        def beta(action,p):
            revision=self.call('/api/projects/beta/operations',profile=self.admin)[1]['revision'];import uuid
            return self.call('/api/projects/beta/operations',{'request_id':uuid.uuid4().hex,'expected_revision':revision,'action':action,'payload':p},self.admin)
        self.assertEqual(beta('template_import',{'asset':'fixed','document':document,'reason':'No explicit consumption yet'})[0],409)
        self.assertEqual(governance.GovernanceCase.shared(self,'consume',{'alias':'fixed','ref':'alpha/method@1','reason':'Explicit fixed template consumption','tests':'Exact bytes SHA verified'},'beta')[0],201)
        self.assertEqual(beta('template_import',{'asset':'fixed','document':document+' ','reason':'Changed bytes'})[0],409);self.assertEqual(beta('template_import',{'asset':'fixed','document':document,'reason':'Exact fixed bytes'})[0],201)
        t=self.call('/api/projects/beta/convergence',profile=self.admin)[1]['templates']['starter@1'];self.assertIsNone(t['review']);self.assertEqual(beta('template_instantiate',{'template':'starter@1','id':'instance','version':'1','parameters':{'owner':'root'},'reason':'Cannot skip consumer review','evidence':EV})[0],409)
    def test_fixed_shared_asset_rule_can_dispatch_submit_then_blocks_withdrawal(self):
        from . import test_governance as governance
        self.prepared();governance.GovernanceCase.asset(self);governance.GovernanceCase.shared(self,'publish',{'asset':'method@1','audience':['alpha'],'shared_location':'https://shared.invalid/method.json','review':'Approved immutable source and license','evidence':EV});governance.GovernanceCase.shared(self,'consume',{'alias':'fixed','ref':'alpha/method@1','reason':'SE explicit fixed consumption','tests':'Actual fixture hash matched'})
        spec=deepcopy(self.hub.store('alpha').get('new/one')['spec']);spec['work']['assets']=['fixed'];self.assertEqual(self.event('new/one','scope',{'spec':spec,'reason':'Use explicitly approved fixed asset'},self.admin)[0],201)
        self.bind(self.rule(assets={'fixed':'b'*64}));self.assertEqual(self.event('new/one','claim',{'summary':'Valid current rule with fixed asset'})[0],201)
        plan=self.call('/api/projects/alpha/workflow/task?task=new/one',profile=self.a)[1]['current_plan'];anchor='sha256:'+'f'*64
        for item in plan['items']:
            claim=self.ok('criteria_claim',{**self.scope(),'plan':plan['id'],'criterion':item['id'],'input_anchor':anchor,'summary':'Actual bounded fixture inspection','runs':[],'evidence':EV},self.a)
            self.ok('criteria_review',{**self.scope(),'plan':plan['id'],'criterion':item['id'],'claim':claim['claim'],'result':'passed','summary':'Reviewer verified current artifact','evidence':EV})
        p={'summary':'Document artifact with approved fixed asset','completeness':'full','deliverable_ids':['D1'],'artifact':{'ref':'fixture/document.md','sha256':'f'*64},'verification':{'method':'inspection','summary':'Actual fixture inspection','reason':'SE approved finite documentation boundary'},'evidence':[],'remaining':'none'}
        result=self.event('new/one','submit',p);self.assertEqual(result[0],201,result[1])
        governance.GovernanceCase.shared(self,'withdraw',{'ref':'alpha/method@1','reason':'Fixture source revoked','migration':'SE must replace the fixed consumption','evidence':EV});self.assertEqual(self.event('new/one','accept',{'submission':result[1]['event_id'],'summary':'Cannot accept revoked input','deliverable_ids':['D1'],'evidence':EV},self.admin)[0],409)
