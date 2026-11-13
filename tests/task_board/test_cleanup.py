import json
from pathlib import Path
import tempfile
import unittest
import uuid
from task_board import lifecycle
from task_board.projects import ProjectHub
from task_board.governance import Governance
from task_board.store import BoardError
from tools.cleanup_rehearsal import cleanup

class CleanupCase(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[2]/'evidence/cleanup-fixtures';root.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=root);self.state=Path(self.tmp.name)
        lifecycle.init_state(self.state,public_url='http://127.0.0.1:24999',port=24999)
        self.hub=ProjectHub(self.state);self.identity=self.hub.resolve(lifecycle.read(self.state/'_private/admin.json')['token'])
        for p in ('task-board','real-project','onboarding-20261113-000000'):self.hub.create(self.identity,{'id':p,'name':p,'description':'fixture'},legacy_import=True)
        self.demo='onboarding-20261113-000000';self.profile=self.hub.invite(self.demo,'demo-agent')
        self.manifest={'projects':[self.hub.metadata(self.demo)],'reason':'explicit user cleanup of this bounded rehearsal'}
    def tearDown(self):self.tmp.cleanup()
    def test_cleanup_removes_live_grants_files_and_visibility_without_rewriting_real_chains(self):
        before={p:self.hub.store(p).head() for p in ('task-board','real-project')}
        store=self.hub.store('task-board');g=Governance(store);root=self.identity['actor']
        g.apply(root,{'request_id':uuid.uuid4().hex,'expected_revision':g.snapshot()['revision'],'action':'asset','payload':{'id':'brief-method-20261113-000000','version':'1','kind':'methodology','source':'independent fixture','license':'internal approved','sensitivity':'public','sha256':'b'*64,'location':'fixture','owner':'root','shareable':True,'evidence':[{'path':'fixture','sha256':'b'*64}]}})
        ref='task-board/brief-method-20261113-000000@1'
        store.registry.apply(root,{'request_id':uuid.uuid4().hex,'action':'publish','payload':{'asset':'brief-method-20261113-000000@1','audience':[self.demo],'shared_location':'explicit fixture','review':'fixture review','evidence':[{'path':'fixture','sha256':'b'*64}]}})
        result=cleanup(self.state,self.manifest)
        self.assertTrue(result['passed']);self.assertEqual(result['preserved_heads'],before)
        self.assertFalse((self.state/'projects'/self.demo).exists())
        with self.assertRaises(BoardError):ProjectHub(self.state).resolve(self.profile['token'])
        with self.assertRaises(BoardError):self.hub.metadata(self.demo)
        with self.assertRaises(BoardError):store.registry.get(ref,'task-board',True)
        self.assertEqual(Governance(store).snapshot()['assets'],{})
        self.assertTrue(g.verify()['passed']);self.assertTrue(self.hub.verify()['passed'])
        with self.assertRaises(BoardError):self.hub.create(self.identity,{'id':self.demo,'name':'reuse','description':'must reject immutable retired ID'})
    def test_manifest_cannot_remove_unrelated_real_project(self):
        self.manifest['projects']=[self.hub.metadata('real-project')]
        with self.assertRaises(BoardError):cleanup(self.state,self.manifest)
        self.assertEqual(self.hub.metadata('real-project')['id'],'real-project')
