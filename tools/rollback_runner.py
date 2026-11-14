"""Execute one frozen project rollback with separately approved local targets.

The API host and Git tracker remain read-only. This tool creates a candidate
bundle, never pushes. Deployment argv/release maps come only from a private
operator file, not from a task, comment, web request or downloaded artifact.
"""
import argparse,hashlib,json,os,re,sys,time,uuid,subprocess,psutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.owned_process import run,remove_owned_tree
from tools.task_board_client import Client,save,ClientError
from tools.quality_runner import post
from tools.runner_process import CommandGroup

def bounded(argv,cwd,env,destination,index,timeout):
    """A job/process-group boundary also reaps children after successful exit."""
    group=CommandGroup();child=None;record={'command':argv,'purpose':'Locally approved exact-plan rollback','started':time.time()}
    startup=None
    if os.name=='nt':
        startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=subprocess.SW_HIDE
    try:
        with (destination/('command-'+str(index)+'.out')).open('wb') as out,(destination/('command-'+str(index)+'.err')).open('wb') as err:
            child=group.launch(argv,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,shell=False,startupinfo=startup,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            record.update(pid=child.pid,created=psutil.Process(child.pid).create_time());child.wait(timeout)
    finally:
        group.close()
        if child is not None:child.wait(5)
        record.update(exit_code=child.returncode if child else None,finished=time.time())
        with (destination/'processes.jsonl').open('a',encoding='utf8') as h:h.write(json.dumps(record)+'\n')
    return child.returncode,(destination/('command-'+str(index)+'.out')).read_bytes(),(destination/('command-'+str(index)+'.err')).read_bytes()

def execute(client,config,rid):
    if config['project_id']!=client.project:raise ValueError('Local approval belongs to a different project')
    plan=client.call('/api/workflow')['rollbacks'][rid]
    if config['approved_plans'].get(rid)!=plan['manifest_hash']:raise ValueError('Exact rollback manifest not locally approved')
    scratch=Path(config['scratch']).resolve();output=Path(config['output']).resolve()
    if scratch==output or scratch.is_relative_to(output) or output.is_relative_to(scratch):raise ValueError('Scratch/output must be separate')
    if os.name=='nt' and any(p.drive.casefold()=='c:' for p in (scratch,output)):raise ValueError('Project scratch/output must stay off C:')
    scratch.mkdir(parents=True,exist_ok=True);output.mkdir(parents=True,exist_ok=True);destination=output/rid
    # A lost result reply must never run the real rollback for a second time.
    if destination.exists():
        pending=destination/'FINISH.json'
        if pending.is_file():return client.call('/api/operations',json.loads(pending.read_text('utf8')))
        raise ValueError('Existing output needs SE recovery; do not repeat side effects')
    claim=post(client,'rollback_claim',{'id':rid,'manifest_hash':plan['manifest_hash']});lease=claim['lease']['id'];latest_revision=claim['revision'];destination.mkdir();work=scratch/(rid+'-'+uuid.uuid4().hex);work.mkdir()
    status='failed';commit='';summary='Setup failed';fallback=None;effects_started=False;steps=[]
    temporary=work/'tmp';temporary.mkdir()
    env={**os.environ,'TMP':str(temporary),'TEMP':str(temporary),'TMPDIR':str(temporary),'GIT_CONFIG_GLOBAL':os.devnull,'GIT_CONFIG_NOSYSTEM':'1','GIT_TERMINAL_PROMPT':'0','GIT_OPTIONAL_LOCKS':'0','GIT_NO_REPLACE_OBJECTS':'1','GIT_EDITOR':'true','GIT_AUTHOR_NAME':'Project rollback executor','GIT_AUTHOR_EMAIL':'rollback@project.invalid','GIT_COMMITTER_NAME':'Project rollback executor','GIT_COMMITTER_EMAIL':'rollback@project.invalid'}
    recovering=False
    def heartbeat():
        nonlocal latest_revision
        try:reply=post(client,'rollback_heartbeat',{'id':rid,'lease':lease})
        except (ClientError,RuntimeError):
            if recovering:return
            raise
        latest_revision=reply['revision']
        if reply['cancel'] and not recovering:raise ValueError('SE requested cancellation')
    def command(argv,cwd,timeout=90):
        if type(argv) is not list or not argv or any(type(x) is not str or not x or '\x00' in x for x in argv):raise ValueError('Local argv must be a nonempty string array')
        heartbeat();index=len(steps);stdout=destination/('command-'+str(index)+'.out');stderr=destination/('command-'+str(index)+'.err')
        code,out,err=bounded(argv,cwd,env,destination,index,timeout)
        steps.append({'index':index,'argv_sha256':hashlib.sha256(json.dumps(argv).encode()).hexdigest(),'exit_code':code,'stdout_sha256':hashlib.sha256(out).hexdigest(),'stderr_sha256':hashlib.sha256(err).hexdigest()})
        if code:raise ValueError('Approved command failed; see retained local log '+str(index))
        heartbeat();return out.decode('utf8','replace').strip()
    def git(args,cwd):return command(['git','-c','core.hooksPath='+os.devnull,'-c','core.fsmonitor=false',*args],cwd)
    try:
        if plan['commits']:
            repo=Path(config['repositories'][plan['repo']]['path']).resolve()
            if not repo.is_dir() or repo.is_symlink() or repo==scratch or scratch.is_relative_to(repo):raise ValueError('Invalid operator-approved source repository')
            source=work/'source';git(['clone','--quiet','--no-hardlinks','--no-checkout',str(repo),str(source)],work);git(['checkout','--quiet','--detach',plan['base']],source)
            if git(['rev-parse','HEAD'],source)!=plan['base'] or git(['status','--porcelain'],source):raise ValueError('Fixed base not clean')
            order=[c for c in git(['rev-list','--topo-order',plan['base']],source).splitlines() if c in plan['commits']]
            if set(order)!=set(plan['commits']):raise ValueError('Rollback commit is not in approved local history')
            for c in order:
                args=['revert','--no-edit'];main=plan['mainlines'].get(c)
                if main is not None:args+=['-m',str(main)]
                git(args+[c],source)
            commit=git(['rev-parse','HEAD'],source)
            if not config.get('checks'):raise ValueError('Local rollback verification commands required')
            for argv in config['checks']:command([sys.executable if x=='{python}' else x for x in argv],source,120)
            if git(['status','--porcelain','--untracked-files=no'],source):raise ValueError('Checks changed tracked candidate contents')
            branch='rollback/'+rid;git(['branch',branch,commit],source)
            git(['bundle','create',str(destination/'candidate.bundle'),branch,'^'+plan['base']],source)
            summary='Reverse commits and locally approved checks passed; candidate bundle retained. No push, merge or deployment performed.';status='prepared'
        elif plan['kind']=='deploy':
            target=config['deployments'][plan['object']];release=target['releases'][plan['target']]
            if release.get('compatible') is not True:raise ValueError('Operator must explicitly approve data/schema compatibility')
            before=json.loads(command(target['probe_argv'],work));expected=target['expected_current']
            if before.get('release')!=expected:raise ValueError('Live deployment differs from locally approved current release')
            fallback=target['releases'][expected];effects_started=True
            command(release['argv'],work);after=json.loads(command(target['probe_argv'],work))
            if after.get('release')!=plan['target'] or after.get('commit')!=release['commit']:raise ValueError('Deployment readback mismatch')
            commit=after['commit'];summary='Locally approved deployment switched and probe readback verified; data compatibility explicitly approved by operator';status='prepared'
        else:raise ValueError('Task/module/asset metadata recovery is applied by SE, not executor')
    except BaseException as error:
        summary=str(error)[:2000]
        if effects_started and fallback is not None:
            try:
                recovering=True
                command(fallback['argv'],work);probe=json.loads(command(target['probe_argv'],work))
                if probe.get('release')!=target['expected_current'] or probe.get('commit')!=fallback['commit']:raise ValueError('Fallback readback mismatch')
                summary+='; original deployment restored and read back'
            except BaseException as restore:status='needs_recovery';summary+='; FALLBACK NEEDS OPERATOR: '+str(restore)[:500]
    finally:
        try:remove_owned_tree(work,scratch)
        except BaseException as cleanup:status='needs_recovery';summary+='; owned scratch retained: '+str(cleanup)[:500]
    proof={'project_id':client.project,'rollback':rid,'manifest_hash':plan['manifest_hash'],'status':status,'commit':commit,'summary':summary,'steps':steps,'finished':time.time(),'scratch_remaining':work.exists(),'trust':'project-authorized local executor attestation, not remote hardware proof'};save(destination/'RESULT.json',proof)
    artifacts=[{'path':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'location':str(p)} for p in destination.iterdir() if p.is_file() and p.name in ('RESULT.json','candidate.bundle','processes.jsonl')]
    payload={'id':rid,'lease':lease,'status':status,'commit':commit,'summary':summary,'evidence':[{'path':str(destination/'RESULT.json'),'sha256':hashlib.sha256((destination/'RESULT.json').read_bytes()).hexdigest()}],'artifacts':artifacts}
    request={'request_id':uuid.uuid4().hex,'expected_revision':latest_revision,'action':'rollback_finish','payload':payload};save(destination/'FINISH.json',request)
    # The durable file is the only retry source. A 409 requires an explicit SE
    # decision; do not repeat execution or silently rewrite the result request.
    for attempt in range(2):
        try:return client.call('/api/operations',request)
        except ClientError as error:
            if error.status or attempt:raise

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profile',type=Path,required=True);p.add_argument('--config',type=Path,required=True);p.add_argument('--id',required=True);args=p.parse_args()
    config=json.loads(args.config.read_text('utf8'));profile=json.loads(args.profile.read_text('utf8'));client=Client(config['url'],profile,config.get('connect_ip'));result=execute(client,config,args.id);print(json.dumps({'rollback':args.id,'result':result}))
if __name__=='__main__':main()
