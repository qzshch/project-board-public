"""SE registration creates only a new project; no issuer or owner file needed."""
import concurrent.futures,json,secrets,sys,unittest,uuid
from unittest.mock import patch
from . import test_projects as fixture
from tools.task_board_client import Client,ClientError,create_se
from tools.owned_process import run

class SESelfServiceCase(unittest.TestCase):
    tearDown=fixture.ProjectCase.tearDown;call=fixture.ProjectCase.call
    def setUp(self):fixture.ProjectCase.setUp(self);self.server.settings['se_self_service']=True
    def definition(self,pid='gamma'):
        d=json.loads((fixture.ROOT/'templates/project-init.json').read_text('utf8'));d.update(id=pid,name='SE local project',description='No issuer fixture');d['knowledge']['entries']=[{'title':'Runtime directory','location':'G:/fixture/runtime/'},{'title':'Public project entry','location':'http://nas.example.ts.net:18785'}];return d
    def seed(self,pid='gamma'):return {'token':secrets.token_urlsafe(32),'actor':'se-'+uuid.uuid4().hex,'project_id':pid}
    def create(self,p=None,rid=None,definition=None):
        p=p or self.seed();request={'request_id':rid or uuid.uuid4().hex,'actor':p['actor'],'project':definition or self.definition(p['project_id'])};return p,request,self.call('/api/projects/'+p['project_id']+'/se-start',request,p)
    def test_enabled_registration_creates_owner_and_unknown_dynamic_entries(self):
        p,req,result=self.create();self.assertEqual(result[0],201,result[1]);self.assertTrue(result[1]['created']);self.assertNotIn(p['token'],json.dumps(result[1]));self.assertEqual([x['id'] for x in self.call('/api/projects',profile=p)[1]['projects']],['gamma']);g=self.call('/api/projects/gamma/governance',profile=p)[1];self.assertEqual(g['members'][p['actor']]['role'],'owner');self.assertTrue(g['worker_access']['enabled']);self.assertEqual(g['knowledge']['entries'][0]['sha256'],'');self.assertEqual(g['knowledge']['entries'][0]['version'],'unversioned')
        rows=self.call('/api/projects/gamma/resources',profile=p)[1]['entries'];self.assertTrue(rows);self.assertTrue(all(r['mutable'] and r['integrity']['kind']=='none' for r in rows));self.assertEqual(self.call('/api/projects/alpha/snapshot',profile=p)[0],404);self.assertEqual(self.call('/api/projects',self.definition('delta'),p)[0],403);self.assertTrue(self.hub.verify()['passed'])
    def test_default_closed_and_explicit_project_path_required(self):
        self.server.settings.pop('se_self_service');self.assertFalse(self.call('/api/se-entry')[1]['se_self_service']);self.assertEqual(self.create()[2][0],403);self.server.settings['se_self_service']=True;self.assertEqual(self.call('/api/se-entry')[1]['command'],'create-se');p=self.seed();self.assertEqual(self.call('/api/se-start',{'request_id':'x','actor':p['actor'],'project':self.definition()},p)[0],404);self.assertEqual(self.call('/api/projects')[0],401)
    def test_retry_preserves_definition_closing_factory_does_not_revoke_owner(self):
        p,req,result=self.create();self.server.settings['se_self_service']=False;again=self.call('/api/projects/gamma/se-start',req,p);self.assertEqual(again[0],201);self.assertTrue(again[1]['replayed']);bad=json.loads(json.dumps(req));bad['project']['name']='Overwrite';self.assertEqual(self.call('/api/projects/gamma/se-start',bad,p)[0],409);self.assertEqual(self.call('/api/projects/gamma/me',profile=p)[0],200)
    def test_existing_project_or_another_seed_never_gets_owner(self):
        p,req,result=self.create();q=self.seed();self.assertEqual(self.create(q)[2][0],409);existing=self.seed('alpha');self.assertEqual(self.create(existing)[2][0],409);self.assertEqual(self.call('/api/projects/alpha/me',profile=existing)[0],401)
        with self.hub.connection() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM se_starts WHERE project='gamma'").fetchone()[0],1)
    def test_revoked_and_handed_off_owner_cannot_be_restored(self):
        p,req,result=self.create();self.hub.revoke(self.identity,'gamma',p['actor'],'Revoke created owner');self.assertEqual(self.call('/api/projects/gamma/se-start',req,p)[0],401)
        q,request,result=self.create(self.seed('delta'));successor=self.hub.invite('delta','next-se')
        def gov(action,payload,profile):
            g=self.call('/api/projects/delta/governance',profile=profile)[1];result=self.call('/api/projects/delta/governance',{'request_id':uuid.uuid4().hex,'expected_revision':g['revision'],'action':action,'payload':payload},profile);self.assertEqual(result[0],201,result[1])
        gov('member',{'actor':'next-se','role':'se','scope':'Successor'},q);gov('handoff_propose',{'to':'next-se','risks':'No work','materials':[],'reason':'Transfer'},q);g=self.call('/api/projects/delta/governance',profile=successor)[1];gov('handoff_accept',{'scope':g['handoff']['scope'],'summary':'Accepted'},successor);self.assertEqual(self.call('/api/projects/delta/se-start',request,q)[0],403)
    def test_concurrent_identical_and_distinct_seeds_publish_one_owner(self):
        p=self.seed();req={'request_id':'concurrent','actor':p['actor'],'project':self.definition()}
        with concurrent.futures.ThreadPoolExecutor(2) as pool:r=list(pool.map(lambda _:self.call('/api/projects/gamma/se-start',req,p),range(2)))
        self.assertEqual([x[0] for x in r],[201,201]);self.assertEqual(sum(x[1]['created'] for x in r),1)
        one=self.seed('delta');two=self.seed('delta')
        with concurrent.futures.ThreadPoolExecutor(2) as pool:r=list(pool.map(lambda p:self.create(p)[2],[one,two]))
        self.assertEqual(sorted(x[0] for x in r),[201,409])
    def test_reserved_old_grant_blocks_until_explicit_revoke_no_identity_reuse(self):
        req={'request_id':'grant','project_id':'gamma','actor':'old-se','ttl_seconds':3600,'reason':'Existing explicit reservation'};old=self.call('/api/project-grants',req,self.admin)[1];self.assertEqual(self.create()[2][0],409);self.call('/api/project-grants/revoke',{'project_id':'gamma','grant_id':old['grant_id'],'reason':'Owner authorizes new self-service instead'},self.admin);self.assertEqual(self.create()[2][0],201)
        for p in ({'project_id':'delta','actor':'copy-se','token':self.a['token']},{'project_id':'delta','actor':'copy-se','token':old['token']},{'project_id':'delta','actor':'copy-se','token':self.admin['token']}):self.assertIn(self.create(p)[2][0],(403,409))
    def test_invalid_shapes_and_partial_directory_fail_closed(self):
        for bad in ({'token':'bad','actor':'se-one','project_id':'gamma'},{'token':secrets.token_urlsafe(32),'actor':'root','project_id':'gamma'}):self.assertIn(self.create(bad)[2][0],(400,401))
        d=self.definition();d['knowledge']['materials']=[{'title':'Must stay fixed','location':'G:/notes'}];self.assertEqual(self.create(definition=d)[2][0],400)
        d=self.definition();d['knowledge']['entries'][0]['sha256']='bad';self.assertEqual(self.create(definition=d)[2][0],400)
        original=fixture.BoardStore.register_actor
        def fail(store,actor,role='agent',**kw):
            if kw.get('_token'):raise fixture.BoardError('Fixture owner initialization failure',409)
            return original(store,actor,role,**kw)
        with patch.object(fixture.BoardStore,'register_actor',fail):p,req,result=self.create()
        self.assertEqual(result[0],409);self.assertTrue((self.state/'projects/gamma/board.sqlite').exists());self.assertEqual(self.call('/api/projects/gamma/se-start',req,p)[0],409);self.assertEqual(self.call('/api/projects/gamma/me',profile=p)[0],401)
    def test_client_no_profile_first_create_and_exact_command_replay(self):
        folder=self.state/'private-client';folder.mkdir();definition=folder/'project-init.json';definition.write_text(json.dumps(self.definition()),encoding='utf8');receipt=folder/'receipt.json';cmd=[sys.executable,'-B',fixture.ROOT/'tools/task_board_client.py','--url',self.url,'create-se','--definition',definition,'--private-dir',folder/'private','--actor','fixture-se','--receipt',receipt]
        for replay in (False,True):
            code,out,err=run(cmd,cwd=fixture.ROOT,evidence=folder/'audit',purpose='SE can create from zero without issuer or pre-existing owner file',timeout=25);self.assertEqual(code,0,(out,err));v=json.loads(out);self.assertEqual(v['replayed'],replay);p=json.loads(fixture.Path(v['owner_profile']).read_text('utf8'));self.assertNotIn(p['token'],out.decode());self.assertEqual(p['actor'],'fixture-se')
        changed=self.definition();changed['name']='New name';definition.write_text(json.dumps(changed),encoding='utf8');code,out,err=run(cmd,cwd=fixture.ROOT,evidence=folder/'audit',purpose='Frozen first-create definition cannot be silently replaced',timeout=25);self.assertEqual(code,2);self.assertEqual(json.loads(out)['status'],409)
    def test_client_lost_response_reuses_same_private_file_and_request(self):
        client=Client(self.url);original=Client.call;calls=[]
        def lost(c,path,payload=None):
            result=original(c,path,payload)
            if path.endswith('/se-start'):
                calls.append(payload)
                if len(calls)==1:raise ClientError('lost first response')
            return result
        with patch.object(Client,'call',new=lost):r=create_se(client,self.definition(),None,self.state/'private',self.state/'receipt.json')
        self.assertTrue(r['replayed']);self.assertEqual(calls[0],calls[1]);profile=json.loads(fixture.Path(r['owner_profile']).read_text('utf8'));self.assertEqual(self.call('/api/projects/gamma/me',profile=profile)[0],200)
