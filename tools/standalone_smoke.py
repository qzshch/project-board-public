"""Actual empty installation, scoped identity, restart and finally cleanup."""
import hashlib
import json
import socket
from pathlib import Path
import shutil
import sys
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from task_board import lifecycle
from task_board_client import Client,ClientError
from owned_process import remove_owned_tree
ROOT=Path(__file__).resolve().parents[1]

def main():
    E=ROOT/'evidence/standalone'/time.strftime('%Y%m%d-%H%M%S');E.mkdir(parents=True);state=E/'temporary-state';report={'checks':[]};started=False
    def check(ok,label):
        if not ok:raise AssertionError(label)
        report['checks'].append(label)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    url='http://127.0.0.1:'+str(port)
    try:
        lifecycle.init_state(state,public_url=url,port=port);r=lifecycle.start(state);started=True;report['owner']=lifecycle.read(state/'service.json')
        admin=Client(url,lifecycle.read(state/'_private/admin.json'));check(admin.call('/api/projects')['projects']==[],'empty startup imports no business projects')
        check(lifecycle.start(state)['reused'],'second start reuses exact instance')
        admin.call('/api/projects',{'id':'blank-product','name':'Blank independent product','description':'No source business repository or planning import'})
        profile=admin.call('/api/projects/blank-product/actors',{'actor':'fresh-dev'});agent=Client(url,{**profile,'url':url})
        check([x['id'] for x in agent.call('/api/projects')['projects']]==['blank-product'],'fresh Agent grant contains only newly created project')
        try:agent.call('/api/projects/sampleapp/snapshot');raise AssertionError('unexpected default game project')
        except ClientError as e:check(e.status==404,'legacy game project is absent and inaccessible')
        spec={'id':'dev/one','title':'Independent empty installation test','kind':'atomic','description':'Exercise API without source business fixtures','deliverables':[{'id':'D1','label':'runtime proof'}],'allowed_paths':['src/one/'],'registered':True,'claimable':True,'work':{'category':'backend','role':'agent','inputs_known':True,'inputs':['frozen specification'],'outputs':['proof'],'contracts':[],'assets':[],'resources':[],'couplings':[],'baseline':'a'*40,'acceptance':'new project identity and durable task readback'}}
        prefix='/api/projects/blank-product'
        admin.call(prefix+'/events',{'request_id':str(uuid.uuid4()),'task_id':'dev/one','action':'create','expected_revision':0,'payload':{'spec':spec,'reason':'empty initialization runtime proof'}})
        t=agent.task('dev/one');receipt=agent.call('/api/events',{'request_id':str(uuid.uuid4()),'task_id':'dev/one','action':'claim','expected_revision':t['revision'],'scope_version':t['scope_version'],'payload':{'summary':'Only this project input and delegated paths'}})
        before=agent.call('/api/snapshot')['head'];lifecycle.stop(state);started=False;lifecycle.start(state);started=True
        check(agent.call('/api/snapshot')['head']==before,'full process restart retains new project task and event chain')
        check(agent.call('/api/receipt?id='+receipt['event_id'])['event']['hash']==receipt['event_hash'],'original Agent credential and receipt survive restart')
        check(admin.call(prefix+'/verify')['passed'],'empty-install task chain verifies independently')
        report.update(passed=True,head=before,port=port,identity_reused=True)
    finally:
        if started:lifecycle.stop(state)
        for name in ('service.json','start.json','lifecycle.jsonl'):
            if (state/name).exists():shutil.copy2(state/name,E/name)
        if state.exists():remove_owned_tree(state,E)
        report['temporary_state_removed']=not state.exists();lifecycle.write(E/'RESULT.json',report)
    print(json.dumps({'passed':True,'checks':len(report['checks']),'evidence':str(E),'temporary_state_removed':report['temporary_state_removed']}))
if __name__=='__main__':main()
