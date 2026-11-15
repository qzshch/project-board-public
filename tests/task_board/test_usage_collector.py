import json,hashlib,tempfile,unittest
from pathlib import Path
from tools.usage_collector import Spool

class CollectorCase(unittest.TestCase):
    def test_owned_event_scope_durable_replay_and_attach_baseline(self):
        root=Path(__file__).resolve().parents[2]/'evidence/collector-fixtures';root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as folder:
            spool=Spool(folder);binding={'project':'alpha','id':'worker-one','task':'new/one','role':'worker','model':'actual-route','runtime':'codex'}
            frame={'method':'thread/tokenUsage/updated','params':{'threadId':'native-id','tokenUsage':{'total':{'inputTokens':100,'outputTokens':10,'cachedInputTokens':40,'reasoningOutputTokens':2}}}}
            self.assertFalse(spool.capture(frame,binding,'other-project-session'));self.assertTrue(spool.capture(frame,binding,'native-id',created=False));self.assertFalse(spool.capture(frame,binding,'native-id'))
            path=next(Path(folder).glob('*.observation.json'));item=json.loads(path.read_text('utf8'));p=item['observation'];self.assertFalse(p['from_start']);self.assertIsNone(p['counters']['cache_write']);self.assertEqual(hashlib.sha256(Path(p['origin']['path']).read_bytes()).hexdigest(),p['origin']['sha256'])
            # Recreate after crash, preserving sample identity and pending bytes.
            recovered=Spool(folder);self.assertFalse(recovered.capture(frame,binding,'native-id'))
            class Client:
                calls=[]
                def call(self,endpoint,payload):self.calls.append(payload);return {'seq':1}
            client=Client();recovered.flush({'worker-one':client});recovered.flush({'worker-one':client});self.assertEqual(len(client.calls),1);self.assertEqual(client.calls[0],p)
            frame['params']['tokenUsage']['total']['inputTokens']=150;self.assertTrue(recovered.capture(frame,binding,'native-id'));records=[json.loads(x.read_text('utf8'))['observation'] for x in Path(folder).glob('*.observation.json')];self.assertEqual(sorted(p['ordinal'] for p in records),[1,2])
            self.assertFalse(recovered.capture(frame,{**binding,'runtime':'zcode'},'native-id'))
