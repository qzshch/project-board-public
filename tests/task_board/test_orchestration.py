"""Real HTTP node pairing, durable delivery, notification and isolation races."""
import json,secrets,time,unittest,uuid
from . import test_projects as fixture
from . import test_governance as gov_fixture
from task_board.operations import Operations
from task_board.orchestration import Orchestrator
from task_board.store import BoardError

class OrchestrationCase(unittest.TestCase):
    setUp=fixture.ProjectCase.setUp;tearDown=fixture.ProjectCase.tearDown;call=fixture.ProjectCase.call
    atomic=gov_fixture.GovernanceCase.atomic;gov=gov_fixture.GovernanceCase.gov;event=gov_fixture.GovernanceCase.event
    def prepare_node(self,runtime='codex'):
        pair=self.call('/api/nodes/pair',{'id':'pc-one','name':'Tailscale arbitrary host','projects':['alpha']},self.admin);self.assertEqual(pair[0],201,pair)
        self.node={'token':'node.'+secrets.token_urlsafe(40)};self.pair=pair[1]
        value={'id':'pc-one','pair':self.pair['pair']};self.assertEqual(self.call('/api/node/enroll',value,self.node)[0],201);self.assertTrue(self.call('/api/node/enroll',value,self.node)[1]['replayed'])
        caps={runtime:{'ready':True,'version':'fixture-control-protocol','models':['actual-route'],'roots':{'alpha':['src']},'reason':'isolated fixture, no model claim'}}
        self.assertEqual(self.call('/api/node/heartbeat',{'capabilities':caps},self.node)[0],200)
    def action(self,action,p,profile=None,rid=None):return self.call('/api/projects/alpha/orchestration',{'request_id':rid or uuid.uuid4().hex,'action':action,'payload':p},profile or self.admin)
    def bind(self,role='worker',bid='binding-one',runtime='codex'):
        if role=='worker':self.atomic('work/one')
        task=self.hub.store('alpha').get('work/one') if role=='worker' else None
        p={'id':bid,'node':'pc-one','runtime':runtime,'model':'actual-route','root':'src','role':role,'task':'work/one' if task else '','scope':task['scope_hash'] if task else ''}
        result=self.action('bind',p);self.assertEqual(result[0],201,result);return p
    def poll(self):
        result=self.call('/api/node/poll',{},self.node);self.assertEqual(result[0],200,result);return result[1]
    def report(self,job,status='accepted',session='session-one'):
        return self.call('/api/node/report',{'job':job['job'],'lease':job['lease'],'status':status,'session':session,'summary':'real fixture receipt'},self.node)
    def test_human_authorizes_node_but_project_agent_cannot_pair_or_use_node_identity(self):
        self.assertEqual(self.call('/api/nodes/pair',{'id':'x','name':'x','projects':['alpha']},self.a)[0],403);self.prepare_node()
        self.assertEqual(self.call('/api/projects/alpha/snapshot',profile=self.node)[0],401)
        self.assertEqual(self.call('/api/nodes',profile=self.a)[0],403)
        self.assertNotIn('pair',json.dumps(self.call('/api/nodes',profile=self.admin)[1]));self.assertNotIn(self.node['token'],json.dumps(self.call('/api/nodes',profile=self.admin)[1]))
    def test_create_receipt_separate_from_first_input_and_exact_replay(self):
        self.prepare_node();self.bind();job=self.poll();self.assertEqual(job['body']['operation'],'create')
        self.assertIsNone(self.poll()['job']);self.assertEqual(self.report(job)[0],200);self.assertTrue(self.report(job)[1]['replayed'])
        follow=self.poll();self.assertEqual(follow['body']['kind'],'start');self.assertEqual(follow['binding']['session'],'session-one');self.assertEqual(self.report(follow)[0],200)
        self.assertEqual(self.hub.store('alpha').get('work/one')['status'],'planned');self.assertIsNone(self.poll()['job'])
    def test_unknown_lease_stays_reserved_and_recovery_cannot_replace_session(self):
        self.prepare_node();self.bind();job=self.poll()
        with self.hub.connection() as db:db.execute('UPDATE orch_jobs SET expires=? WHERE id=?',(time.time()-1,job['job']))
        self.assertIsNone(self.poll()['job']);self.assertEqual(self.report(job)[0],409)
        p={'job':job['job'],'session':'session-one','status':'accepted','summary':'Inspected original local receipt','evidence':'fixture/local-receipt.json'}
        self.assertEqual(self.action('recover',p)[0],201);self.assertEqual(self.call('/api/projects/alpha/orchestration',profile=self.admin)[1]['bindings'][0]['session'],'session-one')
        self.assertEqual(self.action('recover',p)[0],409)
    def test_changed_scope_requires_explicit_se_confirmation_and_keeps_original_session(self):
        self.prepare_node();self.bind();job=self.poll();self.assertEqual(self.report(job)[0],200)
        original=self.hub.store('alpha').get('work/one');spec=original['spec'];spec['description']='SE approved revised bounded task';self.assertEqual(self.event('work/one','scope',{'spec':spec,'reason':'Actual plan change'},self.admin)[0],201)
        current=self.hub.store('alpha').get('work/one');p={'binding':'binding-one','summary':'SE confirms revised task','previous_scope':original['scope_hash'],'scope':current['scope_hash'],'scope_version':current['scope_version']}
        self.assertEqual(self.action('resume',{**p,'scope_version':1})[0],409);self.assertEqual(self.action('resume',p)[0],201)
        job=self.poll();self.assertEqual(job['body']['operation'],'resume');self.assertEqual(job['binding']['session'],'session-one');self.assertEqual(job['binding']['scope'],current['scope_hash']);self.assertEqual(job['binding']['scope_version'],current['scope_version'])
    def test_busy_retains_job_and_revocation_stops_new_polls(self):
        self.prepare_node();self.bind();job=self.poll();self.assertEqual(self.report(job,'busy',None)[0],200);self.assertIsNone(self.poll()['job'])
        self.assertEqual(self.call('/api/nodes/revoke',{'id':'pc-one','reason':'local machine retired'},self.admin)[0],201);self.assertEqual(self.call('/api/node/poll',{},self.node)[0],401)
    def test_worker_profile_is_only_own_binding_and_never_se_or_global(self):
        self.prepare_node();self.bind();self.bind('se','se-one')
        result=self.call('/api/node/profile',{'binding':'binding-one'},self.node);self.assertEqual(result[0],200,result)
        p=result[1];self.assertEqual(p['project_id'],'alpha');self.assertEqual(self.call('/api/projects/beta/snapshot',profile=p)[0],404)
        self.assertEqual(self.call('/api/node/profile',{'binding':'se-one'},self.node)[0],403)
        self.assertEqual(self.call('/api/node/profile',{'binding':'binding-one'},self.node)[1]['token'],p['token'])
    def test_native_permission_observation_notifies_se_without_fake_worker_comment(self):
        self.prepare_node();self.bind();self.bind('se','se-one')
        for _ in range(4):
            job=self.poll();session='worker-session' if job['binding']['id']=='binding-one' else 'se-session';self.assertEqual(self.report(job,session=session)[0],200)
        caps=self.call('/api/nodes',profile=self.admin)[1]['nodes'][0]['capabilities'];p={'capabilities':caps,'observations':[{'binding':'binding-one','session':'worker-session','status':'approval_required'}]}
        self.assertEqual(self.call('/api/node/heartbeat',p,self.node)[0],200);self.assertEqual(self.call('/api/node/heartbeat',p,self.node)[0],200)
        notice=self.poll();self.assertEqual(notice['binding']['id'],'se-one');self.assertEqual(notice['body']['kind'],'runtime_approval');self.report(notice,session='se-session');self.assertIsNone(self.poll()['job'])
        self.assertFalse(Operations(self.hub.store('alpha')).snapshot().get('wf_threads'));self.assertEqual(self.hub.store('alpha').get('work/one')['status'],'planned')
    def test_comment_and_reply_notify_original_sessions_once(self):
        self.prepare_node();self.bind();self.bind('se','se-one');worker=self.call('/api/node/profile',{'binding':'binding-one'},self.node)[1]
        for _ in range(4):
            job=self.poll();session='worker-session' if job['binding']['id']=='binding-one' else 'se-session';self.assertEqual(self.report(job,session=session)[0],200)
        task=self.hub.store('alpha').get('work/one');self.assertEqual(self.event('work/one','claim',{'summary':'take task'},worker)[0],201)
        def op(action,p,who):
            revision=Operations(self.hub.store('alpha')).snapshot()['revision'];return self.call('/api/projects/alpha/operations',{'request_id':uuid.uuid4().hex,'expected_revision':revision,'action':action,'payload':p},who)
        opened=op('thread_open',{'task':'work/one','scope':task['scope_hash'],'scope_version':task['scope_version'],'id':'question-one','kind':'blocker','title':'Need a decision','body':'Actual obstacle','to':['SE'],'pause':False,'affected_step':'current implementation'},worker);self.assertEqual(opened[0],201,opened)
        notice=self.poll();self.assertEqual(notice['binding']['id'],'se-one');self.assertEqual(notice['body']['thread'],'question-one');self.report(notice,session='se-session')
        self.assertEqual(op('thread_reply',{'thread':'question-one','body':'Continue inside original boundary'},self.admin)[0],201)
        reply=self.poll();self.assertEqual(reply['binding']['id'],'binding-one');self.report(reply,session='worker-session');self.assertIsNone(self.poll()['job'])

    def test_antigravity_roles_and_failed_turn_require_original_job_recovery(self):
        self.prepare_node('antigravity');self.bind(runtime='antigravity');self.bind('se','se-one','antigravity');worker_job=None
        for _ in range(4):
            job=self.poll();session='worker-native' if job['binding']['role']=='worker' else 'se-native';self.assertEqual(self.report(job,session=session)[0],200)
            if job['binding']['role']=='worker' and job['body']['operation']!='create':worker_job=job
        caps=self.call('/api/nodes',profile=self.admin)[1]['nodes'][0]['capabilities']
        p={'capabilities':caps,'observations':[{'binding':'binding-one','session':'worker-native','status':'needs_recovery'}]}
        self.assertEqual(self.call('/api/node/heartbeat',p,self.node)[0],200);self.assertEqual(self.call('/api/node/heartbeat',p,self.node)[0],200)
        notice=self.poll();self.assertEqual(notice['binding']['role'],'se');self.assertEqual(notice['body']['kind'],'runtime_recovery');self.report(notice,session='se-native')
        self.assertIsNone(self.poll()['job'])
        recovery={'job':worker_job['job'],'session':'worker-native','status':'failed','summary':'Native terminal failure checked before explicit continuation','evidence':'G:/fixture/receipt.json'}
        self.assertEqual(self.action('recover',recovery)[0],201)
        self.assertEqual(self.action('resume',{'binding':'binding-one','summary':'Explicit continuation after local recovery'})[0],201)
        resumed=self.poll();self.assertEqual(resumed['binding']['runtime'],'antigravity');self.assertEqual(resumed['binding']['session'],'worker-native');self.assertEqual(resumed['body']['operation'],'resume')
