"""Real Git objects and HTTP permissions; no GitHub or production fixtures."""
from copy import deepcopy
import json,os,sqlite3,sys,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from . import test_governance as fixture
from task_board.git_tracking import Tracking
from task_board.git_reader import Reader
from task_board.storage_boundary import reason,ignore_template
from tools.owned_process import run


class GitCase(unittest.TestCase):
    setUp=fixture.GovernanceCase.setUp
    tearDown=fixture.GovernanceCase.tearDown
    call=fixture.GovernanceCase.call
    gov=fixture.GovernanceCase.gov
    member=fixture.GovernanceCase.member
    atomic=fixture.GovernanceCase.atomic
    event=fixture.GovernanceCase.event

    def git(self,args,cwd=None,input_data=None):
        code,out,err=run(['git',*args],cwd=cwd or self.work,evidence=self.state/'process-evidence',purpose='Owned Git tracking fixture',input_data=input_data,env={**os.environ,'GIT_CONFIG_GLOBAL':os.devnull,'GIT_CONFIG_NOSYSTEM':'1'},timeout=20)
        self.assertEqual(code,0,err.decode());return out.decode().strip()

    def action(self,action,payload,profile=None,rid=None,revision=None):
        v=self.call('/api/projects/alpha/git',profile=self.admin)[1]
        return self.call('/api/projects/alpha/git',{'request_id':rid or uuid.uuid4().hex,'expected_revision':v['revision'] if revision is None else revision,'action':action,'payload':payload},profile or self.admin)

    def query(self,endpoint,**p):
        from urllib.parse import urlencode
        return self.call('/api/projects/alpha/git/'+endpoint+'?'+urlencode({'repo':'main',**p}),profile=self.a)

    def repository(self):
        self.work=self.state/'source';self.work.mkdir();self.git(['init','--quiet','--initial-branch=main']);self.git(['config','user.name','Fixture author']);self.git(['config','user.email','fixture@example.invalid'])
        (self.work/'src').mkdir();(self.work/'src/app.py').write_text('first = 1\nsecond = 2\n',encoding='utf8');(self.work/'src/[x].txt').write_text('literal\n');(self.work/'binary.bin').write_bytes(b'\x00\x01')
        (self.work/'research').mkdir();(self.work/'research/raw.md').write_text('LOCAL PRIVATE RESEARCH MUST NOT BE SHOWN');(self.work/'logs').mkdir();(self.work/'logs/run.log').write_text('Runtime record, not code')
        self.git(['add','.']);self.git(['commit','--quiet','-m','Root <img src=x onerror=alert(1)>']);self.first=self.git(['rev-parse','HEAD'])
        self.git(['checkout','--quiet','-b','feature']);(self.work/'feature.py').write_text('feature = True\n');self.git(['add','.']);self.git(['commit','--quiet','-m','Feature']);self.feature=self.git(['rev-parse','HEAD'])
        self.git(['checkout','--quiet','main']);(self.work/'main.txt').write_text('main\n');self.git(['add','.']);self.git(['commit','--quiet','-m','Main']);self.before_merge=self.git(['rev-parse','HEAD']);self.git(['merge','--quiet','--no-ff','feature','-m','Merge feature']);self.merge=self.git(['rev-parse','HEAD'])
        self.git(['mv','src/app.py','src/main.py']);self.git(['commit','--quiet','-m','Rename preserves source lineage']);self.head=self.git(['rev-parse','HEAD']);self.git(['tag','-a','v1','-m','Version one'])
        mirror=self.state/'git-mirrors/alpha/main.git';mirror.parent.mkdir(parents=True);self.git(['clone','--quiet','--bare',str(self.work),str(mirror)])
        (mirror/'PROJECT-BOARD-MIRROR.json').write_text(json.dumps({'project':'alpha','id':'main','repository':'fixture/private'}));private=self.state/'_private';private.mkdir(exist_ok=True);(private/'fixture-key').write_text('Fixture placeholder, not a real credential')
        self.entry={'repository':'fixture/private','key':str(private/'fixture-key')};(private/'github.json').write_text(json.dumps({'projects':{'alpha':{'main':self.entry}}}))
        self.assertEqual(self.action('bind',{'id':'main','repository':'fixture/private','title':'Private fixture','reason':'Actual local Git input'})[0],201)
        refs={'refs/heads/main':self.head,'refs/heads/feature':self.feature,'refs/tags/v1':self.head}
        self.assertEqual(self.action('sync_result',{'repo':'main','repository':'fixture/private','request':1,'refs':refs,'error':'','default_branch':'refs/heads/main','alerts':[{'path':'research/raw.md','reason':'Local-only research'}],'rewritten':[]})[0],201)
        return mirror

    def test_private_binding_immutable_id_chain_idempotence_and_role_boundaries(self):
        p={'id':'main','repository':'fixture/private','title':'one','reason':'SE reviewed read-only code tracking'};rid=uuid.uuid4().hex
        r=self.action('bind',p,rid=rid,revision=0);self.assertEqual(r[0],201);self.assertTrue(self.action('bind',p,rid=rid,revision=0)[1]['replayed'])
        self.assertEqual(self.action('bind',{**p,'title':'different'},rid=rid,revision=0)[0],409);self.assertEqual(self.action('bind',p)[0],409)
        self.assertEqual(self.action('bind',{**p,'id':'other','repository':'https://user:secret@github.com/a/b'})[0],400)
        self.assertEqual(self.action('bind',{**p,'id':'other'},profile=self.a)[0],403)
        for endpoint in ('git','git/verify','git/log?repo=main','git/commit?repo=main&commit='+'a'*40,'git/patch?repo=main','git/blame?repo=main','git/tree?repo=main','git/compare?repo=main'):
            r=self.call('/api/projects/alpha/'+endpoint,profile=self.b);self.assertEqual(r[0],404);self.assertNotIn('fixture',json.dumps(r[1]));self.assertNotIn('ETag',r[2])
        self.assertTrue(Tracking(self.hub.store('alpha')).verify()['passed'])
        with self.hub.store('alpha').connection() as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM git_events')
        self.assertEqual(self.call('/api/projects/alpha/git/log?repo=main',profile=self.admin)[0],409)

    def test_actual_commit_graph_merge_stats_patch_and_fixed_version_compare(self):
        self.repository();r=self.query('log',ref='refs/heads/main');self.assertEqual(r[0],200,r[1]);commits=r[1]['commits'];self.assertEqual(commits[0]['sha'],self.head)
        merge=next(c for c in commits if c['sha']==self.merge);self.assertEqual(set(merge['parents']),{self.before_merge,self.feature})
        details=self.query('commit',commit=self.first);self.assertEqual(details[0],200,details[1]);self.assertIn('research/raw.md',[f['path'] for f in details[1]['files']]);self.assertEqual(details[1]['subject'],'Root <img src=x onerror=alert(1)>')
        diff=self.query('patch',base=self.before_merge,head=self.merge,path='feature.py');self.assertEqual(diff[0],200);self.assertIn('+feature = True',diff[1]['patch'])
        cmp=self.query('compare',base=self.before_merge,head=self.merge);self.assertEqual([f['path'] for f in cmp[1]['files']],['feature.py'])
        root=self.query('patch',base='',head=self.first,path='src/[x].txt');self.assertEqual(root[0],200);self.assertIn('+literal',root[1]['patch'])
        self.assertEqual(self.query('log',ref=self.head,author='Fixture author',q='Rename')[1]['commits'][0]['sha'],self.head)

    def test_file_history_rename_blame_binary_and_path_injection(self):
        self.repository();history=self.query('log',ref=self.head,path='src/main.py');self.assertEqual(history[0],200,history[1]);self.assertEqual([c['sha'] for c in history[1]['commits']],[self.head,self.first])
        blame=self.query('blame',head=self.head,path='src/main.py');self.assertEqual(blame[0],200,blame[1]);self.assertEqual({r['sha'] for r in blame[1]['lines']},{self.first});self.assertEqual(blame[1]['lines'][0]['text'],'first = 1')
        self.assertEqual(self.query('blame',head=self.head,path='binary.bin')[0],400)
        self.assertEqual(self.query('patch',head=self.head,path='../state/.env')[0],400)
        self.assertEqual(self.query('log',ref='--all')[0],400);self.assertEqual(self.query('log',ref=self.head,offset=-1)[0],400)
        self.assertEqual(self.query('patch',head=self.head,path=':(glob)**')[0],400)
        self.assertEqual(self.query('commit',commit='b'*40)[0],404)
        tree=self.query('tree',head=self.head,path='src');self.assertEqual(tree[0],200);self.assertTrue(all(f['path'].startswith('src/') for f in tree[1]['files']))

    def test_local_only_paths_never_expose_body_and_policy_exceptions_are_explicit(self):
        self.repository()
        for endpoint in ('patch','blame','log'):
            r=self.query(endpoint,head=self.head,ref=self.head,path='research/raw.md');self.assertEqual(r[0],403,r[1]);self.assertNotIn('PRIVATE RESEARCH',json.dumps(r[1]))
        self.assertEqual(self.query('patch',head=self.first,path='logs/run.log')[0],403)
        self.assertEqual(self.action('policy',{'patterns':['src/*.py'],'exceptions':{},'reason':'Project reviewed path boundary'})[0],201)
        self.assertEqual(self.query('blame',head=self.head,path='src/main.py')[0],403)
        self.assertEqual(self.action('policy',{'patterns':['src/*.py'],'exceptions':{'src/main.py':'Explicit reviewed source code'},'reason':'This is implementation, not local data'})[0],201)
        self.assertEqual(self.query('blame',head=self.head,path='src/main.py')[0],200)
        for path in ('cache/a','research/raw.md','archives/old.zip','art-assets/source.psd','assets/source.svg','test-results/report.json','logs/run.log','runtime/data.bin','state/a','evidence/report.json','portrait.png','run.jsonl'):
            self.assertIsNotNone(reason(path),path)
        self.assertIsNotNone(reason('runtime/a',exceptions={'runtime/a':'Cannot waive runtime boundary'}));self.assertIsNone(reason('tests/test_math.py'));self.assertIsNone(reason('docs/OWNER-GUIDE.md'))
        (self.work/'.gitignore').write_text(ignore_template());self.git(['rm','--cached','research/raw.md','logs/run.log'])
        self.assertIn('research/raw.md',self.git(['check-ignore','research/raw.md']))
        self.assertTrue((self.work/'research/raw.md').exists(),'Untracking must not delete local data')

    def test_task_scope_associations_are_project_local_and_never_auto_accept(self):
        self.repository();self.atomic();task=self.hub.store('alpha').get('new/one')
        brief=self.call('/api/projects/alpha/brief?task=new/one',profile=self.a)[1]
        self.assertEqual(brief['git']['repositories'][0]['repository'],'fixture/private');self.assertNotIn('fixture-key',json.dumps(brief))
        self.assertEqual(self.action('link',{'repo':'main','commit':self.head,'task':'new/one','scope':task['scope_hash'],'reason':'Actual implementation related to this current atom'})[0],201)
        c=self.query('commit',commit=self.head)[1];self.assertEqual(c['relations']['tasks'][0]['id'],'new/one');self.assertTrue(c['relations']['tasks'][0]['explicit'][0]['current']);self.assertEqual(self.hub.store('alpha').get('new/one')['status'],'planned')
        spec=deepcopy(task['spec']);spec['description']='Scope changed';self.assertEqual(self.event('new/one','scope',{'spec':spec,'reason':'SE expanded actual boundary'},self.admin)[0],201)
        self.assertFalse(self.query('commit',commit=self.head)[1]['relations']['tasks'][0]['explicit'][0]['current'])
        self.assertEqual(self.action('enable',{'repo':'main','enabled':False,'reason':'Revoke project code visibility'})[0],201);self.assertEqual(self.query('commit',commit=self.head)[0],404)

    def test_tracker_can_report_verified_objects_but_cannot_manage_or_develop(self):
        self.repository();self.member(role='tracker')
        self.assertEqual(self.action('bind',{'id':'other','repository':'fixture/other','title':'x','reason':'x'},profile=self.a)[0],403)
        self.assertEqual(self.gov('decision',{'summary':'No','reason':'No','evidence':[]},profile=self.a)[0],403)
        self.atomic();self.assertEqual(self.event('new/one','claim',{'summary':'Cannot be a developer'},self.a)[0],403)
        v=self.call('/api/projects/alpha/operations',profile=self.a)[1]
        self.assertEqual(self.call('/api/projects/alpha/operations',{'request_id':uuid.uuid4().hex,'expected_revision':v['revision'],'action':'policy','payload':{'profile':'light','reason':'Cannot manage'}},self.a)[0],403)
        p={'repo':'main','repository':'fixture/private','request':1,'refs':{'refs/heads/main':self.head},'error':'','default_branch':'refs/heads/main','alerts':[],'rewritten':[]}
        self.assertEqual(self.action('sync_result',p,profile=self.a)[0],201);self.assertEqual(self.action('sync_result',{**p,'refs':{'refs/heads/main':'f'*40}},profile=self.a)[0],404)

    def test_failed_fetch_preserves_verified_refs_and_records_failure(self):
        self.repository();from tools.github_tracker import synchronize
        t=Tracking(self.hub.store('alpha'));actor=self.hub.store('alpha').authenticate(self.reviewer['token']);before=t.state()['repos']['main']['refs']
        with patch('tools.github_tracker.run_git',return_value=(1,b'',b'Network unavailable')):synchronize(t,actor,'main',self.entry)
        after=t.state()['repos']['main'];self.assertEqual(after['refs'],before);self.assertIn('同步失败',after['sync_error']);self.assertTrue(after['synced_at']);self.assertTrue(t.verify()['passed'])
        revision=t.state()['revision']
        with patch('tools.github_tracker.run_git',return_value=(1,b'',b'Network unavailable')):synchronize(t,actor,'main',self.entry)
        self.assertEqual(t.state()['revision'],revision,'Unchanged polling must not grow immutable snapshots each minute');self.assertTrue(t.state()['repos']['main']['last_check']['at'])

    def test_index_checker_rejects_tracked_records_without_upload_or_file_deletion(self):
        self.repository();out=self.state/'boundary/result.json';tool=Path(__file__).resolve().parents[2]/'tools/check_git_boundary.py'
        code,_,_=run([sys.executable,'-B',str(tool),'--repo',str(self.work),'--out',str(out)],cwd=self.work,evidence=self.state/'process-evidence',purpose='Actual local source boundary checker',timeout=20)
        self.assertEqual(code,1);data=json.loads(out.read_text());self.assertFalse(data['passed']);self.assertIn('logs/run.log',[p['path'] for p in data['violations']]);self.assertTrue((self.work/'logs/run.log').exists())

    def test_pagination_pins_input_and_nonfastforward_is_recorded(self):
        mirror=self.repository();tree=self.git(['rev-parse','HEAD^{tree}']);head=self.head
        for i in range(51):head=self.git(['commit-tree',tree,'-p',head,'-m','Page '+str(i)])
        self.git(['update-ref','refs/heads/pagination',head]);self.git(['--git-dir='+str(mirror),'fetch','--quiet',str(self.work),head]);self.git(['--git-dir='+str(mirror),'update-ref','refs/heads/main',head])
        v=self.call('/api/projects/alpha/git',profile=self.admin)[1];p={'repo':'main','repository':'fixture/private','request':1,'refs':{'refs/heads/main':head},'error':'','default_branch':'refs/heads/main','alerts':[],'rewritten':[]};self.assertEqual(self.action('sync_result',p)[0],201)
        page=self.query('log',ref=head)[1];self.assertEqual(len(page['commits']),50);self.assertEqual(page['next'],50)
        second=self.query('log',ref=head,offset=50)[1];self.assertTrue(second['commits']);self.assertFalse(set(c['sha'] for c in page['commits']) & set(c['sha'] for c in second['commits']))
        self.git(['--git-dir='+str(mirror),'update-ref','refs/heads/main',self.first])
        from tools.github_tracker import synchronize
        def fake_fetch(args,**_):return (0,b'ref: refs/heads/main\tHEAD\n' if 'ls-remote' in args else b'',b'')
        tracking=Tracking(self.hub.store('alpha'));actor=self.hub.store('alpha').authenticate(self.reviewer['token'])
        with patch('tools.github_tracker.run_git',side_effect=fake_fetch):synchronize(tracking,actor,'main',self.entry)
        self.assertEqual(tracking.state()['repos']['main']['history'][-1]['rewritten'],['refs/heads/main'])
        self.assertEqual(self.query('log',ref=head,offset=50)[1]['commits'],second['commits'])
