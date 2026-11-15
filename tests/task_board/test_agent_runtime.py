"""Protocol frame contracts and conservative uncertain/busy semantics."""
import json,os,sys,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from tools.agent_runtime import Runtime,Wire,ProtocolError,Busy,Uncertain
from tools.agent_node import Node
from tools.task_board_client import save
from . import test_projects as fixture

class FakeWire:
    def __init__(self,*args):self.calls=[];self.events=[];self.dead=False
    def call(self,method,p,timeout=45):
        self.calls.append((method,p))
        responses={'initialize':{},'thread/start':{'thread':{'id':'original-session'}},'thread/resume':{},'turn/start':{'turn':{'id':'turn-one'}},'session/create':{'session':{'sessionId':'original-session'}},'session/read':{'session':{'status':'idle'}},'session/resume':{},'session/send':{'accepted':True},'session/working-directory/set':{'cwd':'/fixture'},'session/prompt':{'messageId':'message-one'},'runtime/capabilities':{}}
        return responses.get(method,{})
    def notify(self,*args):pass
    def close(self):pass

class RuntimeCase(unittest.TestCase):
    def test_eof_after_request_is_uncertain_not_a_known_rejection(self):
        parent=fixture.ROOT/'evidence/task-board-tests';parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as folder:
            wire=Wire([sys.executable,'-B','-c','import sys;sys.stdin.buffer.readline()'],folder,os.environ,Path(folder)/'audit','codex')
            try:
                with self.assertRaises(Uncertain):wire.call('turn/start',{'threadId':'original','input':[]},timeout=5)
            finally:wire.close()
            self.assertIsNotNone(wire.process.poll())
    def driver(self,kind):
        with patch('tools.agent_runtime.Wire',FakeWire):return Runtime(kind,{'command':['fixture']},fixture.ROOT,fixture.ROOT/'evidence/test-unused','provider/model')
    def test_codex_accepted_turn_does_not_depend_on_rollout_flush_and_cannot_reenter(self):
        driver=self.driver('codex');sid=driver.create('stable','model');driver.send(sid,'model','Bounded test','job-one');self.assertTrue(driver.busy(sid))
        with self.assertRaises(Busy):driver.send(sid,'model','Second input','job-two')
        driver.wire.events.append({'method':'turn/completed','params':{'turn':{'id':'other-turn'}}});self.assertTrue(driver.busy(sid))
        driver.wire.events.append({'method':'turn/completed','params':{'turn':{'id':'turn-one','status':'completed'}}});self.assertFalse(driver.busy(sid))
        self.assertEqual(sum(m=='turn/start' for m,p in driver.wire.calls),1)
    def test_zcode_uses_native_snapshot_and_client_selected_session_identity(self):
        driver=self.driver('zcode');sid=driver.create('stable-root','provider/model');driver.send(sid,'provider/model','One input','job-one');create=next(p for m,p in driver.wire.calls if m=='session/create');self.assertEqual(create['sessionId'],'stable-root');self.assertEqual(create['mode'],'edit');self.assertEqual(create['workspace']['workspacePath'],str(fixture.ROOT.resolve()))
        self.assertEqual(driver.wire.calls[-1],('session/send',{'sessionId':'original-session','content':'One input','inputId':'job-one'}))
    def test_deepseek_official_sdk_requires_cwd_content_blocks_and_does_not_fake_stop(self):
        driver=self.driver('deepseek');init=driver.wire.calls[0][1];self.assertEqual(init['cwd'],str(fixture.ROOT.resolve()));self.assertTrue(init['approvalRequests']);sid=driver.create('stable-root','provider/model');self.assertEqual(sid,'stable-root');driver.send(sid,'provider/model','One input','job-one')
        self.assertEqual(driver.wire.calls[-1],('session/prompt',{'sessionId':'stable-root','contentBlocks':[{'type':'text','text':'One input'}]}))
        with self.assertRaises(ProtocolError):driver.stop(sid)
    def test_zcode_required_model_options_and_busy_admission_race(self):
        driver=self.driver('zcode');driver.config['model_options']={'provider/model':{'reasoningLevel':'high'}};sid=driver.create('fixed','provider/model');create=next(p for m,p in driver.wire.calls if m=='session/create');self.assertEqual(create['model']['options'],{'reasoningLevel':'high'})
        call=driver.wire.call
        def raced(method,p,**kw):
            if method=='session/send':raise ProtocolError('A prompt is already running for this session')
            return call(method,p,**kw)
        driver.wire.call=raced
        with self.assertRaises(Busy):driver.send(sid,'provider/model','One input','job-one')
    def test_node_restart_never_repeats_an_uncertain_model_input(self):
        parent=fixture.ROOT/'evidence/task-board-tests';parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as folder:
            root=Path(folder);config=root/'config.json';save(config,{'id':'fixture-node','url':'http://127.0.0.1:1','state':str(root/'state'),'max_parallel':1,'projects':{'alpha':{'roles':['worker'],'roots':{'workspace':str(root)}}},'runtimes':{}})
            job={'job':'job-unknown','lease':'held-lease','binding':{'id':'binding-one','session':'original-session'}};path=root/'state/receipts/job-unknown.json';save(path,{'status':'attempting','session':'original-session'})
            node=Node(config)
            try:
                with patch.object(node,'report') as report,patch('tools.agent_node.Runtime') as runtime:node.execute(job)
                runtime.assert_not_called();self.assertEqual(report.call_args.args[1],'needs_recovery');self.assertEqual(report.call_args.args[2],'original-session')
                with self.assertRaises(ValueError):Node(config)
            finally:node.close()
    def test_local_node_rejects_shell_wrapper_and_remote_path_injection(self):
        parent=fixture.ROOT/'evidence/task-board-tests';parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as folder:
            root=Path(folder);config=root/'config.json';value={'id':'fixture-node','url':'http://127.0.0.1:1','state':str(root/'state'),'max_parallel':1,'projects':{'alpha':{'roles':['worker'],'roots':{'workspace':str(root)}}},'runtimes':{'codex':{'command':['cmd.exe','/c','start','codex']}}};save(config,value)
            with self.assertRaises(ValueError):Node(config)
            value['runtimes']={};save(config,value);node=Node(config)
            try:
                with self.assertRaises(ProtocolError):node.execute({'job':'../../escape','binding':{'id':'one'}})
            finally:node.close()
