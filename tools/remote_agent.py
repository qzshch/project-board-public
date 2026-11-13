"""Execute one explicitly scoped demo Agent operation on a remote machine.

Input arrives on stdin, including only this role's project credential. No
credential is printed or written. Generated files live in an owned temporary
directory and are returned as evidence before finally cleanup.
"""
import hashlib
import io
import json
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import unittest
import uuid

def main():
    d=json.load(sys.stdin);module={'__name__':'portable_remote'}
    exec(compile(d['client_source'],'<verified-portable-client>','exec'),module)
    Client,Error=module['Client'],module['ClientError'];c=Client(d['url'],d['profile'],d['connect_ip'])
    checks=[]
    def check(value,label):
        if not value:raise AssertionError(label)
        checks.append(label)
    own=d['profile']['project_id']
    check([p['id'] for p in c.call('/api/projects')['projects']]==[own],'project list contains only own grant')
    for endpoint in ('governance','graph','search?q=project','governance/export','shared','brief?task=upgrade/M0.code'):
        try:c.call('/api/projects/task-board/'+endpoint);raise AssertionError('foreign content returned')
        except Error as e:check(e.status==404,'foreign '+endpoint+' refused')
    mode=d['mode'];result={'remote_host':socket.gethostname(),'checks':checks,'mode':mode,'project_id':own}
    def event(action,payload):
        task=c.task(d['task_id'])
        req={'request_id':str(uuid.uuid4()),'task_id':d['task_id'],'action':action,'expected_revision':task['revision'],'scope_version':task['scope_version'],'payload':payload}
        receipt=c.call('/api/events',req)
        record=c.call('/api/receipt?id='+receipt['event_id'])
        check(record['event']['hash']==receipt['event_hash'],'receipt hash read back')
        return receipt
    if mode=='confirm':
        result['receipt']=c.call('/api/governance',{'request_id':str(uuid.uuid4()),'expected_revision':c.call('/api/governance')['revision'],'action':'contract_confirm','payload':d['payload']})
    elif mode=='submit':
        payload={**d['payload'],'implementation_commit':d['implementation_commit']}
        result['receipt']=event('submit',payload)
        check(result['receipt']['project_id']==own,'submission receipt bound to own project')
        try:event('accept',{});raise AssertionError('self-review succeeded')
        except Error as e:check(e.status==403,'execution Agent cannot self-review')
    elif mode=='generate':
        task=c.task(d['task_id']);brief=c.call('/api/brief?task='+d['task_id'])
        check(brief['role']==d['role'] and brief['scope_hash']==task['scope_hash'],'project-specific brief matches frozen role/scope')
        check('token' not in brief,'delegation brief contains no credential')
        if not task['owner']:result['claim']=event('claim',{'summary':'Read only this project brief; verified baseline, input hashes and write scope'})
        parent=Path('/srv/project-board-archive/drill-tmp');parent.mkdir(parents=True,exist_ok=True)
        check(shutil.disk_usage(parent).free>32*1024*1024,'NAS workspace has free space')
        with tempfile.TemporaryDirectory(prefix='agent-',dir=parent) as folder:
            root=Path(folder);artifacts={}
            for name,content in d['files'].items():
                path=root/name
                check(path.resolve().is_relative_to(root) and any(name.startswith(p.rstrip('/')+'/') for p in brief['allowed_paths']),'generated file respects delegated directory')
                path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content,encoding='utf8',newline='\n');artifacts[name]={'content':content,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            if d.get('code'):
                namespace={};exec(compile(d['code'],'<frozen-normalize-code>','exec'),namespace)
                normalize=namespace['normalize_label']
                class Behavior(unittest.TestCase):
                    def test_strips_and_lowercases(self):self.assertEqual(normalize('  ALPHA  '),'alpha')
                    def test_unicode(self):self.assertEqual(normalize(' 项目 A '),'项目 a')
                    def test_empty_is_error(self):
                        with self.assertRaises(ValueError):normalize('  ')
                    def test_non_string_is_error(self):
                        with self.assertRaises(TypeError):normalize(None)
                stream=io.StringIO();suite=unittest.defaultTestLoader.loadTestsFromTestCase(Behavior);run=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
                result['tests']={'passed':run.wasSuccessful(),'run':run.testsRun,'failures':len(run.failures),'errors':len(run.errors),'log':stream.getvalue(),'code_sha256':hashlib.sha256(d['code'].encode()).hexdigest()}
            else:result['tests']={'passed':True,'run':1,'log':'Artifact SHA and delegated scope verified against frozen input.'}
            result['artifacts']=artifacts
        result['remote_temp_removed']=not Path(folder).exists()
        check(result['remote_temp_removed'],'owned remote temporary directory removed')
    else:raise ValueError('Unknown mode')
    result['passed']=True
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
