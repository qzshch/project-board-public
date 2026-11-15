"""Independent human realm exercised through real HTTP, not role headers."""
import json,re,unittest
from . import test_projects as fixture
from task_board.human_auth import HumanAuth
from task_board.store import BoardError

class HumanCase(unittest.TestCase):
    setUp=fixture.ProjectCase.setUp;tearDown=fixture.ProjectCase.tearDown;call=fixture.ProjectCase.call
    def setup_account(self):
        document=(self.state/'_private/human/setup.html').read_text('utf8')
        self.secret=re.search(r'#setup=([^"<]+)',document)[1]
        code,value,headers=self.call('/api/human/setup',{'setup':self.secret,'username':'Owner','password':'a-long-fixture-password'})
        self.assertEqual(code,200,value);self.cookie=headers['Set-Cookie'].split(';')[0];return self.cookie
    def test_one_use_setup_human_visibility_and_agent_isolation(self):
        self.assertFalse(self.call('/api/human/status')[1]['configured']);self.setup_account()
        self.assertTrue(self.call('/api/human/status')[1]['configured'])
        self.assertEqual(self.call('/api/human/setup',{'setup':self.secret,'username':'Other','password':'a-long-fixture-password'})[0],401)
        me=self.call('/api/me',headers={'Cookie':self.cookie})[1];self.assertEqual(me['principal_kind'],'human')
        projects=self.call('/api/projects',headers={'Cookie':self.cookie})[1]['projects'];self.assertTrue({'alpha','beta'}<={x['id'] for x in projects})
        self.assertEqual(self.call('/api/projects/beta/snapshot',headers={'Cookie':self.cookie})[0],200)
        self.assertEqual(self.call('/api/projects/beta/snapshot',profile=self.a,headers={'Cookie':self.cookie})[0],404)
        self.assertEqual(self.call('/api/me',profile={'token':'bad'},headers={'Cookie':self.cookie})[0],401)
        self.assertNotIn(self.secret,json.dumps(me));self.assertNotIn('password',json.dumps(me))
    def test_logout_password_rotation_and_maintenance_identity_not_human(self):
        self.setup_account();payload={'current_password':'a-long-fixture-password','password':'another-long-fixture-password'}
        self.assertEqual(self.call('/api/human/password',payload,self.admin)[0],403)
        code,v,h=self.call('/api/human/password',payload,headers={'Cookie':self.cookie});self.assertEqual(code,200,v)
        self.assertEqual(self.call('/api/me',headers={'Cookie':self.cookie})[0],401)
        cookie=h['Set-Cookie'].split(';')[0];self.assertIn('HttpOnly',h['Set-Cookie']);self.assertIn('SameSite=Strict',h['Set-Cookie'])
        self.assertEqual(self.call('/api/logout',{},headers={'Cookie':cookie})[0],200);self.assertEqual(self.call('/api/me',headers={'Cookie':cookie})[0],401)
        self.assertEqual(self.call('/api/human/login',{'username':'owner','password':payload['password']})[0],200)
    def test_rate_limit_and_no_secrets_in_audit(self):
        self.setup_account()
        for _ in range(5):self.assertEqual(self.call('/api/human/login',{'username':'owner','password':'wrong'})[0],401)
        self.assertEqual(self.call('/api/human/login',{'username':'owner','password':'a-long-fixture-password'})[0],429)
        with self.hub.connection() as db:
            rows=' '.join(str(tuple(r)) for r in db.execute('SELECT * FROM human_accounts'))
        self.assertNotIn('a-long-fixture-password',rows)
        with self.assertRaises(BoardError):HumanAuth(self.hub).resolve('h.invalid')
    def test_private_setup_survives_startup_and_highest_role_is_server_issued(self):
        self.setup_account();identity=self.hub.resolve(session=self.cookie.split('=',1)[1])
        self.assertEqual(self.hub.effective_actor(identity,'alpha')['project_role'],'owner')
        self.assertEqual(self.hub.effective_actor(self.hub.resolve(self.a['token']),'alpha')['project_role'],'agent')
        self.assertIsNone(HumanAuth(self.hub).ensure_setup(self.url))
