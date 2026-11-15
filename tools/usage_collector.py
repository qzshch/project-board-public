"""Durable metadata-only project usage spool; replay the exact saved record.

Codex's verified tokenUsage notification is normalized here. Other runtimes can
import authored normalized observations; unsupported fields stay unknown. No
account-wide history scan or retroactive attribution of an attached chat.
"""
import hashlib, json, threading, time, argparse
from pathlib import Path
from tools.task_board_client import save,read,Client,ClientError

class Spool:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True,mode=0o700);self.lock=threading.RLock()
        # Recover a crash between saving an observation and its stream head.
        recovered={}
        for path in self.root.glob('*.observation.json'):
            item=read(path);p=item['observation'];key=p['epoch']
            head=recovered.setdefault(key,{'ordinal':0,'last_signature':None})
            if p['ordinal']>=head['ordinal']:head.update(ordinal=p['ordinal'],last_signature=item.get('signature'))
        for key,state in recovered.items():save(self.root/(key+'.head.json'),state)
    def capture(self,frame,binding,session,created=False):
        if binding['runtime']!='codex' or frame.get('method')!='thread/tokenUsage/updated':return False
        p=frame.get('params',{})
        if p.get('threadId')!=session:return False
        counts=p.get('tokenUsage',{}).get('total')
        if not isinstance(counts,dict):return False
        total={'input':counts.get('inputTokens'),'output':counts.get('outputTokens'),'cache_read':counts.get('cachedInputTokens'),'cache_write':None,'reasoning':counts.get('reasoningOutputTokens')}
        # This epoch is a locally persisted counter stream, not a model turn.
        key=hashlib.sha256((binding['project']+'|'+binding['id']+'|'+session).encode()).hexdigest()
        with self.lock:
            head=self.root/(key+'.head.json');state=read(head) if head.exists() else {'ordinal':0,'last_signature':None}
            signature=hashlib.sha256(json.dumps([p.get('turnId'),total],sort_keys=True).encode()).hexdigest()
            sample=key+'-'+signature
            if (self.root/(sample+'.observation.json')).exists():return False
            state['ordinal']+=1;record={'sample':sample,'revision':1,'session':session,'task':binding.get('task',''),'phase':'governance' if binding['role']=='se' else 'implementation','model':binding['model'],'source':'observed','mode':'cumulative','epoch':key,'ordinal':state['ordinal'],'from_start':bool(created),'occurred':time.time(),'counters':total,'origin':{'path':str(self.root/(sample+'.observation.json')),'sha256':hashlib.sha256(json.dumps(frame,sort_keys=True).encode()).hexdigest()}}
            source=self.root/(sample+'.source.json');save(source,frame);record['origin']={'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
            path=self.root/(sample+'.observation.json');save(path,{'project':binding['project'],'binding':binding['id'],'signature':signature,'observation':record});state['last_signature']=signature;save(head,state)
            return True
    def flush(self,clients):
        with self.lock:
            for path in self.root.glob('*.observation.json'):
                item=read(path);client=clients.get(item['binding'])
                if not client:continue
                ack=path.with_suffix('.ack.json')
                if ack.exists():continue
                try:result=client.call('/api/usage',item['observation']);save(ack,result)
                except ClientError as exc:
                    # Credentials and payloads never enter the diagnostic.
                    save(path.with_suffix('.error.json'),{'status':exc.status,'at':time.time(),'retry':'exact frozen observation'})

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--profile',required=True);parser.add_argument('--file',required=True);args=parser.parse_args();client=Client(read(args.profile)['url'],read(args.profile))
    # Import explicit per-project normalized records only, never entire account exports.
    for line in Path(args.file).read_text('utf8').splitlines():
        if line.strip():print(json.dumps(client.call('/api/usage',json.loads(line))))
if __name__=='__main__':main()
