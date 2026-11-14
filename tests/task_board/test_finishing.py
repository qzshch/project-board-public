"""Integration coverage across distinct workers, current input and lean actions."""
import json,time,unittest
from copy import deepcopy
from unittest.mock import patch
from . import test_convergence as fixture
from . import test_coordination as coordination_fixture
from . import test_planning as planning
from task_board.store import digest
EV=fixture.EV

class FinishingCase(unittest.TestCase):
    setUp=fixture.ConvergenceCase.setUp;tearDown=fixture.ConvergenceCase.tearDown
    call=fixture.ConvergenceCase.call;gov=fixture.ConvergenceCase.gov;member=fixture.ConvergenceCase.member;atomic=fixture.ConvergenceCase.atomic;event=fixture.ConvergenceCase.event
    git=fixture.ConvergenceCase.git;action=fixture.ConvergenceCase.action;query=fixture.ConvergenceCase.query;repository=fixture.ConvergenceCase.repository
    op=fixture.ConvergenceCase.op;scope=fixture.ConvergenceCase.scope;claimed=fixture.ConvergenceCase.claimed;submit=fixture.ConvergenceCase.submit
    module=fixture.ConvergenceCase.module;charter=fixture.ConvergenceCase.charter;prepared=fixture.ConvergenceCase.prepared
    cv=fixture.ConvergenceCase.cv;ok=fixture.ConvergenceCase.ok;co=coordination_fixture.CoordinationCase.co
    checkpoint=coordination_fixture.CoordinationCase.checkpoint;plan=coordination_fixture.CoordinationCase.plan;gate=coordination_fixture.CoordinationCase.gate
    def participants(self):
        self.claimed();self.other=self.hub.invite('alpha','participant');self.member('participant','developer')
        for id in ('a','b'):self.ok('workspace_register',{'id':id,'task':'new/one','location':'G:/fixture/'+id,'machine':'fixture','branch':'codex/'+id,'paths':['src/one/'],'resources':[],'reason':'Distinct bounded workspaces'})
        self.ok('attempt_policy',{**self.scope(),'actors':['same-agent','participant'],'workspaces':['a','b'],'max_parallel':2,'lease_seconds':300,'reason':'Two different authorized workers'})
        self.fences={}
        for n,profile in [('a',self.a),('b',self.other)]:
            receipt=self.ok('attempt_open',{**self.scope(),'id':n,'workspace':n,'reason':'Independent approach'},profile);self.fences[n]={'attempt_id':n,'attempt_lease':receipt['lease']}
    def test_distinct_participant_checkpoint_progress_wait_and_owner_control(self):
        self.participants();p=self.checkpoint(id='b-point',**self.fences['b']);self.ok('checkpoint',p,self.other)
        # Simulate a checkpoint persisted by the previous release without rewriting history.
        with patch('task_board.finishing.public_record',side_effect=lambda p:deepcopy(p)):self.ok('checkpoint',self.checkpoint(id='legacy-point',**self.fences['b']),self.other)
        self.assertNotIn(self.fences['b']['attempt_lease'],json.dumps(self.call('/api/projects/alpha/operations',profile=self.admin)[1]))
        self.assertEqual(self.co(self.other,'new/one')[1]['resume']['checkpoint']['id'],'legacy-point');self.ok('checkpoint',self.checkpoint(id='a-point',**self.fences['a']),self.a)
        self.assertEqual(self.co(self.other,'new/one')[1]['resume']['checkpoint']['id'],'legacy-point');self.assertEqual(self.co(self.a,'new/one')[1]['resume']['checkpoint']['id'],'a-point')
        data=self.cv(self.other)[1];self.assertEqual(data['workbench']['my_tasks'][0]['participation'],'participant');self.assertNotIn(self.fences['b']['attempt_lease'],json.dumps(self.co(self.a)[1]))
        result=self.event('new/one','progress',{'summary':'Own bounded progress',**self.fences['b']},self.other);self.assertEqual(result[0],201,result[1]);self.assertEqual(self.hub.store('alpha').get('new/one')['owner'],'same-agent')
        p={'task':'new/one','scope':self.scope()['scope'],'mode':'work','phase':'testing','reason':'Actual own attempt work','rework':False,**self.fences['b']};self.ok('time_change',p,self.other)
        thread={**self.scope(),'id':'participant-blocker','kind':'blocker','title':'Need SE input','body':'Bounded input missing','to':['SE'],'pause':True,'affected_step':'Own approach',**self.fences['b']};self.ok('thread_open',thread,self.other)
        self.ok('thread_decide',{'thread':'participant-blocker','decision':'continue','summary':'Fixed input supplied','reference':''});self.ok('thread_ack',{'thread':'participant-blocker','summary':'Input checked',**self.fences['b']},self.other)
        self.assertEqual(self.event('new/one','submit',{'summary':'Cannot take owner delivery'},self.other)[0],403)
    def test_participant_expired_foreign_fence_and_no_fence_are_denied(self):
        self.participants();p=self.checkpoint(id='wrong',**self.fences['a']);self.assertEqual(self.op('checkpoint',p,self.other)[0],403)
        self.assertEqual(self.op('checkpoint',self.checkpoint(),self.other)[0],403)
        self.assertEqual(self.op('checkpoint',self.checkpoint(attempt_id=['bad'],attempt_lease='bad'),self.other)[0],400)
        self.assertEqual(self.op('thread_open',{**self.scope(),'id':'malformed-proof','kind':'discussion','title':'Bad shape','body':'Must reject without poisoning filtered feed','to':['SE'],'pause':False,'affected_step':'None','attempt_id':[]},self.other)[0],400)
        with patch('task_board.finishing.time.time',return_value=time.time()+600):
            self.assertEqual(self.op('checkpoint',self.checkpoint(id='expired',**self.fences['b']),self.other)[0],409)
        self.assertEqual(self.call('/api/projects/beta/convergence',profile=self.other)[0],404)
        self.assertEqual(self.cv(self.a)[1]['attempts']['b']['effective_status'],'running')
    def test_context_entries_dedup_pagination_and_task_feed(self):
        self.prepared();g=self.call('/api/projects/alpha/governance',profile=self.admin)[1]['knowledge'];g['materials']=[{'title':'same material','location':'nas/same','version':'1','sha256':'b'*64}];g['entries']=[{'title':'same entry','location':'nas/same','version':'1','sha256':'b'*64}]+[{'title':'entry '+str(i),'location':'nas/entry'+str(i),'version':'1','sha256':'c'*64} for i in range(34)];self.gov('knowledge',g)
        self.gov('module_plan',self.module('2',knowledge_refs=['nas/same']+['nas/entry'+str(i) for i in range(34)]));t=self.hub.store('alpha').get('new/one');s=deepcopy(t['spec']);s['work']['planning']['module']='core@2';self.event('new/one','scope',{'spec':s,'reason':'Cite registered entries'},self.admin)
        self.atomic('new/unrelated',['other/']);self.event('new/unrelated','claim',{'summary':'Other work'});self.event('new/unrelated','progress',{'summary':'Unrelated task progress'})
        result=self.call('/api/projects/alpha/convergence/context?task=new/one',profile=self.a);self.assertEqual(result[0],200,result[1]);p=result[1];materials=[x for x in p['sources'] if x['kind'] in ('material','entry')];self.assertEqual(len(materials),32);self.assertEqual(len([x for x in materials if x['id']=='nas/same']),1);self.assertTrue(any(x['kind']=='entry' for x in materials));self.assertEqual(len(p['material_readback']['remaining_locations']),3);self.assertTrue(p['materials_truncated']);self.assertFalse(any(x['task']=='new/unrelated' for x in p['changes']['items']));self.assertTrue(any(x['relevance']=='project_boundary' for x in p['changes']['items']))
        g['entries'][0]['sha256']='d'*64;self.gov('knowledge',g);p=self.call('/api/projects/alpha/convergence/context?task=new/one',profile=self.a)[1];source=next(x for x in p['sources'] if x['id']=='nas/same');self.assertTrue(source['summary']['source_conflict']);self.assertEqual({x['sha256'] for x in source['summary']['registrations']},{'b'*64,'d'*64})
    def test_task_feed_keeps_prerequisite_and_filters_attempt_events(self):
        self.participants();self.atomic('new/other',['other/']);self.event('new/other','claim',{'summary':'Other task'});self.event('new/other','progress',{'summary':'Other progress'})
        self.ok('attempt_heartbeat',{'attempt':'b','lease':self.fences['b']['attempt_lease']},self.other)
        data=self.call('/api/projects/alpha/coordination/feed?task=new/one&limit=100',profile=self.a)[1];self.assertFalse(any(e['task']=='new/other' for e in data['items']));self.assertTrue(any(e['action']=='attempt_heartbeat' for e in data['items']));self.assertEqual(self.call('/api/projects/alpha/coordination/feed?task=foreign',profile=self.a)[0],404)
        self.atomic('new/prerequisite',['pre/']);self.event('new/prerequisite','claim',{'summary':'Required research'});self.event('new/prerequisite','progress',{'summary':'Prerequisite progress'});s=deepcopy(self.hub.store('alpha').get('new/one')['spec']);s['depends_on']=['new/prerequisite'];self.assertEqual(self.event('new/one','scope',{'spec':s,'reason':'Explicit real prerequisite'},self.admin)[0],201)
        data=self.call('/api/projects/alpha/coordination/feed?task=new/one&limit=100',profile=self.a)[1];self.assertTrue(any(e['task']=='new/prerequisite' and e['relevance']=='related_task' for e in data['items']))
    def acceptance(self):
        self.claimed();p={**self.scope(),'id':'accept','items':[{'id':'A','deliverable':'D1','expected':'Expected A','method':'manual'},{'id':'B','deliverable':'D1','expected':'Expected B','method':'inspection'}],'defaults':'','git_required':False,'repo':'','reason':'Fixed criteria'};self.ok('criteria_plan',p);return p
    def test_batch_claim_review_atomic_and_exact_claim_ids(self):
        p=self.acceptance();batch={**self.scope(),'plan':'accept','input_anchor':'git:'+'c'*40,'runs':[],'evidence':EV,'items':[{'criterion':'A','summary':'Actual A'},{'criterion':'missing','summary':'Invalid late item'}]};self.assertEqual(self.op('criteria_claim_batch',batch,self.a)[0],404);self.assertFalse(self.call('/api/projects/alpha/workflow/task?task=new/one',profile=self.a)[1]['claims'])
        batch['items'][1]['criterion']='B';receipt=self.ok('criteria_claim_batch',batch,self.a);self.assertEqual(len(receipt['items']),2)
        rows=self.call('/api/projects/alpha/workflow/task?task=new/one',profile=self.a)[1]['claims'];review={**self.scope(),'plan':'accept','evidence':EV,'items':[{'criterion':k,'claim':rows['accept:'+k]['id'],'result':'passed','summary':'SE checked '+k} for k in ('A','B')]};review['items'][1]['claim']='old';self.assertEqual(self.op('criteria_review_batch',review)[0],409);self.assertFalse(self.call('/api/projects/alpha/workflow/task?task=new/one',profile=self.a)[1]['verdicts']);review['items'][1]['claim']=rows['accept:B']['id'];self.ok('criteria_review_batch',review);self.assertEqual(self.op('criteria_review_batch',review,self.a)[0],403)
    def test_conditions_graph_current_and_retired_without_claim_side_effect(self):
        self.claimed();self.ok('condition_gate',self.gate());g=self.call('/api/projects/alpha/governance',profile=self.a)[1];self.assertEqual(g['condition_nodes'][0]['id'],'gate:external');self.assertIn({'from':'gate:external','to':'new/one','type':'condition'},g['graph']);self.assertEqual(self.submit()[0],409)
        gate=self.co()[1]['gates']['external'];self.ok('gate_retire',{'id':'external','gate_hash':gate['gate_hash'],'reason':'Explicit replacement'});self.assertFalse(self.call('/api/projects/alpha/governance',profile=self.a)[1]['condition_nodes'])
    def test_git_batch_keeps_phases_and_rejects_real_outside_paths(self):
        self.repository();self.member();self.atomic(paths=['feature.py'],baseline=self.first);self.event('new/one','claim',{'summary':'Fixed Git input'})
        p={**self.scope(),'repo':'main','baseline':self.first,'implementation':self.head,'target':self.head,'phases':['submit','merge'],'reason':'Invalid extra changed path'}
        self.assertEqual(self.op('git_check_batch',p,self.a)[0],409);self.assertFalse(self.call('/api/projects/alpha/workflow/task?task=new/one',profile=self.a)[1]['checks'])
        p.update(implementation=self.feature,target=self.feature,phases=['submit','merge','native'])
        # Three independent Git phases may outlive the single-action 5s HTTP bound.
        original=self.opener.open
        with patch.object(self.opener,'open',side_effect=lambda req,timeout:original(req,timeout=20)):self.ok('git_check_batch',p,self.a)
        checks=self.call('/api/projects/alpha/workflow/task?task=new/one',profile=self.a)[1]['checks'];self.assertEqual({x['phase'] for x in checks.values()},{'submit','merge','native'});self.assertEqual(self.hub.store('alpha').get('new/one')['status'],'active')
    def test_batch_cannot_replace_automated_verification_or_repeat_criterion(self):
        self.claimed();self.ok('criteria_plan',{**self.scope(),'id':'auto','items':[{'id':'A','deliverable':'D1','expected':'Actual automation','method':'automated'}],'defaults':'','git_required':False,'repo':'','reason':'Requires real automated input'})
        p={**self.scope(),'plan':'auto','input_anchor':'git:'+'c'*40,'runs':[],'evidence':EV,'items':[{'criterion':'A','summary':'Manual assertion is not an automated result'}]};self.assertEqual(self.op('criteria_claim_batch',p,self.a)[0],409)
        self.ok('criteria_plan',{**self.scope(),'id':'manual','items':[{'id':'A','deliverable':'D1','expected':'Inspection','method':'inspection'}],'defaults':'','git_required':False,'repo':'','reason':'Explicit different inspection plan'})
        p['plan']='manual';p['items']*=2;self.assertEqual(self.op('criteria_claim_batch',p,self.a)[0],400);self.assertFalse(self.call('/api/projects/alpha/workflow/task?task=new/one',profile=self.a)[1]['claims'])
    def test_completed_task_old_conditions_not_current_workbench(self):
        self.claimed();self.submit();sub=self.hub.store('alpha').get('new/one')['latest_submission']['id'];self.event('new/one','accept',{'submission':sub,'summary':'Actual verified delivery','deliverable_ids':['D1'],'evidence':EV},self.admin)
        self.ok('condition_gate',self.gate(id='old-final-condition'));self.assertFalse(any(x['kind']=='condition' for x in self.cv()[1]['workbench']['items']))
    def test_results_tracking_ignores_notes_but_reopen_invalidates(self):
        self.member();self.charter();self.atomic('research/one',['research/'],category='research');planning.PlanningCase.complete(self,'research/one')
        self.gov('planning_decision',{'id':'choice','question':'Architecture?','conclusion':'Bounded result','research_tasks':['research/one'],'research_tracking':'results','evidence':EV});self.gov('module_plan',self.module(planning_tasks=['research/one'],decisions=['choice'],knowledge_refs=[],research_tracking='results'))
        g=self.call('/api/projects/alpha/governance',profile=self.admin)[1];scope=g['module_readiness']['core@1']['scope'];self.gov('module_review',{'ref':'core@1','scope':scope,'result':'approve','summary':'Current result accepted','evidence':EV})
        self.event('research/one','note',{'summary':'Non-semantic reading note'},self.admin);g=self.call('/api/projects/alpha/governance',profile=self.admin)[1];self.assertEqual(scope,g['module_readiness']['core@1']['scope']);self.assertTrue(g['module_readiness']['core@1']['ready'])
        sub=self.hub.store('alpha').get('research/one')['latest_submission']['id'];self.event('research/one','reopen',{'submission':sub,'reason':'Result boundary false','findings':[{'description':'Counterexample','acceptance':'Correct the result'}]},self.admin);self.assertFalse(self.call('/api/projects/alpha/governance',profile=self.admin)[1]['module_readiness']['core@1']['ready'])
