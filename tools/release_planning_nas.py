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
os.environ['PATH']={NAS!r}+'/.venv/bin:'+os.environ.get('PATH','/usr/bin:/bin')
from owned_process import run
e=source/'evidence/linux-planning';e.mkdir(parents=True)
code,out,err=run([{NAS!r}+'/.venv/bin/python','-B','-X','utf8','tools/run_checks.py'],cwd=source,evidence=e,purpose='NAS isolated full planning regression',timeout=330)
(e/'stdout.log').write_bytes(out);(e/'stderr.log').write_bytes(err)
assert code==0,(out+err).decode('utf8',errors='replace')[-1400:]
print(json.dumps({{'passed':True,'result':out.decode().strip(),'evidence':str(e)}}))
''','validate isolated Linux candidate before any production mutation',360)
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
 return {{p['id']:{{'task_head':client.call('/api/projects/'+p['id']+'/snapshot')['head'],'governance_head':client.call('/api/projects/'+p['id']+'/governance/verify')['head']}} for p in projects}}
before=anchors();assert {{'sampleapp','task-board'}}<=set(before);old_schema=client.call('/health')['governance_schema'];assert old_schema in (1,2)
secrets_before={{str(p.relative_to(state)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (state/'_private').rglob('*.json') if p.name not in ('server.json',)}}
def command(args,purpose):
 code,out,err=run(args,cwd=source,evidence=e,purpose=purpose,timeout=30)
 if code:raise RuntimeError(err.decode('utf8',errors='replace')[-1000:])
 return out
def service(action):command(['systemctl','--user',action,'project-board.service'],'owned NAS service '+action)

# A Git mirror is runtime data, so its project synchronizer must also stop
# before the consistent checkpoint. Only units owned by this instance qualify.
git_units=[]
chain_prefixes=None
def prefixes_preserved():
 if chain_prefixes is None:return anchors()==before
 # Other projects can legitimately append as soon as any candidate/rollback
 # instance is online. Verify frozen immutable prefixes instead of forbidding
 # those writes or mistaking them for a failed source switch.
 for pid,storage in projects:
  path=state/storage;assert path.resolve().is_relative_to(state.resolve()) and not path.is_symlink()
  with sqlite3.connect(str(path)) as db:
   for table,head in chain_prefixes[pid].items():
    if head['seq'] and db.execute('SELECT hash FROM '+table+' WHERE seq=?',(head['seq'],)).fetchone()!=(head['hash'],):return False
 return True
listed=command(['systemctl','--user','list-units','--type=service','--state=active','--plain','--no-legend','project-board-git-*.service'],'identify only active instance Git synchronizers').decode().splitlines()
for line in listed:
 name=line.split()[0];p=root/'deploy'/name
 assert name.startswith('project-board-git-') and name.endswith('.service') and p.is_file() and 'tools/github_tracker.py' in p.read_text(),'Unknown Git service ownership'
 git_units.append(name)
def readiness(schema):
 for _ in range(60):
  try:
   health=client.call('/health')
   if health.get('governance_schema')==schema and prefixes_preserved():return health
  except Exception:pass
  time.sleep(.2)
 raise RuntimeError('NAS readiness/head verification timeout')
def install(text):
 service('stop');unit.write_text(text,encoding='utf8');command(['systemctl','--user','daemon-reload'],'reload only NAS user units');service('start')
backup=root/'backups'/({name!r}+'-before')/'state';report={{'before':before,'old_source':oldsource,'backup':str(backup),'complete':False}}
try:
 for name in git_units:command(['systemctl','--user','stop',name],'pause owned Git synchronizer for consistent backup')
 service('stop')
 with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',24710))!=0,'Backend still active'
 assert lifecycle.read(state/'service.json').get('closed'),'Graceful service stop not recorded'
 assert not backup.exists(),'Backup must not overwrite previous checkpoint'
 copied=clone_stopped(state,backup);report['backup_files']=len(copied)
 # Freeze the authoritative baseline after stop, including legitimate writes
 # completed between the online observation and shutdown. No candidate schema
 # is created until the consistent checkpoint exists.
 import sqlite3
 with sqlite3.connect(str(state/'projects.sqlite')) as catalog:projects=catalog.execute('SELECT id,storage FROM projects').fetchall()
 stable={{}};chain_prefixes={{}}
 for pid,storage in projects:
  with sqlite3.connect(str(state/storage)) as data:
   chain_prefixes[pid]={{}}
   for table in ('events','governance_events','operations_events','git_events'):
    row=data.execute('SELECT seq,hash FROM '+table+' ORDER BY seq DESC LIMIT 1').fetchone() or (0,'0'*64)
    chain_prefixes[pid][table]={{'seq':row[0],'hash':row[1]}}
   seq,h=data.execute('SELECT seq,hash FROM events ORDER BY seq DESC LIMIT 1').fetchone() or (0,'0'*64)
   gov=data.execute('SELECT hash FROM governance_events ORDER BY seq DESC LIMIT 1').fetchone()
   stable[pid]={{'task_head':{{'seq':seq,'hash':h}},'governance_head':gov[0] if gov else '0'*64}}
 report['observed_before_stop']=before;before=stable;report['before']=before
 report['frozen_prefixes']=chain_prefixes
 # Backups contain credentials and are never included in a public source kit.
 os.chmod(backup.parent,0o700)
 unit.write_text(newunit,encoding='utf8');command(['systemctl','--user','daemon-reload'],'load candidate NAS unit');service('start');report['candidate']=readiness(2)
 install(original);report['rollback']=readiness(old_schema)
 install(newunit);report['restored_candidate']=readiness(2)
 service('restart');report['restart']=readiness(2)
 after=anchors();assert prefixes_preserved();report['chain_prefixes_preserved']=True
 secrets_after={{str(p.relative_to(state)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (state/'_private').rglob('*.json') if p.name not in ('server.json',)}}
 assert secrets_before==secrets_after,'Project identity files changed'
 hub=ProjectHub(state);assert hub.verify()['passed']
 from task_board.operations import Operations
 from task_board.git_tracking import Tracking
 for project in before:
  assert Governance(hub.store(project)).verify()['passed']
  assert Operations(hub.store(project)).verify()['passed']
  assert Tracking(hub.store(project)).verify()['passed']
 connection=lifecycle.read(state/'connection.json');connection.update(code_root=str(source),code_commit={commit!r},client_script=str(source/'tools/task_board_client.py'),governance_version=2,operations_schema=1);lifecycle.write(state/'connection.json',connection)
 report.update(complete=True,after=after,credentials_preserved=True,service=lifecycle.read(state/'service.json'),finished=time.time())
finally:
 if not report['complete']:
  install(original);report['failure_restored_old_source']=readiness(old_schema)
 for name in git_units:command(['systemctl','--user','start',name],'resume original instance Git synchronizer')
 lifecycle.write(e/'RESULT.json',report)
print(json.dumps(report))
''','NAS backup, candidate switch, actual source rollback, restart and chain validation',150)
    report.update(remote_report);lifecycle.write(E/'DEPLOYMENT.json',report)
    print(json.dumps({'complete':report['complete'],'source':source,'backup':report['backup'],'url':URL,'heads_preserved':report['chain_prefixes_preserved']}))
if __name__=='__main__':main()
