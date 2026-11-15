"""Bounded authority never becomes membership or bypasses delivery gates."""
import time,unittest,uuid
from types import SimpleNamespace
from unittest.mock import patch
from . import test_projects as fixture
from . import test_governance as gf
from task_board.operations import Operations
from task_board.delegation import anchor

class DelegationCase(unittest.TestCase):
    setUp=fixture.ProjectCase.setUp;tearDown=fixture.ProjectCase.tearDown;call=fixture.ProjectCase.call
    atomic=gf.GovernanceCase.atomic;gov=gf.GovernanceCase.gov;event=gf.GovernanceCase.event
    def op(self,action,p,who=None,delegation=None,rid=None):
        req={'request_id':rid or uuid.uuid4().hex,'expected_revision':Operations(self.hub.store('alpha')).snapshot()['revision'],'action':action,'payload':p}
        if delegation:req['delegation']=delegation
        return self.call('/api/projects/alpha/operations',req,who or self.admin)
    def setup_work(self):
        self.gov('member',{'actor':self.a['actor'],'role':'worker','scope':'execute own task'})
        self.other=self.hub.invite('alpha','independent-worker');self.gov('member',{'actor':self.other['actor'],'role':'worker','scope':'independent task review'})
        self.atomic('work/one');self.assertEqual(self.event('work/one','claim',{'summary':'take'},self.a)[0],201)
        result=self.event('work/one','submit',{'summary':'Implementation','completeness':'full','deliverable_ids':['D1'],'implementation_commit':'c'*40,'evidence':gf.EV,'tests':'Behavior verified in fixture','remaining':'none','addresses':[]},self.a);self.assertEqual(result[0],201,result)
    def grant(self,**kw):
        t=self.hub.store('alpha').get('work/one');self.definition={'id':'grant-one','task':'work/one','scope':t['scope_hash'],'scope_version':t['scope_version'],'input_anchor':anchor(t),'grantee':self.other['actor'],'actions':['accept'],'expires':time.time()+3600,'reason':'Independent review within exact delivery',**kw};return self.op('delegation_grant',self.definition)
    def accept(self,delegation='grant-one',who=None,rid=None):
        t=self.hub.store('alpha').get('work/one');p={'submission':t['latest_submission']['id'],'summary':'Independently checked current output','deliverable_ids':['D1'],'evidence':gf.EV};req={'request_id':rid or uuid.uuid4().hex,'task_id':'work/one','action':'accept','expected_revision':t['revision'],'scope_version':t['scope_version'],'payload':p,'delegation':delegation};return self.call('/api/projects/alpha/events',req,who or self.other),req
    def test_granted_accept_records_attribution_without_role_elevation(self):
        self.setup_work();self.assertEqual(self.grant()[0],201);result,req=self.accept();self.assertEqual(result[0],201,result)
        self.assertEqual(self.hub.effective_actor(self.hub.resolve(self.other['token']),'alpha')['project_role'],'worker')
        self.assertEqual(self.call('/api/projects/beta/delegations',profile=self.other)[0],404)
        self.assertEqual(self.gov('worker_access',{'enabled':True,'reason':'cannot escalate'},self.other)[0],403)
        receipt=self.hub.store('alpha').receipt(result[1]['event_id']);self.assertEqual(receipt['event']['payload']['delegation'],'grant-one')
        self.op('delegation_revoke',{'id':'grant-one','reason':'work finished'});self.assertTrue(self.call('/api/projects/alpha/events',req,self.other)[1]['replayed'])
    def test_self_review_strict_final_and_grant_forgery_are_rejected(self):
        self.setup_work();self.assertEqual(self.grant(grantee=self.a['actor'])[0],403)
        t=self.hub.store('alpha').get('work/one');self.op('assess',{'task':'work/one','scope':t['scope_hash'],'level':'strict','flags':['permission'],'reason':'permission boundary'})
        self.assertEqual(self.grant()[0],403);self.assertEqual(self.accept()[0][0],403)
        self.assertEqual(self.op('delegation_grant',self.definition,self.other)[0],403)
    def test_revoked_expired_wrong_action_and_changed_anchor_fail(self):
        self.setup_work();self.assertEqual(self.grant()[0],201);self.assertEqual(self.accept(who=self.a)[0][0],403)
        self.op('delegation_revoke',{'id':'grant-one','reason':'Scope needs SE'});self.assertEqual(self.accept()[0][0],403)
        self.assertEqual(self.grant(id='expired',expires=time.time()-1)[0],400)
        self.assertEqual(self.grant(id='wrong-action',actions=['member'])[0],400)
        self.assertEqual(self.grant(id='wrong-input',input_anchor='git:'+'d'*40)[0],409)
    def test_original_criteria_gates_still_reject_authorized_accept(self):
        self.setup_work();t=self.hub.store('alpha').get('work/one');self.op('criteria_plan',{'task':'work/one','scope':t['scope_hash'],'scope_version':t['scope_version'],'id':'required-plan','items':[{'id':'A1','deliverable':'D1','method':'inspection','expected':'Current evidence reviewed'}],'defaults':'','git_required':False,'repo':'','reason':'Explicit completion criterion'})
        self.assertEqual(self.grant()[0],201);result,_=self.accept();self.assertEqual(result[0],409,result)
    def test_existing_grant_expires_and_verification_plan_change_invalidates_it(self):
        self.setup_work();self.assertEqual(self.grant()[0],201)
        with patch('task_board.delegation.time',SimpleNamespace(time=lambda:self.definition['expires']+1)):self.assertEqual(self.accept()[0][0],403)
        t=self.hub.store('alpha').get('work/one');self.op('criteria_plan',{'task':'work/one','scope':t['scope_hash'],'scope_version':t['scope_version'],'id':'new-plan','items':[{'id':'A1','deliverable':'D1','method':'inspection','expected':'New condition'}],'defaults':'','git_required':False,'repo':'','reason':'New SE verification boundary'})
        self.assertEqual(self.accept()[0][0],409)
