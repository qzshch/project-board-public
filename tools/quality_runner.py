"""Trusted project runner. Approve exact suite hashes locally before --watch.

The HTTP service never runs commands. This worker exports a fixed commit into a
new owned directory, uses argv without a shell, renews leases, computes real
artifact digests and cleans its children and scratch on every exit path.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import platform
import subprocess
import sys
import tarfile
import time
import uuid
import psutil
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.task_board_client import Client,ClientError,suite_digest as digest
from tools.owned_process import run,remove_owned_tree
from tools.runner_process import CommandGroup


def post(client,action,payload):
    # A new request is prepared only after an explicit conflict response. A
    # transport failure retries the identical request ID to avoid duplicate jobs.
    for _ in range(4):
        snapshot=client.call('/api/operations');request={'request_id':uuid.uuid4().hex,'expected_revision':snapshot['revision'],'action':action,'payload':payload}
        for attempt in range(2):
            try:return client.call('/api/operations',request)
            except ClientError as error:
                if error.status==409:break
                if error.status or attempt:raise
        else:continue
    raise RuntimeError('Operations remained in conflict; no blind rebase')


def extract(archive,target):
    with tarfile.open(archive) as tar:
        entries=tar.getmembers()
        if len(entries)>20000 or sum(e.size for e in entries)>300*1024*1024:raise ValueError('Export exceeds runner limits')
        for e in entries:
            p=PurePosixPath(e.name)
            if p.is_absolute() or '..' in p.parts or ':' in e.name or '\\' in e.name or not (e.isfile() or e.isdir()):raise ValueError('Unsafe Git export entry')
            path=target.joinpath(*p.parts)
            if not path.resolve().is_relative_to(target.resolve()):raise ValueError('Export escaped scratch')
            if e.isdir():path.mkdir(parents=True,exist_ok=True)
            else:
                path.parent.mkdir(parents=True,exist_ok=True)
                with tar.extractfile(e) as src,path.open('wb') as out:
                    import shutil
                    shutil.copyfileobj(src,out)
                if os.name!='nt':os.chmod(path,e.mode & 0o777)


def execute(client,config,rid,stop_requested=lambda:False):
    # Host locks also serialize approved resources across different projects'
    # runners. Filenames reveal only a digest, never another project's identity.
    snapshot=client.call('/api/operations');job=snapshot['runs'][rid]
    lockroot=Path(config.get('resource_root',str(Path(config['scratch']).parent/'resource-locks'))).resolve()
    if os.name=='nt' and lockroot.drive.casefold()=='c:':raise ValueError('Resource lock cache must stay off C:')
    lockroot.mkdir(parents=True,exist_ok=True);handles=[]
    try:
        for resource in sorted(job['resources']):
            handle=(lockroot/hashlib.sha256(resource.encode()).hexdigest()).open('a+b');handles.append(handle)
            try:
                if os.name=='nt':
                    import msvcrt
                    handle.seek(0);handle.write(b'0');handle.flush();handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError:return {'run':rid,'status':'local_resource_busy'}
        return _execute(client,config,rid,stop_requested)
    finally:
        for handle in handles:handle.close()


def _execute(client,config,rid,stop_requested=lambda:False):
    workspace=Path(config['workspace']).resolve();scratch=Path(config['scratch']).resolve();output=Path(config['output']).resolve()
    if os.name=='nt' and any(p.drive.casefold()=='c:' for p in (workspace,scratch,output)):raise ValueError('Project workspace/cache must stay off C:')
    if scratch==workspace or scratch.is_relative_to(workspace) or workspace.is_relative_to(scratch):raise ValueError('Scratch and repository must be separate')
    scratch.mkdir(parents=True,exist_ok=True);output.mkdir(parents=True,exist_ok=True)
    snapshot=client.call('/api/operations');job=snapshot['runs'][rid];suite=snapshot['suites'][job['suite']];suite_hash=suite.pop('manifest_hash')
    if config['approved_suites'].get(job['suite'])!=suite_hash or digest(suite)!=suite_hash:raise ValueError('Suite not locally approved or manifest changed')
    if config['environment']!=job['environment']:raise ValueError('Runner environment differs from approved suite')
    claim=post(client,'run_claim',{'run':rid,'suite_hash':suite_hash});lease=claim['lease']['id'];nonce=uuid.uuid4().hex
    work=scratch/(rid+'-'+nonce);e=output/(rid+'-'+nonce);work.mkdir();e.mkdir();(work/'source').mkdir();code_root=work/'source'
    results=[];artifacts=[];status='blocked';summary='Runner setup failed';processes=[];child=None;group=None;last_heartbeat=time.monotonic();deadline=time.monotonic()+suite['timeout_seconds'];cancel=False
    def heartbeat(force=False):
        nonlocal last_heartbeat,cancel
        if force or time.monotonic()-last_heartbeat>=5:
            reply=post(client,'run_heartbeat',{'run':rid,'lease':lease});cancel=reply['cancel'];last_heartbeat=time.monotonic()
        return cancel
    def stop_child():
        if child is None:return
        if group is not None:group.close()
        try:
            p=psutil.Process(child.pid);record=next(r for r in processes if r['pid']==p.pid)
            if abs(p.create_time()-record['created'])>.01:return
            descendants=p.children(recursive=True)
            for x in reversed(descendants):
                try:x.terminate()
                except psutil.NoSuchProcess:pass
            if child.poll() is None:child.terminate()
            try:child.wait(5)
            except subprocess.TimeoutExpired:child.kill();child.wait(5)
            _,alive=psutil.wait_procs(descendants,timeout=5)
            for x in alive:
                try:x.kill()
                except psutil.NoSuchProcess:pass
            psutil.wait_procs(alive,timeout=5)
        except psutil.NoSuchProcess:pass
    try:
        commit=job['input_anchor'][4:]
        heartbeat(True)
        env={k:os.environ[k] for k in ('PATH','SystemRoot','WINDIR','PATHEXT','LANG','LD_LIBRARY_PATH') if k in os.environ}
        env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',PROJECT_BOARD_TEST_ROOT=str(work/'fixtures'),TMP=str(work/'tmp'),TEMP=str(work/'tmp'),TMPDIR=str(work/'tmp'),HOME=str(work/'home'),USERPROFILE=str(work/'home'),GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull)
        (work/'tmp').mkdir();(work/'home').mkdir()
        archive=work/'source.tar';code,out,err=run(['git','-C',workspace,'archive','--format=tar','--output',archive,commit],cwd=workspace,evidence=e,purpose='Export approved immutable test input',timeout=20)
        if code:raise RuntimeError('Requested Git input is not available in approved repository')
        extract(archive,code_root);heartbeat(True);status='passed';summary='Approved commands and artifact hashes completed'
        for i,command in enumerate(suite['commands']):
            if cancel or stop_requested() or time.monotonic()>=deadline:status='cancelled' if cancel or stop_requested() else 'timeout';summary='Execution cancelled or total timeout reached';break
            argv=[sys.executable if x=='{python}' else x for x in command['argv']]
            started=time.monotonic();log=e/f'case-{i}.log';startup=None
            if os.name=='nt':startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=subprocess.SW_HIDE
            with log.open('wb') as out:
                group=CommandGroup();child=group.launch(argv,cwd=code_root,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=subprocess.STDOUT,shell=False,startupinfo=startup,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                record={'pid':child.pid,'created':group.created,'command':argv,'purpose':command['case']};processes.append(record)
                case_status='passed'
                try:
                    while child.poll() is None:
                        try:
                            for descendant in psutil.Process(child.pid).children(recursive=True):
                                if not any(x['pid']==descendant.pid and x['created']==descendant.create_time() for x in processes):processes.append({'pid':descendant.pid,'created':descendant.create_time(),'command':descendant.cmdline(),'purpose':command['case']+' descendant'})
                        except psutil.NoSuchProcess:pass
                        if log.stat().st_size>20*1024*1024:raise RuntimeError('Case log exceeded 20 MiB limit')
                        if heartbeat() or stop_requested() or time.monotonic()>=deadline:
                            case_status='cancelled' if cancel or stop_requested() else 'timeout';stop_child();break
                        time.sleep(.1)
                    if child.returncode!=0 and case_status=='passed':case_status='failed'
                finally:
                    # Children may outlive a successful parent; they remain owned
                    # by this exact command and must not leak into the next case.
                    stop_child();record.update(exit_code=child.returncode,finished=time.time(),waited=child.poll() is not None)
                results.append({'case':command['case'],'status':case_status,'exit_code':child.returncode,'seconds':round(time.monotonic()-started,3),'summary':'See '+str(log)})
                if case_status!='passed':status=case_status;summary='Case '+command['case']+' '+case_status+'; see archived logs'
            child=None;group=None
        if status=='passed':
            for raw in suite['artifact_paths']:
                path=code_root/raw
                if path.is_symlink() or any(p.is_symlink() for p in path.parents if p!=code_root.parent) or not path.is_file() or not path.resolve().is_relative_to(code_root) or path.stat().st_size>20*1024*1024:raise ValueError('Artifact missing/linked/outside approved export')
                target=e/'artifacts'/raw;target.parent.mkdir(parents=True,exist_ok=True)
                import shutil
                shutil.copy2(path,target);artifacts.append({'path':raw,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'location':str(target)})
    except BaseException as error:
        status='blocked';summary=type(error).__name__+': '+str(error)
    finally:
        stop_child()
        alive=[]
        for record in processes:
            try:
                proc=psutil.Process(record['pid'])
                if os.name!='nt' and abs(proc.create_time()-record['created'])<.01 and proc.status()==psutil.STATUS_ZOMBIE:
                    try:os.waitpid(proc.pid,os.WNOHANG)
                    except ChildProcessError:pass
                if abs(proc.create_time()-record['created'])<.01 and proc.status()!=psutil.STATUS_ZOMBIE:alive.append(proc)
            except psutil.NoSuchProcess:pass
        _,alive=psutil.wait_procs(alive,timeout=5)
        for proc in alive:
            record=next(row for row in processes if row['pid']==proc.pid)
            try:
                if abs(proc.create_time()-record['created'])<.01:proc.kill()
            except psutil.NoSuchProcess:pass
        _,alive=psutil.wait_procs(alive,timeout=5)
        if alive:status='blocked';summary+='; owned descendants did not exit'
        for record in processes:
            try:
                proc=psutil.Process(record['pid']);record['exited']=abs(proc.create_time()-record['created'])>.01 or proc.status()==psutil.STATUS_ZOMBIE
            except psutil.NoSuchProcess:record['exited']=True
        # Missing cases are explicit non-passes, never silently skipped.
        seen={r['case'] for r in results}
        for command in suite['commands']:
            if command['case'] not in seen:results.append({'case':command['case'],'status':'blocked','exit_code':-1,'seconds':0,'summary':summary})
        try:
            if alive:raise RuntimeError('Owned processes still hold scratch '+str(work))
            remove_owned_tree(work,scratch)
        except Exception as error:status='blocked';summary+='; cleanup failed: '+str(error)
        (e/'processes.json').write_text(json.dumps(processes,indent=2),encoding='utf8')
        logs={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in e.glob('case-*.log')};(e/'logs.sha256.json').write_text(json.dumps(logs,indent=2),encoding='utf8')
        body={'run':rid,'lease':lease,'status':status,'results':results,'artifacts':artifacts,'evidence':[{'path':str(e/name),'sha256':hashlib.sha256((e/name).read_bytes()).hexdigest()} for name in ('processes.json','logs.sha256.json')],'environment':platform.platform()+'; Python '+platform.python_version(),'summary':summary}
        (e/'result.json').write_text(json.dumps(body,ensure_ascii=False,indent=2),encoding='utf8')
        try:
            if heartbeat(True):body['status']='cancelled';status='cancelled'
            (e/'result.json').write_text(json.dumps(body,ensure_ascii=False,indent=2),encoding='utf8')
            receipt=post(client,'run_finish',body);(e/'receipt.json').write_text(json.dumps(receipt),encoding='utf8')
        except Exception as error:(e/'UNCONFIRMED.txt').write_text(str(error),encoding='utf8');raise
    return {'run':rid,'status':status,'evidence':str(e)}


def main():
    import signal,threading
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profile',type=Path,required=True);p.add_argument('--config',type=Path,required=True);p.add_argument('--connect-ip');p.add_argument('--run');p.add_argument('--watch',action='store_true');a=p.parse_args()
    profile=json.loads(a.profile.read_text('utf8'));config=json.loads(a.config.read_text('utf8'));client=Client(profile['url'],profile,a.connect_ip)
    stop=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    while not stop.is_set():
        try:
            snapshot=client.call('/api/operations');jobs=[a.run] if a.run else [rid for rid,r in snapshot['runs'].items() if (r['status']=='queued' or (r['status']=='running' and r['lease']['expires']<=time.time())) and config['approved_suites'].get(r['suite'])==r['suite_hash']]
            for rid in jobs:
                if stop.is_set():break
                print(json.dumps(execute(client,config,rid,stop.is_set)),flush=True)
        except Exception as error:
            if not a.watch:raise
            print(json.dumps({'error':type(error).__name__,'detail':str(error)}),flush=True)
        if not a.watch:break
        stop.wait(5)
if __name__=='__main__':main()
