"""Diagnostics are read-only; transient retries preserve bytes and decisions."""
import io,json,unittest
from unittest.mock import patch
from urllib.error import HTTPError
from tools.task_board_client import Client,ClientError
from . import test_projects as fixture
from . import test_governance as gf

class ReadinessCase(unittest.TestCase):
    setUp=fixture.ProjectCase.setUp;tearDown=fixture.ProjectCase.tearDown;call=fixture.ProjectCase.call
    atomic=gf.GovernanceCase.atomic;gov=gf.GovernanceCase.gov;event=gf.GovernanceCase.event
    def test_real_gates_read_only_and_project_scoped(self):
        self.atomic('unknown/one',inputs_known=False);store=self.hub.store('alpha');before=store.head();result=self.call('/api/projects/alpha/readiness',profile=self.admin);self.assertEqual(result[0],200,result);self.assertTrue(result[1]['read_only']);self.assertTrue(any(t['id']=='unknown/one' and not t['ready'] for t in result[1]['tasks']));self.assertEqual(store.head(),before)
        self.assertEqual(self.call('/api/projects/beta/readiness',profile=self.a)[0],404)
    def test_transient_retries_freeze_request_and_conflict_does_not_retry(self):
        client=Client(self.url,{**self.a,'url':self.url},project='alpha');seen=[];payload={'request_id':'frozen','expected_revision':3,'action':'note','payload':{'body':'same bytes'}}
        def gateway(req,**kw):
            seen.append(req.data)
            if len(seen)<3:raise HTTPError(req.full_url,503,'maintenance',{},io.BytesIO(b'{"error":"temporary"}'))
            return io.BytesIO(b'{"replayed":true}')
        with patch.object(client.opener,'open',side_effect=gateway),patch('tools.task_board_client.time.sleep'):self.assertTrue(client.call('/api/events',payload)['replayed'])
        self.assertEqual(len(seen),3);self.assertTrue(all(x==seen[0] for x in seen));self.assertEqual(json.loads(seen[0]),payload)
        with patch.object(client.opener,'open',side_effect=HTTPError(self.url,409,'changed',{},io.BytesIO(b'{}'))) as send:
            with self.assertRaises(ClientError):client.call('/api/events',payload)
            self.assertEqual(send.call_count,1)
    def test_one_time_login_not_replayed_after_gateway_error(self):
        client=Client(self.url)
        with patch.object(client.opener,'open',side_effect=HTTPError(self.url,502,'lost',{},io.BytesIO(b'{}'))) as send:
            with self.assertRaises(ClientError):client.call('/api/human/setup',{'request_id':'does-not-make-idempotent','setup':'private'})
            self.assertEqual(send.call_count,1)
