"""Project SE self-service does not grant instance or other-project control."""
import hashlib,json,os,secrets,sys,uuid,unittest
from pathlib import Path
from . import test_projects as f
from . import test_governance as g
from task_board.orchestration import project_node_id
from tools.owned_process import run
from tools.task_board_client import save

class ProjectNodeCase(unittest.TestCase):
    setUp=f.ProjectCase.setUp;tearDown=f.ProjectCase.tearDown;call=f.ProjectCase.call
    atomic=g.GovernanceCase.atomic;event=g.GovernanceCase.event;gov=g.GovernanceCase.gov
    def grant(self,action='connect',roles=None):
        self.token='node.'+secrets.token_urlsafe(40)
        value={'request_id':uuid.uuid4().hex,'alias':'home-cli','name':'actual local Tailscale machine','roles':roles or ['se','worker']}
        value.update({'key_sha256':hashlib.sha256(self.token.encode()).hexdigest()} if action=='connect' else {'pair':secrets.token_hex(32)})
        return value
    def post(self,action,p,profile=None,project='alpha'):return self.call('/api/projects/'+project+'/nodes/'+action,p,profile or self.reviewer)
    def test_se_direct_connect_and_private_pair_are_scoped_idempotent_and_offline_until_heartbeat(self):
        p=self.grant();r=self.post('connect',p);self.assertEqual(r[0],201,r[1]);nid=r[1]['id'];self.assertEqual(nid,project_node_id('alpha','home-cli'))
        self.assertTrue(self.post('connect',p)[1]['replayed']);self.assertEqual(self.call('/api/projects/alpha/nodes',profile=self.reviewer)[1]['nodes'][0]['online'],False)
        bad={**p,'name':'must not change a frozen request'};self.assertEqual(self.post('connect',bad)[0],409)
        caps={'antigravity':{'ready':True,'version':'fixture ACP1','models':['route'],'roots':{'alpha':['workspace']},'reason':'isolated capability fixture'}}
        self.assertEqual(self.call('/api/node/heartbeat',{'capabilities':caps},{'token':self.token})[0],200)
        nodes=self.call('/api/projects/alpha/orchestration',profile=self.reviewer)[1];self.assertTrue(nodes['node_management']);self.assertTrue(nodes['nodes'][0]['online'])
        second=self.grant('pair');second['alias']='other-machine';pair=self.post('pair',second);self.assertEqual(pair[0],201,pair[1]);self.assertEqual(pair[1]['pair'],second['pair']);self.assertEqual(self.post('pair',second)[1]['pair'],second['pair'])
        with self.hub.connection() as db:
            stored=''.join(r[0] for r in db.execute('SELECT result FROM orch_requests'))+''.join(r[0] for r in db.execute('SELECT payload FROM audit'))
        self.assertNotIn(second['pair'],stored);self.assertNotIn(self.token,stored)
    def test_worker_foreign_project_and_role_escalation_rejected(self):
        p=self.grant(roles=['worker']);self.assertEqual(self.post('connect',p,self.a)[0],403);self.assertEqual(self.post('connect',p,self.b)[0],404)
        self.assertEqual(self.post('connect',{**p,'projects':['alpha','beta']})[0],400)
        self.assertEqual(self.post('connect',{**p,'roles':[{}]})[0],400)
        self.assertEqual(self.post('connect',p)[0],201);nid=project_node_id('alpha',p['alias'])
        caps={'antigravity':{'ready':True,'version':'fixture','models':['route'],'roots':{'alpha':['workspace']},'reason':'fixture'}}
        self.assertEqual(self.call('/api/node/heartbeat',{'capabilities':caps},{'token':self.token})[0],200)
        binding={'request_id':uuid.uuid4().hex,'action':'bind','payload':{'id':'unapproved-se','node':nid,'runtime':'antigravity','model':'route','root':'workspace','role':'se','task':'','scope':''}}
        self.assertEqual(self.call('/api/projects/alpha/orchestration',binding,self.reviewer)[0],403)
        self.assertEqual(self.call('/api/projects/beta/nodes',profile=self.b)[0],403)
    def test_project_revoke_cannot_touch_shared_or_foreign_nodes_and_retains_identity(self):
        p=self.grant();self.assertEqual(self.post('connect',p)[0],201);nid=project_node_id('alpha',p['alias'])
        shared=self.call('/api/nodes/pair',{'id':'shared-host','name':'shared','projects':['alpha','beta']},self.admin);self.assertEqual(shared[0],201)
        self.assertEqual(self.post('revoke',{'id':'shared-host','reason':'must not revoke other project access'})[0],404)
        self.assertEqual(self.post('revoke',{'id':nid,'reason':'outside project'},self.b,'beta')[0],403)
        self.assertEqual(self.post('revoke',{'id':nid,'reason':'project SE retires owned endpoint'})[0],201)
        self.assertEqual(self.call('/api/node/poll',{}, {'token':self.token})[0],401);self.assertEqual(self.post('connect',p)[0],409)
        with self.hub.connection() as db:self.assertTrue(db.execute("SELECT enabled FROM orch_nodes WHERE id='shared-host'").fetchone()[0])
        self.assertEqual(self.call('/api/projects/alpha/me',profile=self.reviewer)[0],200)
    def test_same_machine_alias_is_isolated_between_project_namespaces(self):
        p=self.grant();self.assertEqual(self.post('connect',p)[0],201)
        beta=self.hub.invite('beta','beta-se','reviewer');other=self.grant();r=self.post('connect',other,beta,'beta');self.assertEqual(r[0],201,r[1]);self.assertNotEqual(r[1]['id'],project_node_id('alpha',p['alias']))
        nodes=self.call('/api/projects/alpha/nodes',profile=self.reviewer)[1]['nodes'];self.assertEqual(len(nodes),1);self.assertEqual(nodes[0]['projects'],['alpha'])
        self.assertEqual(self.post('revoke',{'id':r[1]['id'],'reason':'cannot touch other namespace'})[0],404)
    def test_real_se_cli_bootstraps_from_local_config_without_human_or_global_token(self):
        workspace=self.state/'workspace';workspace.mkdir();profile=self.state/'project-se.json';save(profile,{**self.reviewer,'url':self.url})
        config=self.state/'local-node.json';save(config,{'id':'se-local-machine','url':self.url,'state':str(self.state/'node-state'),'max_parallel':1,'projects':{'alpha':{'roles':['se','worker'],'roots':{'workspace':str(workspace)}}},'runtimes':{}})
        command=[sys.executable,'-B','-X','utf8','-m','tools.agent_node','--config',str(config),'--authorize-profile',str(profile),'--probe']
        rc,out,err=run(command,cwd=f.ROOT,evidence=self.state/'process-evidence',purpose='Real project SE CLI bootstrap with isolated empty local runtime configuration',timeout=30);self.assertEqual(rc,0,err.decode())
        self.assertNotIn(self.reviewer['token'].encode(),out);generated=json.loads((self.state/'node-state/se-node-config.json').read_text('utf8'));self.assertEqual(generated['projects']['alpha']['se_profile'],str(profile.resolve()))
        rc,_,err=run(command,cwd=f.ROOT,evidence=self.state/'process-evidence',purpose='Retry identical SE node bootstrap',timeout=30);self.assertEqual(rc,0,err.decode())
        nodes=self.call('/api/projects/alpha/nodes',profile=self.reviewer)[1]['nodes'];self.assertEqual(len(nodes),1);self.assertEqual(nodes[0]['capabilities'],{})
        from tools.agent_node import authorize_config
        global_profile=self.state/'global.json';save(global_profile,{**self.admin,'url':self.url,'project_id':'alpha'})
        with self.assertRaises(ValueError):authorize_config(config,global_profile)
