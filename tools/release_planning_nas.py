"""Bounded NAS-only source release with consistent backup and actual rollback.

Production task/governance data are read only throughout. Isolated Linux tests
run before the service is stopped. The retained checkpoint is private.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.owned_process import run
from task_board import lifecycle
from tools.task_board_client import Client

ROOT=Path(__file__).resolve().parents[1]
NAS='/srv/project-board'
SMB=Path('//example-owner/Project Workspace/project-board')
URL='http://example-server.example-tailnet.ts.net:18785'
E=ROOT/'evidence/planning-20261113'


def main():
    E.mkdir(exist_ok=True)
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT),'Commit exact candidate before deployment'
    name='planning-'+commit[:12];source=NAS+'/releases/'+name+'/source';stage=SMB/'releases'/name/'source'
    assert not stage.exists(),'Release is immutable; use a new commit for another candidate'
    files=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0');manifest={}
    for relative in filter(None,files):
        p=ROOT/relative;target=stage/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
        manifest[relative]=hashlib.sha256(p.read_bytes()).hexdigest()
        assert hashlib.sha256(target.read_bytes()).hexdigest()==manifest[relative]
    lifecycle.write(E/'SOURCE.json',{'commit':commit,'source':source,'files':manifest})
    report={'complete':False,'commit':commit,'source':source,'url':URL,'started':time.time()}
    def remote(script,purpose,timeout=100):
        code,out,err=run(['ssh','-i','C:/Users/example-user/.ssh/nas_key','-o','BatchMode=yes','-o','ConnectTimeout=8','-o','StrictHostKeyChecking=yes','example-owner@192.0.2.10',shlex.quote(NAS+'/.venv/bin/python')+' -B -X utf8 -'],input_data=script.encode('utf8'),cwd=ROOT,evidence=E,purpose=purpose,timeout=timeout)
        if code:
            (E/('remote-failure-'+str(time.time_ns())+'.log')).write_bytes(out+err)
            raise RuntimeError(err.decode('utf8',errors='replace')[-1800:])
        return json.loads(out)
    # The NAS test suite writes only new, owned release-local fixtures and
    # records child identities. No production identities are used by fixtures.
    preflight=remote(f'''import sys,json,os
from pathlib import Path
source=Path({source!r});sys.path.insert(0,str(source/'tools'))
from owned_process import run
e=source/'evidence/linux-planning';e.mkdir(parents=True)
code,out,err=run([{NAS!r}+'/.venv/bin/python','-B','-X','utf8','tools/run_checks.py'],cwd=source,evidence=e,purpose='NAS isolated full planning regression',timeout=160)
(e/'stdout.log').write_bytes(out);(e/'stderr.log').write_bytes(err)
assert code==0,(out+err).decode('utf8',errors='replace')[-1400:]
print(json.dumps({{'passed':True,'result':out.decode().strip(),'evidence':str(e)}}))
''','validate isolated Linux candidate before any production mutation',190)
    report['linux_tests']=preflight
    lifecycle.write(E/'LINUX-TESTS.json',preflight)
    remote_report=remote(f'''import sys,json,hashlib,socket,time,os
from pathlib import Path
root=Path({NAS!r});source=Path({source!r});state=root/'state';sys.path[:0]=[str(source),str(source/'tools')]
from task_board import lifecycle
from task_board.projects import ProjectHub
from task_board.governance import Governance
from task_board_client import Client
from owned_process import run
from migrate import clone_stopped
e=source/'evidence/release';e.mkdir(parents=True)
unit=root/'deploy/project-board.service';original=unit.read_text('utf8')
oldsource=lifecycle.read(state/'connection.json')['code_root'];assert oldsource in original,'Unexpected service source'
newunit=original.replace(oldsource,str(source));assert newunit!=original
profile=lifecycle.read(state/'_private/admin.json');client=Client('http://127.0.0.1:24710',{{**profile,'url':'http://127.0.0.1:24710'}})
def anchors():
 projects=client.call('/api/projects')['projects']
 return {{p['id']:{{'task_head':client.call('/api/projects/'+p['id']+'/snapshot')['head'],'governance_head':client.call('/api/projects/'+p['id']+'/governance')['head']}} for p in projects}}
before=anchors();assert set(before)=={{'sampleapp','task-board'}};old_schema=client.call('/health')['governance_schema'];assert old_schema in (1,2)
secrets_before={{str(p.relative_to(state)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (state/'_private').rglob('*.json') if p.name not in ('server.json',)}}
def command(args,purpose):
 code,out,err=run(args,cwd=source,evidence=e,purpose=purpose,timeout=30)
 if code:raise RuntimeError(err.decode('utf8',errors='replace')[-1000:])
 return out
def service(action):command(['systemctl','--user',action,'project-board.service'],'owned NAS service '+action)
def readiness(schema):
 for _ in range(60):
  try:
   health=client.call('/health')
   if health.get('governance_schema')==schema and anchors()==before:return health
  except Exception:pass
  time.sleep(.2)
 raise RuntimeError('NAS readiness/head verification timeout')
def install(text):
 service('stop');unit.write_text(text,encoding='utf8');command(['systemctl','--user','daemon-reload'],'reload only NAS user units');service('start')
backup=root/'backups'/({name!r}+'-before')/'state';report={{'before':before,'old_source':oldsource,'backup':str(backup),'complete':False}}
try:
 service('stop')
 with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',24710))!=0,'Backend still active'
 assert lifecycle.read(state/'service.json').get('closed'),'Graceful service stop not recorded'
 assert not backup.exists(),'Backup must not overwrite previous checkpoint'
 copied=clone_stopped(state,backup);report['backup_files']=len(copied)
 # Backups contain credentials and are never included in a public source kit.
 os.chmod(backup.parent,0o700)
 unit.write_text(newunit,encoding='utf8');command(['systemctl','--user','daemon-reload'],'load candidate NAS unit');service('start');report['candidate']=readiness(2)
 install(original);report['rollback']=readiness(old_schema)
 install(newunit);report['restored_candidate']=readiness(2)
 service('restart');report['restart']=readiness(2)
 after=anchors();assert after==before
 secrets_after={{str(p.relative_to(state)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (state/'_private').rglob('*.json') if p.name not in ('server.json',)}}
 assert secrets_before==secrets_after,'Project identity files changed'
 hub=ProjectHub(state);assert hub.verify()['passed']
 for project in before:assert Governance(hub.store(project)).verify()['passed']
 connection=lifecycle.read(state/'connection.json');connection.update(code_root=str(source),code_commit={commit!r},client_script=str(source/'tools/task_board_client.py'),governance_version=2);lifecycle.write(state/'connection.json',connection)
 report.update(complete=True,after=after,credentials_preserved=True,service=lifecycle.read(state/'service.json'),finished=time.time())
finally:
 if not report['complete']:
  install(original);report['failure_restored_old_source']=readiness(old_schema)
 lifecycle.write(e/'RESULT.json',report)
print(json.dumps(report))
''','NAS backup, candidate switch, actual source rollback, restart and chain validation',150)
    report.update(remote_report);lifecycle.write(E/'DEPLOYMENT.json',report)
    print(json.dumps({'complete':report['complete'],'source':source,'backup':report['backup'],'url':URL,'heads_preserved':report['before']==report['after']}))
if __name__=='__main__':main()
