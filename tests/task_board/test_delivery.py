from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

path=Path(__file__).resolve().parents[2]/'tools/check_delivery.py'
spec=importlib.util.spec_from_file_location('generic_gate',path);gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)

class DeliveryCase(unittest.TestCase):
    def setUp(self):
        self.task={'spec':{'id':'impl/one','registered':True,'allowed_paths':['src/one/'],'work':{'baseline':'a'*40,'contracts':['api@1'],'assets':['method']}},'scope_version':1,'scope_hash':'b'*64,'owner':'dev-one'}
        self.manifest={'project_id':'fresh','task_id':'impl/one','actor':'dev-one','scope_version':1,'scope_hash':'b'*64,'baseline':'a'*40,'implementation_commit':'c'*40,'contracts':['api@1'],'assets':['method']}
        self.record={'project_id':'fresh','current_submission_id':'event-one','current_status':'submitted','event':{'id':'event-one','task_id':'impl/one','kind':'submit','hash':'d'*64,'actor':'dev-one','payload':{'implementation_commit':'c'*40}}}
        self.receipt={'project_id':'fresh','event_id':'event-one','event_hash':'d'*64}
    def validate(self,files=None):return gate.validate(self.task,self.record,self.receipt,self.manifest,files or ['src/one/module.py'])
    def test_generic_registered_delivery_needs_no_game_foundation(self):self.assertTrue(self.validate()['passed'])
    def test_foreign_project_stale_scope_and_mismatched_contract_are_rejected(self):
        for key,value in [('project_id','foreign'),('scope_version',0),('scope_hash','0'*64),('contracts',['api@2']),('baseline','0'*40)]:
            original=deepcopy(self.manifest);self.manifest[key]=value
            with self.assertRaises(gate.BoardError):self.validate()
            self.manifest=original
    def test_escaped_shared_and_prefix_collision_paths_are_rejected(self):
        for path in ['src/two/a.py','src/one-other/a.py','src/one/../../shared.py','G:/secret.py','src\\one\\a.py']:
            with self.assertRaises(gate.BoardError):self.validate([path])
    def test_superseded_rework_and_forged_receipt_are_rejected(self):
        self.record['current_submission_id']='event-two'
        with self.assertRaises(gate.BoardError):self.validate()
        self.record['current_submission_id']='event-one';self.record['current_status']='changes_requested'
        with self.assertRaises(gate.BoardError):self.validate()
        self.record['current_status']='submitted';self.receipt['event_hash']='0'*64
        with self.assertRaises(gate.BoardError):self.validate()
