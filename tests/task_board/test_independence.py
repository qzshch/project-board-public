import json
import tempfile
from pathlib import Path
import unittest
from task_board import lifecycle
from task_board.projects import ProjectHub
from task_board.store import BoardError

class IndependenceCase(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[2]/'evidence/independent-fixtures';root.mkdir(parents=True,exist_ok=True)
        self.folder=tempfile.TemporaryDirectory(dir=root);self.state=Path(self.folder.name)
    def tearDown(self):self.folder.cleanup()
    def test_empty_init_has_no_game_project_or_catalog_dependency(self):
        result=lifecycle.init_state(self.state,public_url='http://127.0.0.1:24991',port=24991)
        hub=ProjectHub(self.state);admin=hub.resolve(lifecycle.read(self.state/'_private/admin.json')['token'])
        self.assertEqual(hub.list_projects(admin),[]);self.assertEqual(result['imported'],0)
        self.assertEqual(lifecycle.read(self.state/'connection.json')['code_root'],str(Path(__file__).resolve().parents[2]))
        hub.create(admin,{'id':'fresh','name':'Fresh project','description':'No history required'})
        self.assertEqual(hub.store('fresh').head()['seq'],0)
    def test_init_reuses_credentials_and_refuses_silent_url_replacement(self):
        lifecycle.init_state(self.state,public_url='http://127.0.0.1:24991',port=24991)
        original=(self.state/'_private/admin.json').read_bytes()
        lifecycle.init_state(self.state,public_url='http://127.0.0.1:24991',port=24991)
        self.assertEqual((self.state/'_private/admin.json').read_bytes(),original)
        with self.assertRaises(BoardError):lifecycle.init_state(self.state,public_url='http://127.0.0.1:24992')
    def test_invalid_endpoints_and_ports_fail_before_state_creation(self):
        for url in ('file:///tmp/a','http://a:b@example.com','http://localhost/path','http://localhost?secret=a'):
            with self.assertRaises(BoardError):lifecycle.init_state(self.state,public_url=url)
        with self.assertRaises(BoardError):lifecycle.init_state(self.state,public_url='http://localhost',port=True)

if __name__=='__main__':unittest.main()
