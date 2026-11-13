"""NAS project-only GitHub read mirror. No add/commit/push or working tree.

Operator configuration is outside Git. Each repository uses its own read-only
deploy key. A failed fetch keeps the previous visible snapshot and error state.
"""
import argparse,json,os,shlex,signal,sys,threading,time,uuid,subprocess,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from task_board.projects import ProjectHub
from task_board.git_tracking import Tracking,repo_name,repo_id
from task_board.git_reader import Reader
from task_board.storage_boundary import reason
from task_board.store import BoardError
from tools.owned_process import run
from tools.runner_process import CommandGroup


def run_git(args,*,cwd,evidence,env,timeout,stop_requested):
    """Contain SSH children too, including service stop and network timeout."""
    import psutil
    evidence.mkdir(parents=True,exist_ok=True);group=CommandGroup();child=None;record={'command':['git',*args],'purpose':'Project GitHub read-only fetch','started':time.time()}
    try:
        with tempfile.TemporaryFile(dir=evidence) as out,tempfile.TemporaryFile(dir=evidence) as err:
            startup=None
            if os.name=='nt':startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=subprocess.SW_HIDE
            child=group.launch(record['command'],cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,shell=False,startupinfo=startup,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            record.update(pid=child.pid,created=psutil.Process(child.pid).create_time());deadline=time.monotonic()+timeout
            while child.poll() is None:
                if stop_requested():raise BoardError('同步已取消；旧快照保留',409)
                if time.monotonic()>deadline:raise BoardError('同步超时；旧快照保留',502)
                if os.fstat(out.fileno()).st_size>2*1024*1024 or os.fstat(err.fileno()).st_size>1024*1024:raise BoardError('同步输出超限',413)
                time.sleep(.05)
            if os.fstat(out.fileno()).st_size>2*1024*1024 or os.fstat(err.fileno()).st_size>1024*1024:raise BoardError('同步输出超限',413)
            out.seek(0);err.seek(0);return child.returncode,out.read(),err.read()
    finally:
        group.close();record.update(finished=time.time(),exit_code=child.returncode if child else None)
        with (evidence/'sync-processes.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(record)+'\n')


def synchronize(tracking,actor,rid,entry,stop_requested=lambda:False):
    lock=tracking.root/'git-mirrors'/tracking.project/(repo_id(rid)+'.lock');lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a+b') as handle:
        if os.name=='nt':
            import msvcrt
            handle.write(b'0');handle.flush();handle.seek(0)
            try:msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:raise BoardError('本项目仓库已有同步进程',409)
        else:
            import fcntl
            try:fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise BoardError('本项目仓库已有同步进程',409)
        try:return _synchronize(tracking,actor,rid,entry,stop_requested)
        finally:
            if os.name=='nt':handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


def _synchronize(tracking,actor,rid,entry,stop_requested=lambda:False):
    rid=repo_id(rid);v=tracking.state();repo=v['repos'][rid];repo_name(repo['repository'])
    if not repo['enabled'] or entry['repository']!=repo['repository']:raise BoardError('本机配置不匹配绑定',409)
    path=tracking.root/'git-mirrors'/tracking.project/(rid+'.git');e=path.parent/'audit'
    e.mkdir(parents=True,exist_ok=True);marker=path/'PROJECT-BOARD-MIRROR.json';expected={'project':tracking.project,'id':rid,'repository':repo['repository']}
    key=Path(entry['key']).resolve();private=(tracking.root/'_private').resolve()
    if not key.is_relative_to(private) or not key.is_file() or key.is_symlink():raise BoardError('密钥必须是实例私有目录下的普通文件')
    env={**os.environ,'GIT_TERMINAL_PROMPT':'0','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':os.devnull,
         'GIT_SSH_COMMAND':'ssh -F '+shlex.quote(os.devnull)+' -i '+shlex.quote(str(key))+' -o '+shlex.quote('UserKnownHostsFile="'+str(tracking.root/'_private/github-known-hosts')+'"')+' -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10','GIT_SSH_VARIANT':'ssh'}
    def git(args,timeout=60):
        code,out,err=run_git([str(a) for a in args],cwd=tracking.root,evidence=e,timeout=timeout,env=env,stop_requested=stop_requested)
        if code:raise BoardError('GitHub同步失败；检查NAS项目部署密钥、仓库授权和网络。旧快照保留',502)
        return out
    try:
        if path.exists():
            if not marker.exists() or json.loads(marker.read_text())!=expected:raise BoardError('拒绝使用归属不明的镜像')
        else:
            path.parent.mkdir(parents=True,exist_ok=True);git(['init','--bare','--quiet',str(path)]);marker.write_text(json.dumps(expected));os.chmod(path,0o700)
        if path.is_symlink() or path.parent.is_symlink():raise BoardError('镜像不能为链接')
        remote='git@github.com:'+repo['repository']+'.git'
        # A fixed remote URL and fixed refspec; never fetch arbitrary web input.
        git(['--git-dir='+str(path),'-c','core.hooksPath='+os.devnull,'-c','gc.auto=0','fetch','--quiet','--atomic','--prune','--no-recurse-submodules',remote,'+refs/heads/*:refs/heads/*','+refs/tags/*:refs/tags/*'],timeout=90)
        reader=Reader(path);refs={}
        for line in reader.git(['for-each-ref','--format=%(refname) %(objectname)','refs/heads/','refs/tags/']).decode().splitlines():
            name,h=line.split(' ',1)
            # Annotated tags are peeled to commits; non-commit tags are omitted.
            try:h=reader.git(['rev-parse','--verify',h+'^{commit}']).decode().strip()
            except BoardError:continue
            refs[name]=h
        symbolic=git(['ls-remote','--symref',remote,'HEAD'],timeout=30).decode().splitlines()
        default=next((line.split()[1] for line in symbolic if line.startswith('ref: ')),next(iter(refs),''))
        rewritten=[]
        for ref,old in repo['refs'].items():
            if ref in refs and refs[ref]!=old:
                try:ancestor=reader.git(['merge-base',old,refs[ref]]).decode().strip()
                except BoardError:ancestor=''
                if ancestor!=old:rewritten.append(ref)
        alerts=[]
        if default in refs:
            for f in reader.tree(refs[default]):
                why=reason(f['path'],v['policy']['patterns'],v['policy']['exceptions'])
                if why:alerts.append({'path':f['path'],'reason':why})
        payload={'repo':rid,'repository':repo['repository'],'request':repo['request'],'refs':refs,'error':'','default_branch':default,'alerts':alerts[:500],'rewritten':rewritten}
    except (BoardError,OSError,ValueError,TimeoutError) as error:
        payload={'repo':rid,'repository':repo['repository'],'request':repo['request'],'refs':{},'error':str(error)[:1000],'default_branch':'','alerts':[],'rewritten':[]}
    from task_board import lifecycle
    # Retry a revision conflict only if the immutable binding/request is unchanged.
    for _ in range(4):
        latest=tracking.state();current=latest['repos'].get(rid)
        if not current or current['repository']!=repo['repository'] or current['request']!=repo['request'] or not current['enabled']:raise BoardError('绑定已变化；不发布过期同步结果',409)
        lifecycle.write(path.parent/(rid+'.check.json'),{'repository':repo['repository'],'at':time.time(),'error':payload['error']})
        unchanged=(payload['error']==(current['sync_error'] or '') and current['synced_request']==payload['request'] and
                   (bool(payload['error']) or (current['refs']==payload['refs'] and current.get('default_branch')==payload['default_branch'] and current.get('alerts',[])==payload['alerts'] and not payload['rewritten'])))
        if unchanged:return {'revision':latest['revision'],'unchanged':True}
        try:return tracking.apply(actor,{'request_id':uuid.uuid4().hex,'expected_revision':latest['revision'],'action':'sync_result','payload':payload})
        except BoardError as error:
            if error.status!=409:raise
    raise BoardError('同步结果写入冲突',409)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state',type=Path,required=True);p.add_argument('--project',required=True);p.add_argument('--profile',type=Path,required=True);p.add_argument('--watch',action='store_true');args=p.parse_args()
    if os.name=='nt' and args.state.resolve().drive.casefold()=='c:':raise ValueError('状态和镜像不能放C盘')
    profile=json.loads(args.profile.read_text());assert profile['project_id']==args.project
    hub=ProjectHub(args.state);store=hub.store(args.project);actor=store.authenticate(profile['token']);tracking=Tracking(store)
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    last={}
    while not stop.is_set():
        try:
            profile=json.loads(args.profile.read_text());assert profile['project_id']==args.project
            actor=store.authenticate(profile['token'])
            entries=json.loads((args.state/'_private/github.json').read_text())['projects'].get(args.project,{})
            for rid,repo in tracking.state()['repos'].items():
                if stop.is_set():break
                if not repo['enabled'] or rid not in entries:continue
                if repo['request']!=repo['synced_request'] or time.monotonic()-last.get(rid,0)>=60:
                    synchronize(tracking,actor,rid,entries[rid],stop.is_set);last[rid]=time.monotonic()
                    print(json.dumps({'project':args.project,'repo':rid,'synced':not tracking.state()['repos'][rid]['sync_error']}),flush=True)
        except Exception as error:print(json.dumps({'error':type(error).__name__,'message':str(error)[:1000]}),flush=True)
        if not args.watch:break
        stop.wait(5)
if __name__=='__main__':main()
