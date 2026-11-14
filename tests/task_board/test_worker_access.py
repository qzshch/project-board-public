"""Self-enrollment through real HTTP, claim races and ordinary delivery."""
import concurrent.futures,json,os,secrets,sys,unittest,uuid
from unittest.mock import patch
from . import test_projects as fixture
from . import test_governance as governance_fixture
from task_board.governance import Governance
from tools.task_board_client import Client,ClientError,join_worker
from tools.owned_process import run

class WorkerAccessCase(unittest.TestCase):
    setUp=fixture.ProjectCase.setUp;tearDown=fixture.ProjectCase.tearDown;call=fixture.ProjectCase.call
    gov=governance_fixture.GovernanceCase.gov;atomic=governance_fixture.GovernanceCase.atomic;event=governance_fixture.GovernanceCase.event
    def open(self,enabled=True):
        result=self.gov('worker_access',{'enabled':enabled,'reason':'Owner authorizes this project task pool'});self.assertEqual(result[0],201,result[1])
    def seed(self,pid='alpha',actor=None):
        return {'project_id':pid,'actor':actor or 'worker-'+uuid.uuid4().hex,'token':'worker.'+pid+'.'+secrets.token_urlsafe(32)}
    def join(self,p=None,rid=None):
        p=p or self.seed();request={'actor':p['actor'],'request_id':rid or uuid.uuid4().hex}
        return p,request,self.call('/api/projects/'+p['project_id']+'/worker-join',request,p)
    def worker(self):
        p,_,result=self.join();self.assertEqual(result[0],201,result[1]);return p
    def test_closed_default_and_project_only_public_entry(self):
        self.assertEqual(self.call('/api/projects/alpha/worker-entry')[0],404);self.assertEqual(self.join()[2][0],404)
        self.open();entry=self.call('/api/projects/alpha/worker-entry');self.assertEqual(entry[0],200);self.assertTrue(entry[1]['worker_self_service']);self.assertNotIn('confidential',json.dumps(entry[1]));self.assertNotIn('beta',json.dumps(entry[1]));self.assertEqual(self.call('/api/projects')[0],401);self.assertEqual(self.call('/api/projects/beta/worker-entry')[0],404)
    def test_self_join_claim_developer_and_deliver_without_se_identity_file(self):
        self.open();p=self.worker();self.atomic('work/one')
        tasks=self.call('/api/projects/alpha/convergence',profile=p)[1]['workbench']['claimable'];self.assertIn('work/one',[t['id'] for t in tasks]);self.assertFalse(next(t['blockers'] for t in tasks if t['id']=='work/one'))
        self.assertEqual(self.event('work/one','claim',{'summary':'Read project scope and current brief'},p)[0],201)
        payload={'summary':'Fixture output completed','completeness':'full','deliverable_ids':['D1'],'implementation_commit':'c'*40,'evidence':governance_fixture.EV,'tests':'Fixture actual delivery API accepted; no production test claim','remaining':'none','addresses':[]}
        result=self.event('work/one','submit',payload,p);self.assertEqual(result[0],201,result[1]);self.assertEqual(self.hub.store('alpha').get('work/one')['status'],'submitted');self.assertTrue(Governance(self.hub.store('alpha')).verify()['passed']);self.assertNotIn(p['token'],json.dumps(result[1]))
    def test_worker_executes_research_but_not_se_reserved_tasks(self):
        self.open();p=self.worker();self.atomic('research/one',paths=['research/'],category='research',role='researcher');self.atomic('se/one',paths=['planning/'],role='se')
        self.assertEqual(self.event('research/one','claim',{'summary':'Take research'},p)[0],201);self.assertEqual(self.event('se/one','claim',{'summary':'Cannot take manager task'},p)[0],409)
        spec=self.atomic('held/one',paths=['held/']);spec['claimable']=False;self.assertEqual(self.event('held/one','scope',{'spec':spec,'reason':'SE retained'},self.admin)[0],201);self.assertEqual(self.event('held/one','claim',{'summary':'Cannot take retained'},p)[0],403)
    def test_unknown_inputs_dependency_and_path_conflict_still_block(self):
        self.open();p=self.worker();q=self.worker();self.atomic('unknown/one',inputs_known=False);self.assertEqual(self.event('unknown/one','claim',{'summary':'Unknown'},p)[0],409)
        self.atomic('work/one',['src/shared/']);self.atomic('work/two',['src/shared/x.py']);self.assertEqual(self.event('work/one','claim',{'summary':'Take'},p)[0],201);self.assertEqual(self.event('work/two','claim',{'summary':'Conflict'},q)[0],409)
        spec=self.atomic('dep/one',['dep/']);spec['depends_on']=['work/one'];self.assertEqual(self.event('dep/one','scope',{'spec':spec,'reason':'Hard prerequisite'},self.admin)[0],201);self.assertEqual(self.event('dep/one','claim',{'summary':'Not accepted yet'},q)[0],409)
    def test_cross_project_all_surfaces_and_prefix_tamper_fail(self):
        self.open();p=self.worker()
        self.assertEqual([x['id'] for x in self.call('/api/projects',profile=p)[1]['projects']],['alpha'])
        for endpoint in ('snapshot','governance','graph','operations','convergence','history','search?q=private','brief?task=plan/same'):
            result=self.call('/api/projects/beta/'+endpoint,profile=p);self.assertEqual(result[0],404,(endpoint,result));self.assertNotIn('confidential',json.dumps(result[1]))
        tampered={**p,'token':p['token'].replace('worker.alpha.','worker.beta.')};self.assertEqual(self.call('/api/projects/beta/snapshot',profile=tampered)[0],401)
        self.assertEqual(self.gov('worker_access',{'enabled':False,'reason':'Worker cannot manage'},profile=p)[0],403);self.assertEqual(self.call('/api/projects',{'id':'other','name':'Other','description':'No global creation'},p)[0],403)
        self.assertEqual(self.call('/api/projects/alpha/actors',{'actor':'new-se','role':'reviewer'},p)[0],403)
    def test_request_validation_does_not_override_any_existing_role(self):
        self.open();p=self.seed();req={'actor':p['actor'],'request_id':'join'}
        self.assertEqual(self.call('/api/projects/alpha/worker-join',{**req,'role':'owner'},p)[0],400)
        for actor in ('root','same-agent','alpha-reviewer',[], 'worker-../other'):
            self.assertEqual(self.call('/api/projects/alpha/worker-join',{**req,'actor':actor},p)[0],400)
        self.hub.store('alpha').register_actor(p['actor'],'reviewer');self.assertEqual(self.call('/api/projects/alpha/worker-join',req,p)[0],409)
    def test_join_retry_is_idempotent_closed_policy_and_revocation_are_preserved(self):
        self.open();p,req,result=self.join();self.assertEqual(result[0],201);head=Governance(self.hub.store('alpha')).snapshot()['head'];self.assertTrue(self.call('/api/projects/alpha/worker-join',req,p)[1]['replayed']);self.assertEqual(head,Governance(self.hub.store('alpha')).snapshot()['head'])
        self.assertEqual(self.call('/api/projects/alpha/worker-join',{**req,'request_id':'changed'},p)[0],409);self.open(False);self.assertTrue(self.call('/api/projects/alpha/worker-join',req,p)[1]['replayed']);self.assertEqual(self.join()[2][0],404);self.assertEqual(self.call('/api/projects/alpha/snapshot',profile=p)[0],200)
        self.hub.revoke(self.identity,'alpha',p['actor'],'Owner revokes Worker');self.assertEqual(self.call('/api/projects/alpha/worker-join',req,p)[0],401);self.assertEqual(self.call('/api/projects/alpha/snapshot',profile=p)[0],401)
    def test_same_join_race_and_same_task_claim_have_single_winner(self):
        self.open();p=self.seed();req={'actor':p['actor'],'request_id':'same'}
        with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:self.call('/api/projects/alpha/worker-join',req,p),range(2)))
        self.assertEqual([x[0] for x in results],[201,201]);self.assertEqual(sum(not x[1]['replayed'] for x in results),1)
        self.atomic('race/one');q=self.worker();task=self.hub.store('alpha').get('race/one');event={'request_id':'race','task_id':'race/one','action':'claim','expected_revision':task['revision'],'scope_version':task['scope_version'],'payload':{'summary':'Race'}}
        with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda actor:self.call('/api/projects/alpha/events',event,actor),[p,q]))
        self.assertEqual(sorted(x[0] for x in results),[201,409])
    def test_join_transaction_failure_rolls_back_actor_membership_and_receipt(self):
        self.open();p=self.seed()
        with patch('task_board.convergence.gov_append',side_effect=RuntimeError('fixture interruption')):
            with self.assertRaises(RuntimeError):
                from task_board.worker_access import join
                join(self.hub,'alpha',p['token'],{'request_id':'atomic','actor':p['actor']})
        with self.hub.store('alpha').connection() as db:self.assertIsNone(db.execute('SELECT id FROM actors WHERE id=?',(p['actor'],)).fetchone());self.assertEqual(db.execute('SELECT COUNT(*) FROM worker_joins').fetchone()[0],0)
    def test_standalone_client_creates_unique_private_profiles_and_resumes_without_owner_file(self):
        self.open();folder=self.state/'client-private';audit=self.state/'client-audit'
        cmd=[sys.executable,'-B',fixture.ROOT/'tools/task_board_client.py','--url',self.url,'--project','alpha','join-worker','--private-dir',folder]
        profiles=[]
        for _ in range(2):
            code,out,err=run(cmd,cwd=fixture.ROOT,evidence=audit,purpose='standalone self-service Worker onboarding',timeout=20);self.assertEqual(code,0,(out,err));v=json.loads(out);path=fixture.Path(v['profile']);p=json.loads(path.read_text('utf8'));profiles.append(path);self.assertNotIn(p['token'],out.decode());self.assertEqual(v['project_role'],'worker')
        self.assertNotEqual(profiles[0],profiles[1]);code,out,err=run([sys.executable,'-B',fixture.ROOT/'tools/task_board_client.py','--profile',profiles[0],'join-worker'],cwd=fixture.ROOT,evidence=audit,purpose='resume original Worker identity',timeout=20);self.assertEqual(code,0,(out,err));self.assertTrue(json.loads(out)['replayed'])
    def test_client_lost_response_keeps_same_seed_and_request(self):
        self.open();client=Client(self.url,project='alpha');original=client.call;calls=[]
        def lost(path,payload):
            result=original(path,payload);calls.append(payload)
            if len(calls)==1:raise ClientError('lost response')
            return result
        with patch.object(client,'call',side_effect=lost):result=join_worker(client,private_dir=self.state/'private')
        self.assertTrue(result['replayed']);self.assertEqual(calls[0],calls[1]);self.assertEqual(self.call('/api/projects/alpha/me',profile=client.profile)[0],200)
