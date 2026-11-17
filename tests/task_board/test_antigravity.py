"""ACP lifecycle and one-shot permissions, independent of provider availability."""
import hashlib,json,queue,threading,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tools.agent_runtime import Runtime,Wire,ProtocolError,Busy,Uncertain

ROOT=Path(__file__).resolve().parents[2]

class ACP:
    def __init__(self,*args):self.calls=[];self.events=[];self.dead=False;self.sessions=set();self.waiters={};self.lock=threading.RLock();self.q=queue.Queue()
    def call(self,method,p,timeout=45):
        self.calls.append((method,p))
        if method=='initialize':return {'protocolVersion':1,'agentInfo':{'name':'Antigravity ACP Server','version':'fixture-ACP1'},'agentCapabilities':{'loadSession':True}}
        if method in ('session/new','session/load'):return {'sessionId':'native-ACP-session','models':{'availableModels':[{'modelId':'route-one'},{'modelId':'not-allowed'}]}}
        return {}
    def submit(self,method,p):self.calls.append((method,p));self.waiters[1]=self.q;return 1,self.q
    def notify(self,method,p):self.calls.append((method,p))
    response=staticmethod(Wire.response)
    def close(self):self.dead=True

class AntigravityCase(unittest.TestCase):
    def setUp(self):
        parent=ROOT/'evidence/task-board-tests';parent.mkdir(parents=True,exist_ok=True);self.temp=tempfile.TemporaryDirectory(dir=parent);self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def driver(self):
        with patch('tools.agent_runtime.Wire',ACP):return Runtime('antigravity',{'command':['fixture','acp'],'models':['route-one']},self.root,self.root/'process','route-one')
    def test_native_id_model_mode_busy_completion_and_exact_resume(self):
        d=self.driver();self.assertEqual(d.models(),['route-one']);sid=d.create('not-the-native-session','route-one');self.assertEqual(sid,'native-ACP-session')
        self.assertIn(('session/set_mode',{'sessionId':sid,'modeId':'default'}),d.wire.calls)
        d.send(sid,'route-one','one prompt','one-job');self.assertTrue(d.busy(sid))
        with self.assertRaises(Busy):d.send(sid,'route-one','steering forbidden','two-job')
        self.assertEqual(sum(m=='session/prompt' for m,p in d.wire.calls),1)
        d.wire.q.put({'result':{'stopReason':'end_turn'}});self.assertFalse(d.busy(sid));self.assertEqual(len(list((self.root/'process').glob('turn-*.json'))),1)
        restored=self.driver();restored.resume(sid,'route-one');self.assertIn(('session/load',{'sessionId':sid,'cwd':str(self.root.resolve()),'mcpServers':[]}),restored.wire.calls)
        restored.stop(sid);self.assertEqual(restored.wire.calls[-1],('session/cancel',{'sessionId':sid}))
        with self.assertRaises(ProtocolError):restored.stop('some-other-session')
        with self.assertRaises(ProtocolError):self.driver().create('stable','not-allowed')
    def test_error_and_unknown_terminal_do_not_release_or_replay_prompt(self):
        for terminal in ({'error':{'message':'Actual provider failure'}},{'result':{'stopReason':'new-unknown-status'}},{'_transport_closed':True}):
            d=self.driver();sid=d.create('stable','route-one');d.send(sid,'route-one','one','job');d.wire.q.put(terminal)
            with self.assertRaises(Uncertain):d.busy(sid)
            with self.assertRaises(Uncertain):d.send(sid,'route-one','unsafe retry','second-job')
            self.assertEqual(sum(m=='session/prompt' for m,p in d.wire.calls),1)
    def test_real_server_identity_and_protocol_are_required(self):
        class Wrong(ACP):
            def call(self,*args,**kwargs):return {'protocolVersion':1,'agentInfo':{'name':'Other ACP'}}
        with patch('tools.agent_runtime.Wire',Wrong):
            with self.assertRaises(ProtocolError):Runtime('antigravity',{'command':['fixture','acp']},self.root,self.root/'p','route-one')
    def test_permission_only_exact_owned_command_once_and_no_daemon(self):
        script=self.root/'client.py';script.write_text('# operator approved fixture','utf8')
        w=Wire.__new__(Wire);w.runtime='antigravity';w.cwd=self.root.resolve();w.events=[];w.sessions={'native-session'};w.approval_context={'project':'alpha','role':'worker','binding':'one'}
        w.approved_commands=[{'project':'alpha','role':'worker','cwd':str(self.root),'command':'python approved.py','script':str(script),'sha256':hashlib.sha256(script.read_bytes()).hexdigest()}]
        value={'CommandLine':'python approved.py','IsDaemon':False,'WaitMsBeforeAsync':5000}
        frame={'method':'session/request_permission','params':{'sessionId':'native-session','toolCall':{'name':'run_command','kind':'execute','rawInput':value},'options':[{'kind':'allow_once','optionId':'allow'},{'kind':'allow_always','optionId':'always'}]}}
        self.assertEqual(w.approval(frame),{'outcome':{'outcome':'selected','optionId':'allow'}})
        value['IsDaemon']=True;self.assertIsNone(w.approval(frame));value['IsDaemon']=False
        value['extraPrivilege']=True;self.assertIsNone(w.approval(frame));del value['extraPrivilege']
        w.approval_context['role']='se';self.assertIsNone(w.approval(frame));w.approval_context['role']='worker'
        frame['params']['sessionId']='unowned';self.assertIsNone(w.approval(frame));frame['params']['sessionId']='native-session'
        script.write_text('changed by worker','utf8');self.assertIsNone(w.approval(frame))
