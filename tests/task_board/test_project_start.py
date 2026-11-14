"""Real HTTP and standalone CLI coverage of named-project SE bootstrap."""
import json,sys,unittest,uuid,concurrent.futures
from pathlib import Path
from unittest.mock import patch
from . import test_projects as fixture
from task_board import lifecycle
from tools.owned_process import run

class ProjectStartCase(unittest.TestCase):
    tearDown=fixture.ProjectCase.tearDown;call=fixture.ProjectCase.call
    def setUp(self):
        fixture.ProjectCase.setUp(self);self.server.settings['public_url']=self.url
    def grant(self,pid='gamma',actor='gamma-se',**kw):
        value={'request_id':uuid.uuid4().hex,'project_id':pid,'actor':actor,'ttl_seconds':3600,'reason':'User assigned a real project SE'};value.update(kw)
        code,profile,_=self.call('/api/project-grants',value,self.admin);self.assertEqual(code,201,profile);return profile,value
    def definition(self,pid='gamma'):
        value=json.loads((fixture.ROOT/'templates/project-init.json').read_text('utf8'));value.update(id=pid,name='New scoped project',description='Independent empty fixture');return value
    def create(self,profile,definition=None,rid=None):
        payload={'request_id':rid or uuid.uuid4().hex,'project':definition or self.definition(profile['project_id'])}
        return self.call('/api/projects/'+profile['project_id']+'/bootstrap',payload,profile),payload
    def test_grant_has_no_read_rights_until_creation_then_same_token_is_owner(self):
        p,_=self.grant();self.assertEqual(self.call('/api/projects',profile=p)[0],401);self.assertEqual(self.call('/api/projects/alpha/snapshot',profile=p)[0],401)
        result,request=self.create(p);self.assertEqual(result[0],201,result[1]);self.assertNotIn(p['token'],json.dumps(result[1]));self.assertTrue(result[1]['same_profile'])
        me=self.call('/api/projects/gamma/me',profile=p)[1];self.assertFalse(me['global_admin']);self.assertEqual(me['role'],'reviewer')
        projects=self.call('/api/projects',profile=p)[1]['projects'];self.assertEqual([x['id'] for x in projects],['gamma']);g=self.call('/api/projects/gamma/governance',profile=p)[1];self.assertEqual(g['members']['gamma-se']['role'],'owner');self.assertEqual(g['planning_policy']['mode'],'enforced');self.assertFalse(self.call('/api/projects/gamma/snapshot',profile=p)[1]['tasks'])
        self.assertEqual(self.call('/api/projects/gamma/worker-entry')[0],200)
        self.assertEqual(self.call('/api/projects/alpha/snapshot',profile=p)[0],404);self.assertEqual(self.call('/api/projects',self.definition('other'),p)[0],403);self.assertTrue(self.hub.verify()['passed'])
    def test_identical_retry_is_readback_and_different_definition_cannot_overwrite(self):
        p,_=self.grant();result,request=self.create(p,rid='fixed');before=self.call('/api/projects/gamma/governance',profile=p)[1]['head'];again=self.call('/api/projects/gamma/bootstrap',request,p);self.assertTrue(again[1]['replayed']);self.assertFalse(again[1]['created'])
        changed=json.loads(json.dumps(request));changed['project']['knowledge']['goals']='Different goals';self.assertEqual(self.call('/api/projects/gamma/bootstrap',changed,p)[0],409);self.assertEqual(before,self.call('/api/projects/gamma/governance',profile=p)[1]['head'])
        with patch('task_board.project_start.time.time',return_value=p['grant_expires']+100):self.assertTrue(self.call('/api/projects/gamma/bootstrap',request,p)[1]['replayed'])
    def test_bound_project_actor_and_no_existing_project_takeover(self):
        p,_=self.grant();self.assertEqual(self.call('/api/projects/beta/bootstrap',{'request_id':'wrong','project':self.definition('beta')},p)[0],404)
        result,_=self.create(p,self.definition('other'));self.assertEqual(result[0],403)
        self.hub.create(self.identity,self.definition('gamma'));result,_=self.create(p);self.assertEqual(result[0],409);self.assertEqual(self.call('/api/projects/gamma/me',profile=p)[0],401)
        self.assertEqual(self.call('/api/project-grants',{'request_id':'x','project_id':'alpha','actor':'owner','ttl_seconds':3600,'reason':'Cannot take over'},self.admin)[0],409)
    def test_only_admin_issues_and_bad_shapes_have_no_project_side_effect(self):
        params={'request_id':'x','project_id':'new-id','actor':'new-se','ttl_seconds':3600,'reason':'Bound grant'}
        for profile in [None,self.a,self.reviewer]:self.assertIn(self.call('/api/project-grants',params,profile)[0],(401,403))
        for key,value in [('actor','root'),('actor',[]),('project_id','../alpha'),('ttl_seconds',True),('ttl_seconds',604801),('reason','')]:
            bad={**params,key:value};self.assertEqual(self.call('/api/project-grants',bad,self.admin)[0],400)
        p,_=self.grant();result,_=self.create(p,{**self.definition(),'name':''},rid='fixable');self.assertEqual(result[0],400);result,_=self.create(p,rid='corrected');self.assertEqual(result[0],201)
    def test_expired_and_revoked_grants_fail_without_owner_escalation(self):
        p,_=self.grant()
        with patch('task_board.project_start.time.time',return_value=p['grant_expires']+1):self.assertEqual(self.create(p)[0][0],403)
        self.assertEqual(self.call('/api/project-grants/revoke',{'project_id':'gamma','grant_id':p['grant_id'],'reason':'Withdraw before use'},self.admin)[0],201);self.assertEqual(self.create(p)[0][0],403)
        q,_=self.grant('delta','delta-se');result,request=self.create(q);self.assertEqual(result[0],201);self.call('/api/project-grants/revoke',{'project_id':'delta','grant_id':q['grant_id'],'reason':'Retire bootstrap only'},self.admin);self.assertEqual(self.call('/api/projects/delta/me',profile=q)[0],200);self.assertEqual(self.call('/api/projects/delta/bootstrap',request,q)[0],403)
    def test_project_owner_revocation_cannot_be_undone_by_bootstrap_retry(self):
        p,_=self.grant();result,request=self.create(p);self.hub.revoke(self.identity,'gamma','gamma-se','Revoke actual owner');self.assertEqual(self.call('/api/projects/gamma/bootstrap',request,p)[0],401);self.assertEqual(self.call('/api/projects/gamma/me',profile=p)[0],401)
    def test_owner_handoff_is_not_reversed_by_the_original_creation_grant(self):
        p,_=self.grant();result,request=self.create(p);successor=self.hub.invite('gamma','successor')
        def gov(action,payload,profile):
            g=self.call('/api/projects/gamma/governance',profile=profile)[1];r=self.call('/api/projects/gamma/governance',{'request_id':uuid.uuid4().hex,'expected_revision':g['revision'],'action':action,'payload':payload},profile);self.assertEqual(r[0],201,r[1]);return r
        gov('member',{'actor':'successor','role':'se','scope':'Real fixture successor'},p);gov('handoff_propose',{'to':'successor','risks':'No active work','materials':[],'reason':'Current owner delegates project'},p);g=self.call('/api/projects/gamma/governance',profile=successor)[1];gov('handoff_accept',{'scope':g['handoff']['scope'],'summary':'Accepted current project boundaries'},successor)
        self.assertEqual(self.call('/api/projects/gamma/bootstrap',request,p)[0],403);self.assertEqual(self.call('/api/projects/gamma/governance',profile=successor)[1]['members']['successor']['role'],'owner')
    def test_partial_initialization_stays_unpublished_and_never_overwrites_files(self):
        p,_=self.grant();original=fixture.BoardStore.register_actor
        def interrupted(store,actor,role='agent',**kw):
            if kw.get('_token'):raise fixture.BoardError('Fixture interrupted before catalog publication',409)
            return original(store,actor,role,**kw)
        with patch.object(fixture.BoardStore,'register_actor',interrupted):result,request=self.create(p)
        self.assertEqual(result[0],409);path=self.state/'projects/gamma/board.sqlite';self.assertTrue(path.exists());before=path.read_bytes();self.assertEqual(self.call('/api/projects/gamma/bootstrap',request,p)[0],409);self.assertEqual(path.read_bytes(),before);self.assertEqual(self.call('/api/projects/gamma/me',profile=p)[0],401)
    def test_concurrent_identical_requests_publish_one_owner_and_project(self):
        p,_=self.grant();payload={'request_id':'concurrent','project':self.definition()}
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.call('/api/projects/gamma/bootstrap',payload,p),range(2)))
        self.assertEqual([x[0] for x in results],[201,201]);self.assertEqual(sum(x[1]['created'] for x in results),1)
        with self.hub.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM projects WHERE id='gamma'").fetchone()[0],1);self.assertEqual(db.execute("SELECT COUNT(*) FROM credentials WHERE project='gamma'").fetchone()[0],1)
    def test_issuer_replay_reuses_private_file_and_audit_contains_no_token(self):
        p,value=self.grant();again=self.call('/api/project-grants',value,self.admin);self.assertEqual(p['token'],again[1]['token']);changed={**value,'request_id':'another'};self.assertEqual(self.call('/api/project-grants',changed,self.admin)[0],409)
        with self.hub.connection() as db:payloads=''.join(x[0] for x in db.execute('SELECT payload FROM audit'))
        self.assertNotIn(p['token'],payloads);self.assertEqual(p['token'],json.loads((self.state/'_private/project-grants/gamma.json').read_text('utf8'))['token'])
    def test_standalone_client_durably_retries_same_definition_and_never_prints_token(self):
        p,_=self.grant();folder=self.state/'private-client';folder.mkdir();profile=folder/'owner.json';definition=folder/'project-init.json';receipt=folder/'receipt.json';lifecycle.write(profile,p);lifecycle.write(definition,self.definition());script=fixture.ROOT/'tools/task_board_client.py';command=[sys.executable,'-I','-B','-X','utf8',script,'--profile',profile,'create-project','--definition',definition,'--receipt',receipt]
        outputs=[]
        for _ in range(2):
            code,out,err=run(command,cwd=folder,evidence=folder/'audit',purpose='Actual standalone project creation using scoped grant',timeout=25);self.assertEqual(code,0,err.decode());self.assertNotIn(p['token'],out.decode());outputs.append(json.loads(out))
        self.assertFalse(outputs[0]['replayed']);self.assertTrue(outputs[1]['replayed']);self.assertEqual(lifecycle.read(profile)['token'],p['token']);self.assertTrue((folder/'outbox/gamma/project-create.json').exists())
        lifecycle.write(definition,{**self.definition(),'description':'Changed after success'});code,out,err=run(command,cwd=folder,evidence=folder/'audit',purpose='Reject altered frozen project creation request',timeout=25);self.assertEqual(code,2);self.assertIn('409',out.decode());self.assertNotIn(p['token'],out.decode())
    def test_client_lost_response_reuses_exact_request_and_normal_owner_cannot_issue(self):
        p,_=self.grant();profile=self.state/'owner.json';lifecycle.write(profile,p);client=fixture.portable.Client(self.url,p);original=client.call;seen=[]
        def lost(path,payload=None):
            seen.append(json.loads(json.dumps(payload)));result=original(path,payload)
            if len(seen)==1:raise fixture.portable.ClientError('Response lost')
            return result
        with patch.object(client,'call',side_effect=lost):result=client.create_project(self.definition(),profile,self.state/'receipt.json')
        self.assertTrue(result['replayed']);self.assertEqual(seen[0],seen[1]);self.assertEqual(self.call('/api/project-grants',{'request_id':'x','project_id':'omega','actor':'omega-se','ttl_seconds':3600,'reason':'Forbidden'},p)[0],403)

if __name__=='__main__':unittest.main()
