"""Progressive planning through the real project-scoped HTTP boundary."""
from copy import deepcopy
import unittest
from . import test_governance as fixture
from task_board.governance import Governance
EV=fixture.EV


class PlanningCase(unittest.TestCase):
    setUp=fixture.GovernanceCase.setUp
    tearDown=fixture.GovernanceCase.tearDown
    call=fixture.GovernanceCase.call
    gov=fixture.GovernanceCase.gov
    event=fixture.GovernanceCase.event
    atomic=fixture.GovernanceCase.atomic
    member=fixture.GovernanceCase.member
    contract=fixture.GovernanceCase.contract

    def snap(self):return self.call('/api/projects/alpha/governance',profile=self.admin)[1]

    def charter(self):
        return self.gov('knowledge',{'background':'Background','goals':'Measurable outcome','non_goals':'Other projects','constraints':'NAS only','materials':[],'entries':[],'history_notes':'New project, no history','resource_notes':'Private repository and isolated fixtures'})

    def module(self,version='1',**kw):
        return {'id':'core','version':version,'title':'Core capability','parent':'','goal':'A usable capability','scope':'Only core','non_goals':'Unrelated features','owner':'root','path':'Investigate, decide, implement, verify','inputs':[],'outputs':['core-result'],'interfaces':[],'no_interface_reason':'Pure local function with no cross-module consumers','risks':'Unknowns tracked explicitly','unknowns':[],'planning_tasks':[],'decisions':[],'depends_on':[],'acceptance':'Behavior and counterexamples','stage':'design','evidence':[],**kw}

    def plan(self,**kw):
        p=self.module(**kw);r=self.gov('module_plan',p);self.assertEqual(r[0],201,r[1]);return p

    def review(self,ref='core@1',**kw):
        p={'ref':ref,'scope':self.snap()['module_readiness'][ref]['scope'],'result':'approve','summary':'Scope and boundaries reviewed','evidence':EV,**kw}
        return self.gov('module_review',p)

    def binding(self,ref='core@1',purpose='execution'):
        return {'module':ref,'purpose':purpose,'question':'What architecture meets the constraints?' if purpose=='planning' else '', 'no_interface_reason':'Independent bounded function; no public interface'}

    def complete(self,tid):
        r=self.event(tid,'claim',{'summary':'Read current scope'});self.assertEqual(r[0],201,r[1])
        r=self.event(tid,'submit',{'summary':'Actual artifact','completeness':'full','deliverable_ids':['D1'],'implementation_commit':'c'*40,'evidence':EV,'tests':'Behavior plus counterexamples passed','remaining':'None'});self.assertEqual(r[0],201,r[1])
        r=self.event(tid,'accept',{'submission':r[1]['event_id'],'summary':'Verified evidence','deliverable_ids':['D1'],'evidence':EV},self.admin);self.assertEqual(r[0],201,r[1])

    def test_new_projects_enforce_planning_but_existing_projects_are_not_rewritten(self):
        old=self.hub.store('alpha').head()
        r=self.call('/api/projects',{'id':'fresh','name':'New','description':'Independent'},self.admin)
        self.assertEqual(r[0],201,r[1])
        new=self.call('/api/projects/fresh/governance',profile=self.admin)[1]
        self.assertEqual(new['planning_policy']['mode'],'enforced');self.assertTrue(new['planning_health']['charter_blockers'])
        self.assertEqual(self.snap()['planning_policy']['mode'],'legacy');self.assertEqual(old,self.hub.store('alpha').head())
        self.gov('planning_enable',{'reason':'Explicit adoption'})
        self.assertEqual(self.event('plan/same','claim',{'summary':'No bypass'},self.admin)[0],409)
        self.atomic();self.assertEqual(self.event('new/one','claim',{'summary':'Unbound'},self.admin)[0],409)

    def test_unknown_module_allows_research_not_development_and_cannot_skip_decision(self):
        self.charter();self.plan(unknowns=['Which parser?'],stage='research')
        self.atomic(planning=self.binding());self.assertEqual(self.event('new/one','claim',{'summary':'Too early'})[0],409)
        self.atomic('research/parser',['research/'],category='research',role='researcher',planning=self.binding(purpose='planning'))
        self.member(role='researcher');self.complete('research/parser')
        self.plan(version='2',planning_tasks=['research/parser'])
        self.assertEqual(self.review('core@2')[0],409)
        p={'id':'parser-choice','question':'Which parser?','conclusion':'Use deterministic format','research_tasks':['research/parser'],'evidence':EV}
        self.assertEqual(self.gov('planning_decision',p,profile=self.a)[0],403)
        self.assertEqual(self.gov('planning_decision',p)[0],201)
        self.plan(version='3',planning_tasks=['research/parser'],decisions=['parser-choice'])
        self.assertEqual(self.review('core@3')[0],201)
        self.member();spec=self.hub.store('alpha').get('new/one')['spec'];spec['work']['planning']=self.binding('core@3')
        self.assertEqual(self.event('new/one','scope',{'spec':spec,'reason':'Decision incorporated'},self.admin)[0],201)
        self.assertEqual(self.event('new/one','claim',{'summary':'Now executable'})[0],201)

    def test_frozen_module_interface_cannot_be_omitted_and_versions_are_immutable(self):
        self.charter();self.contract()
        self.plan(interfaces=['api@1'])
        self.assertEqual(self.review()[0],409) # Contract names backend/frontend, not core.
        self.plan(version='2',id='backend',interfaces=['api@1'])
        self.assertEqual(self.review('backend@2')[0],201)
        self.atomic(planning=self.binding('backend@2'))
        self.member();r=self.event('new/one','claim',{'summary':'Forgot contract'});self.assertEqual(r[0],409);self.assertIn('遗漏',r[1]['error'])
        spec=self.hub.store('alpha').get('new/one')['spec'];spec['work']['contracts']=['api@1']
        self.event('new/one','scope',{'spec':spec,'reason':'Include frozen boundary'},self.admin)
        self.assertEqual(self.event('new/one','claim',{'summary':'Covered'})[0],201)
        self.assertEqual(self.gov('module_plan',self.module())[0],409)

    def test_review_is_stale_after_input_change_and_old_scope_requires_explicit_migration(self):
        self.charter();self.plan();scope=self.snap()['module_readiness']['core@1']['scope']
        self.gov('knowledge',{'background':'Changed goal context','goals':'New goal','non_goals':'Other projects','constraints':'NAS','materials':[],'entries':[],'history_notes':'New','resource_notes':'Private'})
        self.assertEqual(self.review(scope=scope)[0],409)
        self.assertEqual(self.review()[0],201);self.atomic(planning=self.binding());self.member()
        self.plan(version='2');self.assertEqual(self.event('new/one','claim',{'summary':'Old scope'})[0],409)
        self.assertTrue(self.snap()['module_readiness']['core@1']['ready']) # Historical approval retained.

    def test_milestone_requires_completed_linked_tasks_and_separate_stage_evidence(self):
        self.charter();self.plan();self.review();self.atomic(planning=self.binding());self.member()
        p={'id':'M1','version':'1','goal':'Usable result','path':'Build then integrate','entry':'Approved module','modules':['core@1'],'tasks':['new/one'],'acceptance':'Real result works','method':'Integration test and demonstration','threshold':'All required examples pass','environment':'Isolated NAS-equivalent Linux','reviewer':'root','due':'After implementation','risks':'Return failed work for repair'}
        self.assertEqual(self.gov('milestone_plan',p)[0],201)
        def review(**kw):
            c=self.snap()['milestone_readiness']['M1@1'];return self.gov('milestone_review',{'ref':'M1@1','scope':c['scope'],'result':'pass','summary':'Integration observed','evidence':EV,**kw})
        self.assertEqual(review()[0],409);self.complete('new/one')
        self.assertFalse(self.snap()['milestone_readiness']['M1@1']['passed'])
        self.assertEqual(review(evidence=[])[0],400)
        self.assertEqual(review()[0],201);self.assertTrue(self.snap()['milestone_readiness']['M1@1']['passed'])
        self.assertTrue(Governance(self.hub.store('alpha')).verify()['passed'])

    def test_module_parent_cycles_and_foreign_references_do_not_leak(self):
        self.charter();self.plan();self.plan(id='child',parent='core')
        self.assertEqual(self.gov('module_plan',self.module(version='2',parent='child'))[0],409)
        self.assertEqual(self.gov('module_plan',self.module(version='2',planning_tasks=['foreign/task']))[0],409)
        r=self.call('/api/projects/alpha/governance',profile=self.b);self.assertEqual(r[0],404);self.assertNotIn('Core capability',str(r[1]))
        self.assertEqual(self.gov('module_plan',self.module(version='2'),profile=self.a)[0],403)

    def test_declared_cross_module_products_require_a_shared_frozen_boundary(self):
        self.charter();self.plan(id='backend',outputs=['result'])
        self.plan(id='frontend',inputs=['result'])
        self.assertEqual(self.review('backend@1')[0],409)
        self.assertEqual(self.review('frontend@1')[0],409)
        self.contract();self.plan(id='backend',version='2',outputs=['result'],interfaces=['api@1'])
        self.plan(id='frontend',version='2',inputs=['result'],interfaces=['api@1'])
        self.assertEqual(self.review('backend@2')[0],201)
        self.assertEqual(self.review('frontend@2')[0],201)

    def test_reopening_research_invalidates_confirmed_decision_and_downstream_readiness(self):
        self.charter();self.plan(stage='research',unknowns=['choice'])
        self.atomic(category='research',role='researcher',planning=self.binding(purpose='planning'));self.member(role='researcher');self.complete('new/one')
        self.gov('planning_decision',{'id':'D1','question':'Choice','conclusion':'Use A','research_tasks':['new/one'],'evidence':EV})
        self.plan(version='2',planning_tasks=['new/one'],decisions=['D1']);self.assertEqual(self.review('core@2')[0],201)
        latest=self.hub.store('alpha').get('new/one')['latest_submission']['id']
        self.assertEqual(self.event('new/one','reopen',{'submission':latest,'reason':'Counterexample','findings':[{'description':'Research assumption failed','acceptance':'Reproduce and revise conclusion'}]},self.admin)[0],201)
        c=self.snap()['module_readiness']['core@2'];self.assertFalse(c['ready']);self.assertTrue(any('来源已变化' in b for b in c['blockers']))

    def test_invalid_initial_context_leaves_no_project_directory(self):
        r=self.call('/api/projects',{'id':'invalid','name':'Invalid','description':'No allocation','knowledge':{}},self.admin)
        self.assertEqual(r[0],400);self.assertFalse((self.state/'projects/invalid').exists())

    def test_interface_change_includes_module_owner_before_any_execution_tasks_exist(self):
        self.charter();self.member();self.contract();self.contract(version='2')
        self.plan(id='backend',owner='same-agent',interfaces=['api@1'])
        r=self.gov('contract_propose',{'id':'replace','contract':'api@1','replacement':'api@2','migration':'Explicit version migration','tests':'Contract tests'})
        self.assertEqual(r[0],201,r[1]);change=self.snap()['changes']['replace']
        self.assertIn('same-agent',change['required']);self.assertIn('backend@1',change['impact']['module_scopes'])

    def test_whitespace_does_not_satisfy_interface_attestation(self):
        self.charter();self.plan(no_interface_reason='   ')
        self.assertEqual(self.review()[0],409)


if __name__=='__main__':unittest.main()
