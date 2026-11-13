"""Behavior and counterexamples at the real authorized HTTP boundary."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import sqlite3
import unittest
import uuid
from . import test_projects as fixtures
from task_board.governance import Governance
from task_board.store import digest, BoardError

SHA='b'*64
EV=[{'path':'G:/project-board/evidence/fixture/report.json','sha256':SHA}]

class GovernanceCase(unittest.TestCase):
    setUp=fixtures.ProjectCase.setUp
    tearDown=fixtures.ProjectCase.tearDown
    call=fixtures.ProjectCase.call

    def gov(self,action,payload,profile=None,project='alpha',revision=None,rid=None):
        snap=self.call('/api/projects/'+project+'/governance',profile=profile or self.admin)[1]
        return self.call('/api/projects/'+project+'/governance',{'request_id':rid or str(uuid.uuid4()),'expected_revision':snap['revision'] if revision is None else revision,'action':action,'payload':payload},profile or self.admin)

    def member(self,actor='same-agent',role='developer'):
        status,body,_=self.gov('member',{'actor':actor,'role':role,'scope':'Only the assigned task, no public interface edits'})
        self.assertEqual(status,201,body)

    def atomic(self,tid='new/one',paths=None,**work):
        spec={'id':tid,'title':'one atom','description':'bounded implementation','kind':'atomic','deliverables':[{'id':'D1','label':'reviewed code'}],'registered':True,'claimable':True,'allowed_paths':paths or ['src/one/'],
              'work':{'category':'backend','role':'developer','inputs_known':True,'inputs':['spec@sha256:'+SHA],'outputs':['out:'+tid],'contracts':[],'assets':[],'resources':[],'couplings':[],'baseline':'a'*40,'acceptance':'actual behavior and counterexamples',**work}}
        result=self.event(tid,'create',{'spec':spec,'reason':'new atomic scope'},self.admin)
        self.assertEqual(result[0],201,result[1]);return spec

    def event(self,tid,action,payload,profile=None):
        task=self.hub.store('alpha').get(tid) if action!='create' else None
        return self.call('/api/projects/alpha/events',{'request_id':str(uuid.uuid4()),'task_id':tid,'action':action,'expected_revision':task['revision'] if task else 0,'scope_version':task['scope_version'] if task else 1,'payload':payload},profile or self.a)

    def contract(self,version='1'):
        return self.gov('contract_freeze',{'id':'api','version':version,'owner':'root','signature':'POST /x {value:int} -> {result:int}','units':'milliseconds','errors':'400 bad input, 409 stale','transaction':'one SQLite immediate transaction','idempotency':'actor/request_id','source':'docs/api@'+SHA,'producers':['backend'],'consumers':['frontend'],'compatibility':'retain v1 until explicit migration','evidence':EV})

    def asset(self,version='1',**kw):
        return self.gov('asset',{'id':'method','version':version,'kind':'methodology','source':'authored independently','license':'MIT','sensitivity':'public','sha256':SHA,'location':'private/project/notes.md','owner':'root','shareable':True,'evidence':EV,**kw})

    def shared(self,action,payload,project='alpha',profile=None,rid=None):
        return self.call('/api/projects/'+project+'/shared',{'action':action,'payload':payload,'request_id':rid or str(uuid.uuid4())},profile or self.admin)

    def publish(self,version='1',audience=None):
        self.assertEqual(self.asset(version)[0],201)
        return self.shared('publish',{'asset':'method@'+version,'audience':audience or ['beta'],'shared_location':'https://shared.invalid/method-'+version+'.md','review':'license/sensitivity/hash reviewed','evidence':EV})

    def test_new_surfaces_reject_foreign_projects_before_any_content(self):
        self.gov('knowledge',{'background':'alpha confidential','goals':'one','non_goals':'two','constraints':'three','materials':[],'entries':[]})
        for path in ('governance','graph','search?q=alpha','governance/export','governance/verify','brief?task=plan/same','shared','shared/impact?ref=alpha/method@1'):
            status,body,headers=self.call('/api/projects/alpha/'+path,profile=self.b)
            self.assertEqual(status,404,(path,body));self.assertNotIn('ETag',headers);self.assertNotIn('confidential',json.dumps(body))
        for path in ('governance','shared'):
            self.assertEqual(self.call('/api/projects/alpha/'+path,{'action':'knowledge','payload':{}},self.b)[0],404)

    def test_governance_validation_stale_versions_idempotence_and_chain(self):
        rid=str(uuid.uuid4());p={'id':'M1','goal':'goal','acceptance':'test','status':'planned','evidence':[]}
        first=self.gov('milestone',p,revision=0,rid=rid);self.assertEqual(first[0],201)
        self.assertEqual(self.gov('milestone',p,revision=0,rid=rid)[1]['replayed'],True)
        self.assertEqual(self.gov('milestone',p,revision=0)[0],409)
        self.assertEqual(self.gov('milestone',{**p,'status':'passed'})[0],400)
        self.assertEqual(self.gov('member',{'actor':'same-agent','role':'invented','scope':'x'})[0],400)
        self.assertEqual(self.gov('milestone',p,profile=self.a)[0],403)
        self.assertTrue(Governance(self.hub.store('alpha')).verify()['passed'])
        with self.hub.store('alpha').connection() as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM governance_events')

    def test_handoff_requires_acceptance_and_removes_former_owner_privileges(self):
        owner=self.hub.invite('alpha','lead-one');se=self.hub.invite('alpha','lead-two')
        self.member('lead-one','owner');self.member('lead-two','se')
        p={'to':'lead-two','risks':'no known runtime hazards','materials':['spec@1'],'reason':'new session takes over'}
        self.assertEqual(self.gov('handoff_propose',p,owner)[0],201)
        snap=self.call('/api/projects/alpha/governance',profile=se)[1];scope=snap['handoff']['scope']
        self.assertEqual(self.gov('handoff_accept',{'scope':scope,'summary':'read all'},self.a)[0],409)
        self.assertEqual(self.gov('handoff_accept',{'scope':scope,'summary':'read all'},se)[0],201)
        self.assertEqual(self.gov('decision',{'summary':'bad','reason':'old lead','evidence':EV},owner)[0],403)
        self.assertEqual(self.call('/api/projects/alpha/actors',{'actor':'lead-three'},owner)[0],403)
        self.assertEqual(self.gov('decision',{'summary':'good','reason':'new lead','evidence':EV},se)[0],201)

    def test_handoff_is_invalidated_when_active_scope_changes(self):
        self.hub.invite('alpha','lead-two');self.member('lead-two','se')
        self.gov('handoff_propose',{'to':'lead-two','risks':'unknown','materials':[],'reason':'inherit'})
        scope=self.call('/api/projects/alpha/governance',profile=self.a)[1]['handoff']['scope']
        self.atomic()
        profile=json.loads((self.state/'_private/admin.json').read_text('utf8'))
        # Wrong identity cannot accept regardless of root access.
        self.assertEqual(self.gov('handoff_accept',{'scope':scope,'summary':'stale'},profile)[0],409)

    def test_concurrent_disjoint_task_claims_with_same_writer_path_have_one_winner(self):
        self.member();other=self.hub.invite('alpha','dev-two');self.member('dev-two')
        self.atomic('new/one',['src/Shared/']);self.atomic('new/two',['src/shared/a.py'])
        def claim(pair):return self.event(pair[0],'claim',{'summary':'take'},pair[1])[0]
        with ThreadPoolExecutor(2) as pool:statuses=list(pool.map(claim,[('new/one',self.a),('new/two',other)]))
        self.assertEqual(sorted(statuses),[201,409])

    def test_exclusive_resource_and_shared_database_couplings_block_parallel_claim(self):
        self.member();self.atomic('new/one',['src/a/'],resources=['port:25000'],couplings=['db:schema'])
        self.atomic('new/two',['src/b/'],resources=['port:25000'],couplings=['db:schema'])
        self.assertEqual(self.event('new/one','claim',{'summary':'take'})[0],201)
        status,body,_=self.event('new/two','claim',{'summary':'take'})
        self.assertEqual(status,409);self.assertIn('排他资源',body['error']);self.assertIn('共享修改',body['error'])

    def test_unknown_inputs_role_and_unfrozen_contract_are_refused(self):
        self.member(role='researcher');self.atomic(inputs_known=False,contracts=['api@1'])
        status,body,_=self.event('new/one','claim',{'summary':'take'})
        self.assertEqual(status,409)
        for reason in ('输入未知','执行角色','接口未冻结'):self.assertIn(reason,body['error'])

    def test_contract_versions_are_immutable_and_switch_needs_current_impact_confirmations(self):
        self.assertEqual(self.contract()[0],201);self.assertEqual(self.contract()[0],409);self.assertEqual(self.contract('2')[0],201)
        self.atomic(contracts=['api@1'])
        p={'id':'change-one','contract':'api@1','replacement':'api@2','migration':'upgrade direct/transitive tasks','tests':'contract compatibility tests'}
        self.assertEqual(self.gov('contract_propose',p)[0],201)
        self.assertEqual(self.gov('contract_execute',{'id':'change-one'})[0],409)
        snap=self.call('/api/projects/alpha/governance',profile=self.a)[1];c=snap['changes']['change-one']
        self.assertEqual(c['impact']['direct'],['new/one'])
        self.assertEqual(self.gov('contract_confirm',{'id':'change-one','impact_hash':digest(c['impact']),'summary':'migration reviewed'})[0],201)
        self.assertEqual(self.gov('contract_execute',{'id':'change-one'})[0],201)
        self.member();self.assertEqual(self.event('new/one','claim',{'summary':'old interface'})[0],409)

    def test_packages_are_mapping_not_completion_and_brief_is_project_specific(self):
        self.atomic();self.gov('package',{'id':'legacy/pack','tasks':['new/one'],'source':'old history@1','unknown':'old atom breakdown not verified'})
        status,body,_=self.call('/api/projects/alpha/brief?task=new/one',profile=self.a)
        self.assertEqual(status,200);self.assertEqual(body['project_id'],'alpha');self.assertEqual(body['baseline'],'a'*40)
        self.assertNotIn('token',body);self.assertEqual(self.hub.store('alpha').get('new/one')['status'],'planned')

    def test_asset_publish_requires_explicit_shareable_public_generic_version(self):
        self.assertEqual(self.asset(sensitivity='secret')[0],201)
        p={'asset':'method@1','audience':['beta'],'shared_location':'shared/only','review':'request','evidence':EV}
        self.assertEqual(self.shared('publish',p)[0],403)
        self.assertEqual(self.asset()[0],409)
        self.assertEqual(self.call('/api/projects/beta/shared',profile=self.b)[1]['releases'],[])

    def test_shared_versions_do_not_drift_and_consumer_identities_are_filtered(self):
        self.assertEqual(self.publish()[0],201)
        self.assertEqual(self.shared('consume',{'alias':'method','ref':'alpha/method@1','reason':'reviewed','tests':'passed'},'beta')[0],201)
        self.assertEqual(self.publish('2')[0],201)
        before=self.call('/api/projects/beta/shared',profile=self.b)[1]
        self.assertEqual(before['consumption']['method']['release'],'alpha/method@1')
        raw=json.dumps(before);self.assertNotIn('private/project',raw)
        impact=self.call('/api/projects/alpha/shared/impact?ref=alpha/method@1',profile=self.reviewer)[1]
        self.assertEqual(impact['consumers'],[])
        self.assertEqual(self.shared('upgrade',{'alias':'method','ref':'alpha/method@2','reason':'upgrade approved','tests':'new regression passed'},'beta')[0],201)
        self.assertEqual(self.call('/api/projects/beta/shared',profile=self.b)[1]['consumption']['method']['release'],'alpha/method@2')

    def test_restricted_publication_and_withdrawal_prevent_new_consumption(self):
        self.publish(audience=['alpha'])
        self.assertEqual(self.call('/api/projects/beta/shared',profile=self.b)[1]['releases'],[])
        self.assertEqual(self.shared('consume',{'alias':'x','ref':'alpha/method@1','reason':'x','tests':'x'},'beta')[0],404)
        self.assertEqual(self.shared('withdraw',{'ref':'alpha/method@1','reason':'license revoked','migration':'consumers retain trace and must replace','evidence':EV})[0],201)
        self.assertEqual(self.shared('consume',{'alias':'x','ref':'alpha/method@1','reason':'x','tests':'x'})[0],409)

if __name__=='__main__':unittest.main()
