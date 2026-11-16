"""Actual scoped HTTP boundaries and SE-local GitHub credential separation."""
import io,json,subprocess,unittest,zipfile
from unittest.mock import patch
from . import test_workflow as w
from task_board.git_onboarding import Onboarding
from task_board.help import github_kit
from tools.github_connect import connect,GitHub
from tools.task_board_client import Client,ClientError

IDENTITY=(1,b'',b"Hi example/project! You've successfully authenticated, but GitHub does not provide shell access.\n")
READ=(0,b'0000',b'')
READONLY=(1,b'',b'ERROR: The key you are authenticating with has been marked as read only.\n')

class GitHubLocalCase(unittest.TestCase):
    setUp=w.WorkflowCase.setUp;tearDown=w.WorkflowCase.tearDown
    call=w.WorkflowCase.call;action=w.WorkflowCase.action
    gov=w.WorkflowCase.gov
    def key(self):
        self.action('bind',{'id':'main','repository':'example/project','title':'Code','reason':'Approved code'})
        code,state,_=self.call('/api/projects/alpha/git-onboarding/request',{'repo':'main'},self.admin);self.assertEqual(code,201,state)
        self.payload={'repo':'main','repository':'example/project','public_key':state['public_key']};return state
    def complete(self):return self.call('/api/projects/alpha/git-onboarding/complete',self.payload,self.admin)
    def test_complete_independent_protocol_verification_and_idempotence(self):
        self.key()
        with patch('tools.owned_process.run',side_effect=[IDENTITY,READ,READONLY]*2) as run,patch.object(Onboarding,'sync',return_value={'stage':'ready'}):
            self.assertEqual(self.complete()[0],201);self.assertEqual(self.complete()[0],201)
        config=json.loads((self.state/'_private/github.json').read_text());entry=config['projects']['alpha']['main'];self.assertEqual(entry['repository'],'example/project')
        self.assertEqual(run.call_count,6)
        for args,kw in run.call_args_list:
            self.assertEqual(kw['input_data'],b'');self.assertIn('StrictHostKeyChecking=yes',args[0]);self.assertIn('IdentityAgent=none',args[0])
        status=self.call('/api/projects/alpha/git-onboarding?repo=main',profile=self.admin)[1];self.assertTrue(status['read_only']);self.assertNotIn('key',status)
    def test_no_client_receipt_or_foreign_key_or_repository_is_authority(self):
        self.key()
        with patch('tools.owned_process.run') as run:
            self.payload['read_only']=True;self.assertEqual(self.complete()[0],400);self.payload.pop('read_only')
            self.payload['repository']='other/project';self.assertEqual(self.complete()[0],409);self.payload['repository']='example/project'
            self.payload['public_key']='ssh-ed25519 unregistered';self.assertEqual(self.complete()[0],409);run.assert_not_called()
    def test_worker_and_foreign_project_cannot_complete(self):
        self.key();path='/api/projects/alpha/git-onboarding/complete'
        self.assertEqual(self.call(path,self.payload,self.a)[0],403);self.assertEqual(self.call(path,self.payload,self.b)[0],404)
    def test_project_se_completes_without_global_identity(self):
        self.key();se=self.hub.invite('alpha','project-se');self.gov('member',{'actor':'project-se','role':'se','scope':'Manage this project only'})
        with patch('tools.owned_process.run',side_effect=[IDENTITY,READ,READONLY]),patch.object(Onboarding,'sync',return_value={'stage':'ready'}):
            self.assertEqual(self.call('/api/projects/alpha/git-onboarding/complete',self.payload,se)[0],201)
    def test_writable_key_network_error_and_generic_permission_denial_reject(self):
        self.key()
        for response in [(0,b'0012refs advertisement',b''),(255,b'',b'network error'),(1,b'',b'Permission denied (publickey).')]:
            with self.subTest(response=response),patch('tools.owned_process.run',side_effect=[IDENTITY,READ,response]),patch.object(Onboarding,'sync') as sync:
                self.assertEqual(self.complete()[0],409);sync.assert_not_called();self.assertFalse((self.state/'_private/github.json').exists())
    def test_wrong_repository_identity_and_read_failure_do_not_pass(self):
        self.key()
        for responses in [[(1,b'',b'Hi other/project! authentication successful')],[IDENTITY,(255,b'',b'Connection refused')]]:
            with patch('tools.owned_process.run',side_effect=responses):self.assertEqual(self.complete()[0],409)
        self.assertFalse((self.state/'_private/github.json').exists())
    def test_probe_timeout_keeps_prior_config_and_reports_unknown(self):
        self.key();cfg=self.state/'_private/github.json';cfg.write_text(json.dumps({'projects':{'another':{'preserved':True}}}));before=cfg.read_bytes()
        with patch('tools.owned_process.run',side_effect=subprocess.TimeoutExpired('ssh',30)):self.assertEqual(self.complete()[0],502)
        self.assertEqual(cfg.read_bytes(),before)
    def test_failed_reverification_cannot_be_hidden_by_read_sync(self):
        self.key()
        with patch('tools.owned_process.run',side_effect=[IDENTITY,READ,READONLY]),patch.object(Onboarding,'sync',return_value={'stage':'ready'}):self.assertEqual(self.complete()[0],201)
        with patch('tools.owned_process.run',side_effect=[IDENTITY,READ,(0,b'write allowed',b'')]):self.assertEqual(self.complete()[0],409)
        self.assertEqual(self.call('/api/projects/alpha/git-onboarding/sync',{'repo':'main'},self.admin)[0],409)
        status=self.call('/api/projects/alpha/git-onboarding?repo=main',profile=self.admin)[1];self.assertEqual(status['stage'],'verification_failed')
    def test_stopped_repo_during_external_probe_cannot_be_enabled(self):
        self.key();seen=[]
        def probe(*a,**kw):
            result=[IDENTITY,READ,READONLY][len(seen)];seen.append(1)
            if len(seen)==3:self.action('enable',{'repo':'main','enabled':False,'reason':'SE stopped during verification'})
            return result
        with patch('tools.owned_process.run',side_effect=probe):self.assertEqual(self.complete()[0],409)
        self.assertFalse((self.state/'_private/github.json').exists())
    def test_local_git_credential_is_not_sent_to_board_and_retry_reuses_key(self):
        state=self.key();client=Client(self.url,{**self.admin,'url':self.url,'project_id':'alpha'});sent=[];original=client.call;api_calls=[]
        def board(path,payload=None,**kw):
            sent.append((path,payload));return original(path,payload,**kw)
        client.call=board
        def api(self,method,path,body=None):
            api_calls.append((method,path,body))
            if path=='/repos/example/project':return {'full_name':'example/project'}
            if '/keys?' in path:return [{'id':7,'key':state['public_key'],'read_only':True}]
            return {'id':7,'key':state['public_key'],'read_only':True}
        def local_command(*a,**kw):return 0,b'username=owner\npassword=secret-sentinel-never-on-NAS\n',b''
        with patch('tools.github_connect.shutil.which',return_value=None),patch('tools.github_connect.run',side_effect=local_command),patch.object(GitHub,'call',api),patch('tools.owned_process.run',side_effect=[IDENTITY,READ,READONLY]),patch.object(Onboarding,'sync',return_value={'stage':'ready','read_only':True}):
            result=connect(client,'main',self.state/'local-connect')
        self.assertEqual(result['stage'],'ready');self.assertFalse(result['github_credential_sent_to_NAS']);self.assertNotIn('secret-sentinel',json.dumps(sent));self.assertNotIn('secret-sentinel',(self.state/'local-connect/github-connect-receipt.json').read_text());self.assertFalse(any(x[0]=='POST' for x in api_calls))
    def test_local_gh_registration_uses_readonly_and_no_secret_body(self):
        state=self.key();client=Client(self.url,{**self.admin,'url':self.url,'project_id':'alpha'});created=[]
        def api(self,method,path,body=None):
            if method=='POST':created.append(body)
            if path=='/repos/example/project':return {'full_name':'example/project'}
            if '/keys?' in path:return []
            return {'id':7,'key':state['public_key'],'read_only':True}
        with patch.object(GitHub,'select'),patch.object(GitHub,'call',api),patch('tools.owned_process.run',side_effect=[IDENTITY,READ,READONLY]),patch.object(Onboarding,'sync',return_value={'stage':'ready','read_only':True}):connect(client,'main',self.state/'local-connect')
        self.assertEqual(created,[{'title':'project-board alpha main','key':state['public_key'],'read_only':True}])
    def test_local_existing_writable_key_refused_without_mutation(self):
        state=self.key();client=Client(self.url,{**self.admin,'url':self.url,'project_id':'alpha'})
        def api(self,method,path,body=None):return {'full_name':'example/project'} if path=='/repos/example/project' else [{'id':7,'key':state['public_key'],'read_only':False}]
        with patch.object(GitHub,'select'),patch.object(GitHub,'call',api),self.assertRaises(ClientError):connect(client,'main',self.state/'local-connect')
        self.assertFalse((self.state/'_private/github.json').exists())
    def test_gh_transport_uses_existing_login_and_public_key_input_only(self):
        state=self.key();client=Client(self.url,{**self.admin,'url':self.url,'project_id':'alpha'});commands=[]
        def command(args,**kw):
            commands.append((args,kw))
            if args[-1]=='/user':body={'login':'existing-user'}
            elif args[-1]=='/repos/example/project':body={'full_name':'example/project'}
            elif '/keys?' in args[-1]:body=[]
            else:body={'id':7,'key':state['public_key'],'read_only':True}
            return 0,json.dumps(body).encode(),b''
        with patch('tools.github_connect.shutil.which',return_value='gh'),patch('tools.github_connect.run',side_effect=command),patch('tools.owned_process.run',side_effect=[IDENTITY,READ,READONLY]),patch.object(Onboarding,'sync',return_value={'stage':'ready','read_only':True}):connect(client,'main',self.state/'local-connect')
        post=next(kw for args,kw in commands if 'POST' in args);self.assertTrue(json.loads(post['input_data'])['read_only']);self.assertTrue(all(args[0]=='gh' for args,kw in commands));self.assertTrue(all('GH_DEBUG' not in kw['env'] for args,kw in commands))
    def test_downloadable_kit_has_only_reviewed_sources_and_manifest(self):
        with zipfile.ZipFile(io.BytesIO(github_kit())) as z:
            self.assertIn('tools/github_connect.py',z.namelist());self.assertFalse(any('_private' in n or n.endswith('profile.json') for n in z.namelist()));manifest=json.loads(z.read('MANIFEST.json'))
            import hashlib
            for n,h in manifest.items():self.assertEqual(hashlib.sha256(z.read(n)).hexdigest(),h)
        from urllib.request import build_opener,ProxyHandler
        with build_opener(ProxyHandler({})).open(self.url+'/github-kit.zip',timeout=5) as response:
            self.assertEqual(response.status,200);self.assertEqual(response.headers['Content-Type'],'application/zip');self.assertEqual(response.read(),github_kit())
