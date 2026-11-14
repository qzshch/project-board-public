"""Finite project event consumption; no agent launch or resource reclamation."""
import argparse,json,sys,uuid,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.task_board_client import Client

def atomic_json(path,value):
    path=Path(path)
    if os.name=='nt' and path.resolve().drive.casefold()=='c:':raise ValueError('Project outputs must be outside C drive')
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+'.writing')
    try:tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(path)
    finally:
        if tmp.exists():tmp.unlink()

def consume(client,consumer,output,processed=False):
    """At-least-once local delivery. Stable event IDs allow consumer deduplication.

    A durable pending request is replayed exactly after lost acknowledgements.
    Processing is explicit; printing a message never marks an obstacle solved.
    """
    output=Path(output);output.mkdir(parents=True,exist_ok=True);state=output/'CURSOR.json';pending=output/'ACK.json'
    binding={'project':client.project,'actor':client.profile['actor'],'consumer':consumer}
    old=json.loads(state.read_text('utf8')) if state.exists() else {**binding,'cursor':''}
    if any(old.get(k)!=v for k,v in binding.items()):raise ValueError('Cursor directory belongs to another project, identity or consumer')
    if pending.exists():
        request=json.loads(pending.read_text('utf8'));client.call('/api/operations',request);pending.unlink()
    from urllib.parse import urlencode
    batch=client.call('/api/coordination/feed?'+urlencode({'cursor':old['cursor'],'limit':100}))
    # Archive immutable batches before advancing any delivery cursor.
    batch_path=output/('batch-'+uuid.uuid4().hex+'.json');atomic_json(batch_path,batch)
    for status in (('delivered','read','processed') if processed else ('delivered',)):
        snapshot=client.call('/api/operations');request={'request_id':uuid.uuid4().hex,'expected_revision':snapshot['revision'],'action':'consumer_ack','payload':{'consumer':consumer,'cursor':batch['cursor'],'state':status}}
        atomic_json(pending,request);client.call('/api/operations',request);pending.unlink()
    atomic_json(state,{**binding,'cursor':batch['cursor']});return batch

def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);p.add_argument('--consumer',default='worker');p.add_argument('--output',required=True);p.add_argument('--processed',action='store_true');p.add_argument('--task');p.add_argument('--context',action='store_true');p.add_argument('--since',default='');p.add_argument('--connect-ip');a=p.parse_args();profile=json.loads(Path(a.profile).read_text('utf8'));c=Client(profile['url'],profile,a.connect_ip)
    if a.context and not a.task:p.error('--context requires --task')
    if a.task:
        from urllib.parse import quote
        endpoint='/api/convergence/context?task=' if a.context else '/api/coordination?task='
        data=c.call(endpoint+quote(a.task,safe='')+('&since='+quote(a.since,safe='') if a.context and a.since else ''));atomic_json(Path(a.output)/('CONTEXT.json' if a.context else 'RESUME.json'),data);print(json.dumps({'task':a.task,**({'sha256':data['sha256'],'has_more':data['changes']['has_more']} if a.context else {'resume':data['resume']})},ensure_ascii=False))
    else:
        batch=consume(c,a.consumer,a.output,a.processed);print(json.dumps({'events':len(batch['items']),'has_more':batch['has_more']},ensure_ascii=False))
if __name__=='__main__':main()
