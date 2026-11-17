"""Explicit source hashing and project-bound frozen historical packages."""
import tempfile,unittest
from pathlib import Path
from tools.retrospective_client import prepare,sha

class RetrospectiveClientCase(unittest.TestCase):
    def test_prepare_only_explicit_project_sources_and_keep_credentials_out(self):
        root=Path(__file__).resolve().parents[2]/'evidence/task-board-tests';root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as folder:
            p=Path(folder);source=p/'source.json';source.write_text('actual source metadata','utf8');manifest=p/'MANIFEST.json';manifest.write_text('actual controlled manifest','utf8')
            package={'project_id':'alpha','draft':{'archive':{'path':str(manifest),'sha256':sha(manifest)},'entries':[{'origin':{'path':str(source),'sha256':sha(source)}}]}}
            profile={'project_id':'alpha','token':'fixture-must-not-export'};request,checked=prepare(profile,package,[p]);self.assertEqual(request['action'],'submit');self.assertEqual(request['project_id'],'alpha');self.assertNotIn('token',str(request));self.assertEqual(len(checked),2)
            with self.assertRaises(ValueError):prepare({'project_id':'beta'},package,[p])
            package['draft']['archive']['sha256']='0'*64
            with self.assertRaises(ValueError):prepare(profile,package,[p])
    def test_no_unapproved_root_or_directory_scan(self):
        root=Path(__file__).resolve().parents[2]/'evidence/task-board-tests';root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as folder:
            p=Path(folder);allowed=p/'allowed';allowed.mkdir();outside=p/'unapproved.json';outside.write_text('do not read by traversal','utf8');pack={'project_id':'alpha','draft':{'archive':{'path':str(outside),'sha256':sha(outside)},'entries':[]}}
            with self.assertRaises(ValueError):prepare({'project_id':'alpha'},pack,[allowed])
