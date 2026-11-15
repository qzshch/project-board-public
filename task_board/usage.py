"""Small, project-local append-only usage ledger, separate from state snapshots.

Amounts are observations, never billing claims. No prompts, messages or provider
credentials are accepted. Revisions replace a sample for reporting, not history.
"""
import json, time, math
from collections import defaultdict
from .store import BoardError, fields, text, digest, canonical

COUNTERS=('input','output','cache_read','cache_write','reasoning')

def setup(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS token_usage(
      seq INTEGER PRIMARY KEY, actor TEXT NOT NULL, sample TEXT NOT NULL,
      revision INTEGER NOT NULL, payload TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL,
      UNIQUE(actor,sample,revision));
      CREATE TRIGGER IF NOT EXISTS token_usage_no_update BEFORE UPDATE ON token_usage BEGIN SELECT RAISE(ABORT,'append only'); END;
      CREATE TRIGGER IF NOT EXISTS token_usage_no_delete BEFORE DELETE ON token_usage BEGIN SELECT RAISE(ABORT,'append only'); END;''')
    db.execute("CREATE INDEX IF NOT EXISTS token_usage_stream ON token_usage(actor,json_extract(payload,'$.observation.session'),json_extract(payload,'$.observation.source'),json_extract(payload,'$.observation.epoch'),json_extract(payload,'$.observation.ordinal'))")

def normalize_counters(value):
    fields(value,set(COUNTERS),set(COUNTERS))
    for key,n in value.items():
        if n is not None and (type(n) is not int or not 0<=n<=10**15):raise BoardError('Token计数需非负整数或null')
    if value['input'] is not None and any(value[k] is not None and value[k]>value['input'] for k in ('cache_read','cache_write')):raise BoardError('缓存是输入子集，不能超过输入')
    if value['output'] is not None and value['reasoning'] is not None and value['reasoning']>value['output']:raise BoardError('推理是输出子集')
    return value

class Usage:
    def __init__(self,store):
        self.store=store
        with store.connection() as db:setup(db)

    def head(self,actor):
        from .governance import role
        with self.store.connection() as db:
            role(db,actor);row=db.execute('SELECT seq,hash FROM token_usage ORDER BY seq DESC LIMIT 1').fetchone()
        return {'revision':row['seq'] if row else 0,'head':row['hash'] if row else '0'*64}

    def append(self,actor,p):
        from .governance import role, tasks
        from .operations import load
        fields(p,{'sample','revision','session','task','phase','model','source','mode','epoch','ordinal','from_start','occurred','counters','origin','attribution'}, {'sample','revision','session','task','phase','model','source','mode','epoch','ordinal','from_start','occurred','counters','origin'})
        p={**p,'attribution':p.get('attribution','bound_task' if p['task'] else 'project_overhead')}
        if p['attribution'] not in ('bound_task','project_overhead','unattributed') or bool(p['task'])!=(p['attribution']=='bound_task'):raise BoardError('任务归因需与任务ID对应；项目协调与未归因分开登记')
        for k in ('sample','session','phase','model','epoch'):text(p[k],k,256)
        if type(p['task']) is not str or len(p['task'])>160:raise BoardError('任务ID无效')
        if p['source'] not in ('observed','imported','manual','estimated') or p['mode'] not in ('call','cumulative'):raise BoardError('采集来源/模式无效')
        if type(p['revision']) is not int or p['revision']<1 or type(p['ordinal']) is not int or p['ordinal']<0 or type(p['from_start']) is not bool:raise BoardError('样本版本/次序/基线无效')
        if type(p['occurred']) not in (int,float) or not math.isfinite(p['occurred']) or not 0<p['occurred']<=time.time()+300:raise BoardError('发生时间无效')
        normalize_counters(p['counters'])
        fields(p['origin'],{'path','sha256'},{'path','sha256'});text(p['origin']['path'],'本地受控来源',1000)
        import re
        if not re.fullmatch('[0-9a-f]{64}',str(p['origin']['sha256'])):raise BoardError('来源摘要无效')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');r=role(db,actor)
            if r in ('viewer','tracker','runner','restorer'):raise BoardError('此身份不能上报模型用量',403)
            if p['task']:
                t=tasks(db).get(p['task'])
                if not t:raise BoardError('本项目任务不存在',404)
            elif r not in ('owner','se','reviewer'):raise BoardError('项目协调用量需SE身份',403)
            v=load(db);refs=[*v.get('session_registry',{}).values(),*v.get('cv_sessions',{}).values()]
            session=next((x for x in refs if x.get('session')==p['session'] and x.get('actor')==actor['id']),None)
            hub=self.store.registry.hub
            with hub.connection() as catalog:
                managed=catalog.execute('SELECT definition FROM orch_bindings WHERE project=? AND actor=? AND session=?',(self.store.registry.project,actor['id'],p['session'])).fetchone()
            if managed:
                bound=json.loads(managed['definition']);session={'session':p['session'],'actor':actor['id'],'tasks':[bound['task']] if bound.get('task') else []}
            if not session:raise BoardError('先登记属于本项目和本身份的原生Session ID',409)
            allowed=session.get('tasks',[session.get('task')])
            if p['task'] and p['task'] not in allowed:raise BoardError('会话不属于上报任务',403)
            # The immutable owned session records its original task authority.
            # Late usage may arrive after assignment changes; it grants no
            # execution, submission or review rights on that task.
            old=db.execute('SELECT * FROM token_usage WHERE actor=? AND sample=? AND revision=?',(actor['id'],p['sample'],p['revision'])).fetchone()
            if old:
                if json.loads(old['payload'])['observation']!=p:raise BoardError('样本ID/版本绑定其他内容',409)
                return {'seq':old['seq'],'hash':old['hash'],'replayed':True}
            latest=db.execute('SELECT * FROM token_usage WHERE actor=? AND sample=? ORDER BY revision DESC LIMIT 1',(actor['id'],p['sample'])).fetchone()
            if not latest:
                prior=db.execute("SELECT payload FROM token_usage WHERE actor=? AND json_extract(payload,'$.observation.session')=? AND json_extract(payload,'$.observation.source')=? LIMIT 1",(actor['id'],p['session'],p['source'])).fetchone()
                if prior and json.loads(prior['payload'])['observation']['mode']!=p['mode']:raise BoardError('同一会话来源不可同时累计与逐调用相加；选择一种口径',409)
                if p['mode']=='cumulative' and db.execute("SELECT 1 FROM token_usage WHERE actor=? AND json_extract(payload,'$.observation.session')=? AND json_extract(payload,'$.observation.source')=? AND json_extract(payload,'$.observation.epoch')=? AND json_extract(payload,'$.observation.ordinal')=? LIMIT 1",(actor['id'],p['session'],p['source'],p['epoch'],p['ordinal'])).fetchone():raise BoardError('累计流次序已存在，使用原样本修订',409)
            if latest:
                before=json.loads(latest['payload'])['observation']
                if p['revision']!=latest['revision']+1 or any(before[k]!=p[k] for k in ('session','task','mode','epoch','ordinal','source')):raise BoardError('样本修订需接续原归属和版本',409)
            elif p['revision']!=1:raise BoardError('新样本从版本1开始',409)
            last=db.execute('SELECT seq,hash FROM token_usage ORDER BY seq DESC LIMIT 1').fetchone();seq=last['seq']+1 if last else 1;prev=last['hash'] if last else '0'*64
            event={'observation':p,'received':time.time()};h=digest({'seq':seq,'actor':actor['id'],'event':event,'previous':prev})
            db.execute('INSERT INTO token_usage VALUES(?,?,?,?,?,?,?)',(seq,actor['id'],p['sample'],p['revision'],canonical(event),prev,h));db.commit();return {'seq':seq,'hash':h}

    def report(self,actor):
        from .governance import role
        from .operations import load
        with self.store.connection() as db:
            db.execute('BEGIN');role(db,actor);rows=db.execute('SELECT * FROM token_usage ORDER BY seq').fetchall();v=load(db)
        latest={};previous='0'*64;valid=True
        for row in rows:
            event=json.loads(row['payload']);valid &= row['prev_hash']==previous and digest({'seq':row['seq'],'actor':row['actor'],'event':event,'previous':previous})==row['hash'];previous=row['hash']
            latest[(row['actor'],row['sample'])]={'actor':row['actor'],'seq':row['seq'],**event}
        records=list(latest.values());groups=defaultdict(list);normalized=[]
        for row in records:
            p=row['observation']
            if p['mode']=='cumulative':groups[(row['actor'],p['session'],p['source'],p['epoch'])].append(row)
            else:normalized.append({**row,'amounts':p['counters'],'baseline_only':False,'anomaly':False})
        for group in groups.values():
            group.sort(key=lambda x:(x['observation']['ordinal'],x['seq']));before=None;seen=set()
            for row in group:
                p=row['observation'];counts=p['counters'];baseline=before is None and not p['from_start'];anomaly=p['ordinal'] in seen;seen.add(p['ordinal'])
                amounts={}
                for k,n in counts.items():
                    old=before[k] if before else 0
                    bad=n is not None and old is not None and n<old
                    anomaly |= bad
                    amounts[k]=None if baseline or n is None or old is None or bad else n-old
                normalized.append({**row,'amounts':amounts,'baseline_only':baseline,'anomaly':anomaly});before=counts
        buckets={};observed_sessions=set()
        for row in normalized:
            p=row['observation'];key=(p['source'],p['task'],p['phase'],p['model'],p.get('attribution','bound_task' if p['task'] else 'project_overhead'));b=buckets.setdefault(key,{'source':key[0],'task':key[1],'phase':key[2],'model':key[3],'attribution':key[4],'counts':{k:0 for k in COUNTERS},'unknown':{k:0 for k in COUNTERS},'samples':0,'anomalies':0})
            b['samples']+=1;b['anomalies']+=int(row['anomaly'])
            if p['source']=='observed':observed_sessions.add(p['session'])
            for k,n in row['amounts'].items():
                if n is None:b['unknown'][k]+=1
                else:b['counts'][k]+=n
        refs=[*v.get('session_registry',{}).values(),*v.get('cv_sessions',{}).values()]
        with self.store.registry.hub.connection() as catalog:
            refs += [dict(row) for row in catalog.execute('SELECT session FROM orch_bindings WHERE project=?',(self.store.registry.project,))]
        known={x['session'] for x in refs if x.get('session')}
        from .product import snapshot
        visible=snapshot(self.store,actor)['items']
        with self.store.connection() as db:
            from .governance import tasks
            task_modules={tid:t['spec'].get('work',{}).get('planning',{}).get('module') or 'unassigned' for tid,t in tasks(db).items()}
        return {'revision':len(rows),'head':previous,'chain_valid':bool(valid),'buckets':list(buckets.values()),'samples':normalized,'task_modules':task_modules,'requirements':{k:e.get('tasks',[]) for k,e in visible.items() if e.get('product_kind')=='requirement'},'coverage':{'known_project_sessions':len(known),'observed_sessions':len(observed_sessions & known),'missing_sessions':sorted(known-observed_sessions),'unknown_session_refs':sum(not x.get('session') for x in refs)},'semantics':'input + output only; cache/reasoning subsets; observed lower bound; imported/manual/estimated separate; first attached cumulative observation is baseline; requirement rows overlap, never sum them'}
