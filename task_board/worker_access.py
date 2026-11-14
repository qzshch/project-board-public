"""Project opt-in recruitment. Registration and membership commit together.

The token's project prefix is a routing hint, never authority: every request
still authenticates its full hash against that project's actor table. No global
credential, enrollment secret, or pre-issued worker file is needed.
"""
import re,time
from .store import BoardError,fields,text,digest,canonical
from .projects import project_id,token_hash

def setup(db):
    db.execute('CREATE TABLE IF NOT EXISTS worker_joins(actor TEXT PRIMARY KEY, request_id TEXT NOT NULL, request_hash TEXT NOT NULL, receipt TEXT NOT NULL)')

def entry(hub,pid):
    from .governance import load
    meta=hub.metadata(pid)
    with hub.store(pid).connection() as db:g=load(db)
    if not g.get('worker_access',{}).get('enabled'):raise BoardError('项目未开放自助加入',404)
    return {'project_id':pid,'name':meta['name'],'worker_self_service':True,'role':'worker','guide':'/help/worker-start','client':'/client.py','join_endpoint':'/api/projects/'+pid+'/worker-join'}

def join(hub,pid,token,p):
    from .governance import load
    from .convergence import gov_append
    import json
    fields(p,{'request_id','actor'},{'request_id','actor'})
    rid=text(p['request_id'],'请求ID',100);actor=text(p['actor'],'Worker ID',48)
    if not re.fullmatch(r'worker-[a-z0-9-]{2,40}',actor):raise BoardError('自助身份需唯一worker-前缀，不复用owner或SE名称')
    if type(token) is not str or not re.fullmatch(r'worker\.'+re.escape(pid)+r'\.[A-Za-z0-9_-]{43,86}',token):raise BoardError('需要客户端生成的本项目Worker私有身份',401)
    store=hub.store(project_id(pid));hashed=token_hash(token)
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE');g=load(db)
        old=db.execute('SELECT * FROM worker_joins WHERE actor=?',(actor,)).fetchone()
        existing=db.execute('SELECT token_hash FROM actors WHERE id=?',(actor,)).fetchone()
        if old:
            if not existing or existing['token_hash']!=hashed:raise BoardError('Worker身份不匹配或已撤销',401)
            if old['request_id']!=rid or old['request_hash']!=digest(p):raise BoardError('加入请求已固定，请复用原身份及请求',409)
            # Closing recruitment prevents new joins, not readback of committed
            # receipts. Replay never writes membership or revives a revoked key.
            return {**json.loads(old['receipt']),'replayed':True}
        if not g.get('worker_access',{}).get('enabled'):raise BoardError('项目未开放自助加入',404)
        if existing:raise BoardError('身份已存在，不能覆盖',409)
        db.execute('INSERT INTO actors VALUES(?,?,?)',(actor,'agent',hashed))
        db.execute('INSERT INTO actor_audit(actor,action,operator,reason,created) VALUES(?,?,?,?,?)',(actor,'registered',actor,'project Worker self-service; policy '+g['head'],time.time()))
        state=gov_append(store,db,{'id':actor,'role':'agent'},'worker_join',{'actor':actor,'policy_head':g['head']})
        receipt={'project_id':pid,'actor':actor,'role':'agent','project_role':'worker','joined':True,'replayed':False,'request_id':rid,'governance_revision':state.get('revision',g['revision']+1)}
        db.execute('INSERT INTO worker_joins VALUES(?,?,?,?)',(actor,rid,digest(p),canonical(receipt)));db.commit()
    return receipt
