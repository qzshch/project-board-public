"""One bounded PC-to-NAS cutover, with exact ownership and offline cleanup."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from task_board import lifecycle
from task_board_client import Client
from tools.cleanup_rehearsal import cleanup
from tools.migrate import clone_stopped
from tools.owned_process import run

ROOT=Path(__file__).resolve().parents[1];E=ROOT/'evidence/nas-ui-20261113'
NAS='/srv/project-board';SOURCE=NAS+'/releases/nas-20261113/source';PUBLIC='http://example-server.example-tailnet.ts.net:18785';IP='100.64.0.10';SMB=Path('//example-owner/Project Workspace/project-board')

def main():
    state=ROOT/'state';report={'complete':False,'started':time.time(),'canonical_url':PUBLIC,'nas_root':NAS};nas_started=False;pc_stopped=False;nas_proxy=False;compat=False
    def command(args,purpose,timeout=40):
        code,out,err=run(args,cwd=ROOT,evidence=E,purpose=purpose,timeout=timeout)
        if code:raise RuntimeError(err.decode('utf8',errors='replace')[:1200])
        return out
    def remote(code,purpose):
        return command(['ssh','-i','C:/Users/example-user/.ssh/nas_key','-o','BatchMode=yes','-o','ConnectTimeout=8','-o','StrictHostKeyChecking=yes','example-owner@192.0.2.10','python3 -c '+shlex.quote(code)],purpose)
    def ts(args):return command(['C:/Program Files/Tailscale/tailscale.exe','serve',*args],'preserve owned PC compatibility proxy')
    oldsettings=lifecycle.read(state/'_private/server.json');oldprofile=lifecycle.read(state/'_private/admin.json');local=Client('http://127.0.0.1:24710',{**oldprofile,'url':'http://127.0.0.1:24710'})
    real=['sampleapp','task-board'];before={p:local.call('/api/projects/'+p+'/snapshot')['head'] for p in real};report['before_heads']=before
    before_proxy=json.loads(ts(['status','--json']));report['pc_proxy_before']=before_proxy
    try:
        lifecycle.stop(state);pc_stopped=True
        checkpoint=E/'_private/before-nas';stage=E/'_private/clean-state';target=SMB/'state'
        from task_board.projects import ProjectHub
        assert {p:ProjectHub(state).store(p).head() for p in real}==before,'Concurrent source write; retry from a new checkpoint'
        if target.exists():
            previous=lifecycle.read(E/'DEPLOYMENT.json')
            assert previous.get('rolled_back_to_pc') and previous.get('after_heads')==before and previous['cleanup']['passed'],'Unknown candidate cannot be resumed'
            report['cleanup']=previous['cleanup'];report['resumed_verified_clean_candidate']=True
        else:
            assert not checkpoint.exists() and not stage.exists()
            clone_stopped(state,checkpoint);clone_stopped(checkpoint,stage)
            report['cleanup']=cleanup(stage,lifecycle.read(E/'REHEARSAL-MANIFEST.json'));assert report['cleanup']['preserved_heads']==before
            for path in (stage/'_private').glob('recovery-key-*.json'):path.unlink()
            shutil.copytree(stage,target)
        settings=lifecycle.read(target/'_private/server.json');settings.update(public_url=PUBLIC,proxy_hosts=['example-server.example-tailnet.ts.net:18785',*settings.get('proxy_hosts',[])],allowed_origins=list(dict.fromkeys([PUBLIC,*settings.get('allowed_origins',[])])),project_state=NAS+'/state',access_log=NAS+'/state/access.jsonl',network_ownership={'configured':False,'managed_by':'NAS systemd user service and NAS Tailscale Serve','connect_ip':IP,'backend':'http://127.0.0.1:24710'},maintenance_read_only=False)
        lifecycle.write(target/'_private/server.json',settings)
        for profile in (target/'_private').rglob('*.json'):
            if profile.name=='server.json':continue
            data=lifecycle.read(profile)
            if 'url' in data:data['url']=PUBLIC;lifecycle.write(profile,data)
        connection=lifecycle.read(target/'connection.json');connection.update(url=PUBLIC,local_url='http://127.0.0.1:24710',code_root=SOURCE,client_script=SOURCE+'/tools/task_board_client.py',state=NAS+'/state');lifecycle.write(target/'connection.json',connection)
        remote(f'''from pathlib import Path
import os,json,subprocess,socket
root=Path({NAS!r});source=Path({SOURCE!r});state=root/'state'
with socket.socket() as s:
 s.settimeout(.3);assert s.connect_ex(('127.0.0.1',24710))!=0,'NAS backend port already owned'
unit=root/'deploy/project-board.service';unit.parent.mkdir(exist_ok=True);(root/'tmp').mkdir(exist_ok=True)
unit.write_text('[Unit]\\nDescription=WeftBoard - Agentic Project Board\\nAfter=network-online.target\\n\\n[Service]\\nType=simple\\nWorkingDirectory='+str(source)+'\\nExecStart="'+str(root/'.venv/bin/python')+'" -B -X utf8 "'+str(source/'tools/task_board.py')+'" --state "'+str(state)+'" serve\\nRestart=on-failure\\nRestartSec=3\\nTimeoutStopSec=20\\nUMask=0077\\nEnvironment=PYTHONDONTWRITEBYTECODE=1\\nEnvironment="TMPDIR='+str(root/'tmp')+'"\\nNoNewPrivileges=yes\\n\\n[Install]\\nWantedBy=default.target\\n',encoding='utf8')
link=Path.home()/'.config/systemd/user/project-board.service';link.parent.mkdir(parents=True,exist_ok=True)
assert not link.exists() and not link.is_symlink(),'Unknown existing service unit'
link.symlink_to(unit)
for args in [['systemctl','--user','daemon-reload'],['systemctl','--user','enable','--now','project-board.service']]:subprocess.run(args,check=True,capture_output=True,timeout=15)
print(json.dumps({{'unit':str(unit),'enabled':True}}))
''','enable persistent NAS user service without PC dependency');nas_started=True
        # The NAS has its own canonical Serve handler. Preserve every existing
        # NAS handler; never reset the Tailscale daemon or Serve configuration.
        proxy_result=remote('''import subprocess,json
base=['docker','exec','tailscale','tailscale','serve'];before=json.loads(subprocess.check_output(base+['status','--json']))
assert '18785' not in before.get('TCP',{}),'Unknown NAS port owner'
subprocess.run(base+['--http=18785','--set-path=/','--bg','--yes','http://127.0.0.1:24710'],check=True,capture_output=True,timeout=15)
after=json.loads(subprocess.check_output(base+['status','--json']))
other=json.loads(json.dumps(after));other.get('TCP',{}).pop('18785',None);other.get('Web',{}).pop('example-server.example-tailnet.ts.net:18785',None)
for key in ('TCP','Web'):
 if not other.get(key):other.pop(key,None)
assert other==before
print(json.dumps({'before':before,'after':after}))
''','configure only NAS project-board private port');nas_proxy=True;report['nas_proxy']=json.loads(proxy_result)
        nasprofile={**oldprofile,'url':PUBLIC};client=Client(PUBLIC,nasprofile,IP)
        for _ in range(40):
            try:projects=client.call('/api/projects')['projects'];break
            except Exception:time.sleep(.2)
        else:raise RuntimeError('NAS service readiness timed out')
        assert {p['id'] for p in projects}==set(real)
        after={p:client.call('/api/projects/'+p+'/snapshot')['head'] for p in real};assert before==after
        assert client.call('/api/projects/task-board/shared')['releases']==[]
        assert client.call('/api/projects/task-board/governance')['assets']=={}
        report['after_heads']=after
        remote("import subprocess; subprocess.run(['systemctl','--user','restart','project-board.service'],check=True,timeout=20)",'restart NAS service to prove durable state')
        for _ in range(40):
            try:
                restarted={p:client.call('/api/projects/'+p+'/snapshot')['head'] for p in real}
                if restarted==before:break
            except Exception:pass
            time.sleep(.2)
        else:raise RuntimeError('NAS restart readback failed')
        report['restart_heads']=restarted
        # The user explicitly moved the product to the NAS. Retire the PC
        # address rather than keeping an application or relay on the PC.
        after_proxy=json.loads(ts(['status','--json']))
        for port in ('18781','18783'):
            assert before_proxy.get('TCP',{}).get(port)==after_proxy.get('TCP',{}).get(port)
            host='DEVELOPMENT-HOST.example-tailnet.ts.net:'+port;assert before_proxy.get('Web',{}).get(host)==after_proxy.get('Web',{}).get(host)
        report['pc_proxy_after']=after_proxy
        lifecycle.write(state/'MIGRATED_TO.json',{'url':PUBLIC,'state':NAS+'/state','pc_application_stopped':True,'previous_pc_url_retired':True})
        report.update(complete=True,previous_pc_url=oldsettings['public_url'],persistent_host='example-server',remaining_projects=real,finished=time.time())
    finally:
        if not report['complete']:
            if compat:ts(['--http=18785','--set-path=/','off'])
            if nas_started:remote("import subprocess; subprocess.run(['systemctl','--user','disable','--now','project-board.service'],check=True,timeout=20)",'rollback failed NAS service')
            if nas_proxy:remote("import subprocess; subprocess.run(['docker','exec','tailscale','tailscale','serve','--http=18785','--set-path=/','off'],check=True,timeout=15)",'rollback only owned NAS proxy')
            if pc_stopped:lifecycle.start(state)
            report['rolled_back_to_pc']=True
        lifecycle.write(E/'DEPLOYMENT.json',report)
    print(json.dumps({'complete':True,'url':PUBLIC,'remaining_projects':real,'heads_preserved':before==after,'pc_application_stopped':True}))
if __name__=='__main__':main()
