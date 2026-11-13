import json
import io
import hashlib
import zipfile
from pathlib import Path
import unittest
from urllib.request import Request
from urllib.error import HTTPError
from . import test_projects as fixtures
from task_board.help import render_markdown

class HelpCase(unittest.TestCase):
    setUp=fixtures.ProjectCase.setUp
    tearDown=fixtures.ProjectCase.tearDown

    def get(self,path,profile=None):
        req=Request(self.url+path,headers={'Authorization':'Bearer '+profile['token']} if profile else {})
        try:
            with self.opener.open(req,timeout=5) as r:return r.status,r.read(),dict(r.headers)
        except HTTPError as error:return error.code,error.read(),dict(error.headers)

    def test_shareable_guides_are_available_without_project_or_admin_material(self):
        for path in ('/help','/help/admin','/help/connectivity','/help/operations','/help/runner','/help/agent','/help/owner','/help/templates','/agent-guide.md','/owner-guide.md'):
            code,body,_=self.get(path);self.assertEqual(code,200,path)
            self.assertNotIn(b'alpha private',body);self.assertNotIn(b'beta private',body)
            self.assertNotIn(b'operator.html',body);self.assertNotIn(b'_private/admin',body)
            self.assertNotIn(self.admin['token'].encode(),body)
        self.assertIn(b'example-server.example-tailnet.ts.net:18785',self.get('/help/agent')[1])

    def test_full_operator_docs_require_global_admin_not_project_review_role(self):
        for path in ('/help/operator','/help/deployment','/manual.md'):
            self.assertIn(self.get(path)[0],(401,403))
            for profile in (self.a,self.reviewer):self.assertEqual(self.get(path,profile)[0],403)
            self.assertEqual(self.get(path,self.admin)[0],200)

    def test_reading_management_docs_does_not_grant_project_or_global_actions(self):
        for profile in (None,self.a,self.reviewer):
            code,body,_=self.get('/help/admin',profile);self.assertEqual(code,200)
            self.assertIn('阅读文档不会授予'.encode('utf8'),body)
        for path in ('/help/operator','/help/deployment','/manual.md'):
            self.assertEqual(self.get(path,self.a)[0],403)
        self.assertNotIn(b'operator.html',self.get('/help/admin')[1])
        self.assertIn(b'--resolve',self.get('/help/connectivity')[1])
        status=fixtures.ProjectCase.call(self,'/api/projects',{'id':'forbidden','name':'No','description':'Read access is not admin'},self.a)[0]
        self.assertEqual(status,403)
        self.assertEqual(fixtures.ProjectCase.call(self,'/api/projects/beta/governance',profile=self.a)[0],404)

    def test_template_whitelist_does_not_serve_arbitrary_files(self):
        code,body,_=self.get('/templates/project-init.json');self.assertEqual(code,200);self.assertEqual(set(json.loads(body)),{'id','name','description','knowledge','governance_profile'})
        for path in ('/templates/../../state/_private/admin.json','/templates/server.json','/help/../../state/_private/admin.json'):
            code,body,_=self.get(path,self.admin);self.assertEqual(code,404,path);self.assertNotIn(self.admin['token'].encode(),body)

    def test_markdown_renderer_escapes_html_and_unsafe_links(self):
        body=render_markdown('# Guide\n\n<script>alert(1)</script>\n\n[bad](javascript:evil) [safe](/help/agent)\n\n```sh\n<secret-placeholder>\n```')
        self.assertIn('&lt;script&gt;',body);self.assertNotIn('<script>',body)
        self.assertNotIn('href="javascript:',body);self.assertIn('href="/help/agent"',body)
        self.assertIn('<pre><code>&lt;secret-placeholder&gt;',body)

    def test_main_ui_exposes_handbook_and_role_guides(self):
        code,body,_=self.get('/');self.assertEqual(code,200)
        for link in (b'href="/help"',b'href="/help/agent"',b'href="/help/owner"'):self.assertIn(link,body)
        body=render_markdown('| Method | Route |\n|---|---|\n| GET | /help |')
        self.assertIn('<table>',body);self.assertEqual(body.count('<tr>'),2)

    def test_runner_download_is_only_whitelisted_sources_and_verified_manifest(self):
        code,body,_=self.get('/runner-kit.zip');self.assertEqual(code,200)
        self.assertEqual(body,self.get('/runner-kit.zip')[1])
        with zipfile.ZipFile(io.BytesIO(body)) as kit:
            self.assertEqual(set(kit.namelist()),{'tools/quality_runner.py','tools/task_board_client.py','tools/owned_process.py','tools/runner_process.py','tools/__init__.py','requirements.txt','README.md','MANIFEST.json'})
            manifest=json.loads(kit.read('MANIFEST.json'))
            for name,sha in manifest.items():
                self.assertEqual(hashlib.sha256(kit.read(name)).hexdigest(),sha);self.assertNotIn(self.admin['token'].encode(),kit.read(name))
            self.assertNotIn(self.admin['token'].encode(),body)
