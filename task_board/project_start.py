"""One named-project grant becomes the caller-held owner credential at creation.

Before creation the token is accepted only by the bound bootstrap endpoint.
No owner secret is returned over HTTP and no existing project can be adopted.
The catalog publishes project, credential mapping and grant completion together.
"""
import json,re,secrets,time,uuid
from pathlib import Path
from .store import BoardError,fields,text,integer,digest
from .projects import project_id,token_hash

def prepare(db):
    db.execute('''CREATE TABLE IF NOT EXISTS se_starts(project TEXT PRIMARY KEY,
        token_hash TEXT NOT NULL UNIQUE,actor TEXT NOT NULL,request_id TEXT NOT NULL,
        request_hash TEXT NOT NULL,created REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS project_grants(
        project TEXT PRIMARY KEY,token_hash TEXT NOT NULL UNIQUE,actor TEXT NOT NULL,
        grant_id TEXT NOT NULL UNIQUE,created REAL NOT NULL,expires REAL NOT NULL,
        issue_request TEXT NOT NULL,issue_hash TEXT NOT NULL,reason TEXT NOT NULL,
        revoked REAL,request_id TEXT,request_hash TEXT,completed REAL)''')

def issue(hub,identity,value,public_url):
    if not identity['global_admin']:raise BoardError('开通授权只能由实例授权者签发',403)
    keys={'request_id','project_id','actor','ttl_seconds','reason'};fields(value,keys,keys)
    rid=text(value['request_id'],'签发请求ID',100);pid=project_id(value['project_id']);actor=value['actor']
    if type(actor) is not str or not re.fullmatch('[a-z][a-z0-9_-]{1,47}',actor) or actor=='root':raise BoardError('需非root的有限项目Actor')
    integer(value['ttl_seconds'],'首次开通有效秒数',60)
    if value['ttl_seconds']>604800:raise BoardError('首次开通授权最多7天')
    text(value['reason'],'授权依据',4000);hashed=digest(value);path=hub.state/'_private/project-grants'/str(pid+'.json')
    with hub.connection() as db:
        db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT * FROM project_grants WHERE project=?',(pid,)).fetchone()
        if old:
            if old['issue_request']!=rid or old['issue_hash']!=hashed:raise BoardError('该项目已签发授权；复用原私有文件，不能静默轮换',409)
            if old['revoked']:raise BoardError('开通授权已撤销',403)
            profile=json.loads(path.read_text('utf8'))
            if token_hash(profile['token'])!=old['token_hash']:raise BoardError('私有授权文件与目录不符',409)
            return profile
        if db.execute('SELECT 1 FROM projects WHERE id=? UNION SELECT 1 FROM removed_projects WHERE id=?',(pid,pid)).fetchone():raise BoardError('项目已存在或已退役，不能用开通授权接管',409)
        now=time.time()
        if path.exists():
            # A signing response/write may be interrupted before catalog commit.
            # Reuse only the exact issuer request's exclusively-created file.
            profile=json.loads(path.read_text('utf8'))
            if profile.get('issue_request')!=rid or profile.get('issue_hash')!=hashed:raise BoardError('私有授权文件已存在，未覆盖',409)
            if profile.get('project_id')!=pid or profile.get('actor')!=actor:raise BoardError('授权文件绑定不符',409)
        else:
            profile={'url':public_url,'actor':actor,'role':'agent','project_role':'owner','project_id':pid,'token':secrets.token_urlsafe(32),'global_admin':False,'capability':'create-bound-project','grant_id':uuid.uuid4().hex,'grant_created':now,'grant_expires':now+value['ttl_seconds'],'issue_request':rid,'issue_hash':hashed}
            hub.write_private(path,profile)
        db.execute('INSERT INTO project_grants VALUES(?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL)',(pid,token_hash(profile['token']),actor,profile['grant_id'],profile['grant_created'],profile['grant_expires'],rid,hashed,value['reason']))
        hub.audit(db,'project_grant',pid,identity['actor']['id'],{'actor':actor,'grant_id':profile['grant_id'],'expires':profile['grant_expires'],'reason':value['reason']});db.commit()
        return profile

def revoke(hub,identity,value):
    if not identity['global_admin']:raise BoardError('需要实例授权者',403)
    fields(value,{'project_id','grant_id','reason'},{'project_id','grant_id','reason'});pid=project_id(value['project_id']);text(value['grant_id'],'授权ID',100);text(value['reason'],'撤销依据',4000)
    with hub.connection() as db:
        db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT * FROM project_grants WHERE project=?',(pid,)).fetchone()
        if not row or row['grant_id']!=value['grant_id']:raise BoardError('当前授权不存在',404)
        if not row['revoked']:
            db.execute('UPDATE project_grants SET revoked=? WHERE project=?',(time.time(),pid));hub.audit(db,'project_grant_revoke',pid,identity['actor']['id'],{'grant_id':row['grant_id'],'reason':value['reason']});db.commit()
    return {'revoked':True,'project_id':pid,'owner_identity_unchanged':True}

def grant(db,token,pid,rid,hashed):
    row=db.execute('SELECT * FROM project_grants WHERE token_hash=?',(token_hash(token),)).fetchone()
    if not row:raise BoardError('需要本项目的有效开通授权',401)
    if row['project']!=pid:raise BoardError('授权不属于此项目',404)
    if row['revoked']:raise BoardError('开通授权已撤销',403)
    if not row['completed'] and row['expires']<=time.time():raise BoardError('首次开通授权已过期',403)
    if row['request_id'] and (row['request_id']!=rid or row['request_hash']!=hashed):raise BoardError('授权已绑定另一份创建请求；保留原请求并核对',409)
    return row

