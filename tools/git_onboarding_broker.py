"""One NAS-controlled watcher for self-service repositories only.

Legacy project watchers keep their ownership. No project can select this
process's profile or commands. Only externally verified read-only entries run.
"""
import sys,json,time,signal,threading,argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from task_board.projects import ProjectHub
from task_board.git_tracking import Tracking
from task_board.git_onboarding import Onboarding
from tools.github_tracker import synchronize

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--state',type=Path,required=True);parser.add_argument('--profile',type=Path,required=True);parser.add_argument('--watch',action='store_true');args=parser.parse_args();hub=ProjectHub(args.state);stop=threading.Event();last={}
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    while not stop.is_set():
        try:
            profile=json.loads(args.profile.read_text('utf8'));identity=hub.resolve(profile['token'])
            if not identity['global_admin']:raise ValueError('Broker requires private instance maintenance identity')
            config=json.loads((args.state/'_private/github.json').read_text('utf8'))
            for pid,entries in config.get('projects',{}).items():
                store=hub.store(pid);tracking=Tracking(store);actor=hub.effective_actor(identity,pid)
                for rid,entry in entries.items():
                    if stop.is_set():break
                    if entry.get('authorization')!='github_verified_readonly_deploy_key':continue
                    repo=tracking.state()['repos'].get(rid)
                    if not repo or not repo['enabled']:continue
                    if Onboarding(store).status(rid).get('stage')=='verification_failed':continue
                    if repo['request']!=repo['synced_request'] or time.monotonic()-last.get((pid,rid),0)>60:
                        Onboarding(store).sync(actor,{'repo':rid},stop.is_set);last[(pid,rid)]=time.monotonic()
                        print(json.dumps({'project':pid,'repo':rid,'checked':True}),flush=True)
        except Exception as exc:print(json.dumps({'error':type(exc).__name__,'detail':'Broker check failed; inspect scoped onboarding status'}),flush=True)
        if not args.watch:break
        stop.wait(5)
if __name__=='__main__':main()