def validate_seed(hub,db,seed,pid):
    row=grant(db,seed['token'],pid,seed['request_id'],seed['request_hash'])
    if row['completed']:raise BoardError('项目已完成创建，请读取原回执',409)
    return row

def bootstrap(hub,pid,token,value):
    pid=project_id(pid);fields(value,{'request_id','project'},{'request_id','project'});rid=text(value['request_id'],'创建请求ID',100)
    if type(value['project']) is not dict:raise BoardError('project需项目初始化对象')
    if value['project'].get('id')!=pid:raise BoardError('定义中的项目ID与开通授权路径不符',403)
    hashed=digest(value)
    # One production writer plus a local lock serializes duplicate HTTP retries.
    # The catalog lock revalidates revocation/expiry inside project publication.
    with hub._bootstrap_lock:
        with hub.connection() as db:
            db.execute('BEGIN IMMEDIATE');row=grant(db,token,pid,rid,hashed)
            if row['completed']:
                identity=hub.resolve(token)
                if identity['global_admin'] or identity['project_id']!=pid:raise BoardError('owner身份不可用',401)
                role=hub.effective_actor(identity,pid).get('project_role')
                if role!='owner':raise BoardError('原开通身份已移交owner职责，请使用当前项目身份',403)
                return {'project':hub.metadata(pid),'actor':row['actor'],'project_role':role,'created':False,'replayed':True,'same_profile':True}
            # Validate definition before reserving the grant; invalid input can be
            # corrected without binding a capability to an unusable definition.
            definition=value['project'];fields(definition,{'id','name','description','knowledge','governance_profile'},{'id','name','description'})
            text(definition['name'],'项目名称',200);text(definition['description'],'项目说明',4000)
            if definition.get('governance_profile','standard') not in ('light','standard','strict'):raise BoardError('治理档位无效')
            if 'knowledge' in definition:
                from .governance import knowledge_spec
                knowledge_spec(definition['knowledge'])
            if db.execute('SELECT 1 FROM projects WHERE id=?',(pid,)).fetchone():raise BoardError('项目已存在，不能通过授权接管',409)
            db.execute('UPDATE project_grants SET request_id=?,request_hash=? WHERE project=?',(rid,hashed,pid));db.commit();actor=row['actor']
        seed={'token':token,'request_id':rid,'request_hash':hashed}
        metadata=hub.create({'global_admin':False,'actor':{'id':actor}},definition,_owner_seed=seed)
        return {'project':metadata,'actor':actor,'project_role':'owner','created':True,'replayed':False,'same_profile':True}


def self_seed(db,seed,pid):
    """Internal factory validation, under the same publication catalog lock."""
    fields(seed,{'token','actor','request_id','request_hash'},{'token','actor','request_id','request_hash'})
    if type(seed['token']) is not str or not re.fullmatch('[A-Za-z0-9_-]{43,86}',seed['token']):raise BoardError('需要本机生成的SE私有身份',401)
    if type(seed['actor']) is not str or not re.fullmatch('[a-z][a-z0-9_-]{1,47}',seed['actor']) or seed['actor']=='root':raise BoardError('需非root的本项目SE身份')
    hashed=token_hash(seed['token'])
    if db.execute('SELECT 1 FROM credentials WHERE token_hash=? UNION SELECT 1 FROM se_starts WHERE token_hash=? UNION SELECT 1 FROM project_grants WHERE token_hash=?',(hashed,hashed,hashed)).fetchone():raise BoardError('身份已绑定其他登记，请为新项目生成独立身份',409)
    reservation=db.execute('SELECT revoked FROM project_grants WHERE project=?',(pid,)).fetchone()
    if reservation and not reservation['revoked']:raise BoardError('项目ID已有未撤销开通预约，不能接管；请核对项目ID',409)
    return {'actor':seed['actor'],'token_hash':token_hash(seed['token'])}


def self_start(hub,pid,token,value,enabled):
    """Opt-in private-instance registration grants only a new project's owner.

    Textual role claims do not grant existing-project privileges. Publication
    binds the caller-held seed, exact definition and request in one catalog
    commit; normal authorization remains required on every other endpoint.
    """
    pid=project_id(pid);fields(value,{'request_id','actor','project'},{'request_id','actor','project'})
    rid=text(value['request_id'],'创建请求ID',100)
    if type(value['project']) is not dict or value['project'].get('id')!=pid:raise BoardError('定义与项目路径不符')
    hashed=digest(value);seed={'token':token,'actor':value['actor'],'request_id':rid,'request_hash':hashed}
    with hub._bootstrap_lock:
        with hub.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT * FROM se_starts WHERE project=?',(pid,)).fetchone()
            if old:
                if old['token_hash']!=token_hash(token):raise BoardError('项目已开通，不能自行取得其SE身份',409)
                identity=hub.resolve(token)
                if hub.effective_actor(identity,pid).get('project_role')!='owner':raise BoardError('原创建身份已移交，不能恢复owner权限',403)
                if old['actor']!=value['actor'] or old['request_id']!=rid or old['request_hash']!=hashed:raise BoardError('创建请求已冻结，使用原文件恢复',409)
                return {'project':hub.metadata(pid),'actor':old['actor'],'project_role':'owner','created':False,'replayed':True,'same_profile':True}
            if enabled is not True:raise BoardError('此实例尚未启用SE自助创建',403)
            try:hub.admin_store.authenticate(token)
            except BoardError:pass
            else:raise BoardError('请使用独立SE身份，不使用管理员身份',403)
            binding=self_seed(db,seed,pid)
        metadata=hub.create({'global_admin':False,'actor':{'id':binding['actor']}},value['project'],_self_owner_seed=seed)
        return {'project':metadata,'actor':binding['actor'],'project_role':'owner','created':True,'replayed':False,'same_profile':True}
