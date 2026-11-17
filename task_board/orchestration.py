"""Pull-only node control plane. No executable, shell, environment or raw RPC."""
import hashlib,json,re,secrets,time,uuid
from .store import BoardError,fields,text,canonical,digest
from .projects import token_hash,project_id

RUNTIMES={'codex','zcode','deepseek','antigravity'}
def prepare(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS orch_nodes(id TEXT PRIMARY KEY,secret TEXT,definition TEXT NOT NULL,pair TEXT,pair_expires REAL,last_seen REAL NOT NULL DEFAULT 0,capabilities TEXT NOT NULL DEFAULT '{}',enabled INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS orch_bindings(id TEXT PRIMARY KEY,project TEXT NOT NULL,actor TEXT NOT NULL,definition TEXT NOT NULL,session TEXT,status TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS orch_jobs(id TEXT PRIMARY KEY,binding TEXT NOT NULL,event TEXT NOT NULL,body TEXT NOT NULL,status TEXT NOT NULL,lease TEXT,expires REAL NOT NULL DEFAULT 0,result TEXT,available REAL NOT NULL DEFAULT 0,UNIQUE(binding,event));
    CREATE TABLE IF NOT EXISTS orch_requests(actor TEXT NOT NULL,id TEXT NOT NULL,hash TEXT NOT NULL,result TEXT NOT NULL,PRIMARY KEY(actor,id));
    CREATE TABLE IF NOT EXISTS orch_cursors(node TEXT NOT NULL,project TEXT NOT NULL,events INTEGER NOT NULL,operations INTEGER NOT NULL,PRIMARY KEY(node,project));
    ''')

def label(value):
    text(value,'标识',100)
    reserved={'CON','PRN','AUX','NUL',*('COM'+str(i) for i in range(1,10)),*('LPT'+str(i) for i in range(1,10))}
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}',value) or value.endswith('.') or value.split('.')[0].upper() in reserved:raise BoardError('标识需跨平台安全：字母、数字、点、下划线或连字符，不用设备名、冒号或结尾点')
    return value
def manager(hub,identity,pid):
    hub.authorize(identity,pid);actor=hub.effective_actor(identity,pid)
    if actor['project_role'] not in ('owner','se','reviewer'):raise BoardError('需要本项目SE权限',403)
    return actor

def project_node_id(pid,alias):
    text(alias,'项目内节点名称',70);label(alias)
    return 'pn-'+hashlib.sha256(pid.encode()).hexdigest()[:16]+'-'+alias

class Orchestrator:
    def __init__(self,hub):self.hub=hub
    def live(self,db,node):
        row=db.execute('SELECT secret,enabled FROM orch_nodes WHERE id=?',(node['id'],)).fetchone()
        if not row or not row['enabled'] or row['secret']!=node['secret']:raise BoardError('节点已撤销',401)
    def node(self,token):
        with self.hub.connection() as db:row=db.execute('SELECT * FROM orch_nodes WHERE secret=? AND enabled=1',(token_hash(token),)).fetchone()
        if not row:raise BoardError('节点未接入或已撤销',401)
        return dict(row)
    def pair(self,identity,p):
        if not identity['global_admin']:raise BoardError('全局共享节点需要实例权限；项目SE请使用 /api/projects/<项目>/nodes/pair 或 nodes/connect',403)
        fields(p,{'id','name','projects'},{'id','name','projects'});label(p['id']);text(p['name'],'节点名',200)
        if type(p['projects']) is not list or not 1<=len(p['projects'])<=100:raise BoardError('需明确允许项目')
        for pid in p['projects']:self.hub.metadata(project_id(pid))
        secret=secrets.token_urlsafe(32)
        with self.hub.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM orch_nodes WHERE id=?',(p['id'],)).fetchone():raise BoardError('节点ID已登记，使用撤销/新ID而非覆盖密钥',409)
            db.execute('INSERT INTO orch_nodes(id,definition,pair,pair_expires) VALUES(?,?,?,?)',(p['id'],canonical(p),digest(secret),time.time()+1800));self.hub.audit(db,'node_pair',None,identity['actor']['id'],p);db.commit()
        return {'id':p['id'],'pair':secret,'expires_in':1800,'private':True}
    def project_node(self,identity,pid,action,p):
        """SE grants only a project-local agent endpoint, never a physical host login."""
        actor=manager(self.hub,identity,pid)
        if action=='revoke':
            fields(p,{'id','reason'},{'id','reason'});label(p['id']);text(p['reason'],'撤销原因')
            with self.hub.connection() as db:
                db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT * FROM orch_nodes WHERE id=?',(p['id'],)).fetchone()
                if not row or json.loads(row['definition']).get('managed_project')!=pid:raise BoardError('本项目专用接入端不存在；不能撤销共享或其他项目节点',404)
                db.execute('UPDATE orch_nodes SET enabled=0 WHERE id=?',(p['id'],));self.hub.audit(db,'project_node_revoked',pid,actor['id'],p);db.commit()
            return {'revoked':p['id'],'running_work':'已撤销本项目接入端控制面权限；原运行和独立项目身份仍需按既有流程核对，不假称已停止'}
        common={'request_id','alias','name','roles'};credential='pair' if action=='pair' else 'key_sha256'
        if action not in ('pair','connect'):raise BoardError('节点动作无效',404)
        fields(p,common|{credential},common|{credential});label(p['request_id']);nid=project_node_id(pid,p['alias']);text(p['name'],'节点名',200)
        if type(p['roles']) is not list or not p['roles'] or any(type(r) is not str or r not in ('se','worker') for r in p['roles']) or len(p['roles'])!=len(set(p['roles'])):raise BoardError('接入角色需明确为SE、Worker或两者')
        if action=='pair':
            if type(p['pair']) is not str or not re.fullmatch('[0-9a-f]{64}',p['pair']):raise BoardError('接入秘密需本机生成的256位随机值')
        elif type(p['key_sha256']) is not str or not re.fullmatch('[0-9a-f]{64}',p['key_sha256']) or p['key_sha256']=='0'*64:raise BoardError('需要本机节点凭据的SHA256，不接收凭据原值')
        definition={'id':nid,'name':p['name'],'projects':[pid],'managed_project':pid,'alias':p['alias'],'roles':sorted(p['roles'])}
        request={'action':action,'payload':p};request_actor='project-node:'+actor['id']+'@'+pid
        with self.hub.connection() as db:
            db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT * FROM orch_requests WHERE actor=? AND id=?',(request_actor,p['request_id'])).fetchone()
            if old:
                if old['hash']!=digest(request):raise BoardError('请求ID已绑定其他节点配置',409)
                row=db.execute('SELECT enabled FROM orch_nodes WHERE id=?',(nid,)).fetchone()
                if not row or not row['enabled']:raise BoardError('该节点已撤销；使用新项目内名称重新接入',409)
                result={**json.loads(old['result']),'replayed':True}
                return {**result,**({'pair':p['pair']} if action=='pair' else {})}
            row=db.execute('SELECT * FROM orch_nodes WHERE id=?',(nid,)).fetchone()
            if row:
                if not row['enabled'] or json.loads(row['definition'])!=definition or action!='connect' or row['secret']!=p['key_sha256']:raise BoardError('本项目节点ID已使用；不能覆盖身份或授权，变更使用新名称',409)
                result={'id':nid,'projects':[pid],'roles':definition['roles'],'connected':True,'replayed':True}
            elif action=='pair':
                expires=time.time()+1800;db.execute('INSERT INTO orch_nodes(id,definition,pair,pair_expires) VALUES(?,?,?,?)',(nid,canonical(definition),digest(p['pair']),expires))
                result={'id':nid,'projects':[pid],'roles':definition['roles'],'expires_at':expires,'expires_in':1800,'private':True}
            else:
                db.execute('INSERT INTO orch_nodes(id,secret,definition) VALUES(?,?,?)',(nid,p['key_sha256'],canonical(definition)))
                result={'id':nid,'projects':[pid],'roles':definition['roles'],'connected':True,'capability_status':'等待本机实际探测与心跳'}
            # Never persist a plaintext pair/credential in audit or response cache.
            db.execute('INSERT INTO orch_requests VALUES(?,?,?,?)',(request_actor,p['request_id'],digest(request),canonical(result)))
            self.hub.audit(db,'project_node_'+action,pid,actor['id'],{'id':nid,'roles':definition['roles'],'request_id':p['request_id']});db.commit()
        return {**result,**({'pair':p['pair']} if action=='pair' else {})}
    def enroll(self,token,p):
        fields(p,{'id','pair'},{'id','pair'});label(p['id']);text(p['pair'],'接入凭据',200)
        if type(token) is not str or not token.startswith('node.') or len(token)<40:raise BoardError('需要本机生成的节点凭据',401)
        hashed=token_hash(token)
        with self.hub.connection() as db:
            db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT * FROM orch_nodes WHERE id=?',(p['id'],)).fetchone()
            if row and row['enabled'] and row['secret']==hashed:return {'id':p['id'],'enrolled':True,'replayed':True}
            if not row or not row['enabled'] or row['secret'] or row['pair_expires']<time.time() or not secrets.compare_digest(row['pair'] or '',digest(p['pair'])):raise BoardError('节点开通凭据失效',401)
            db.execute('UPDATE orch_nodes SET secret=?,pair=NULL,pair_expires=NULL WHERE id=?',(hashed,p['id']));self.hub.audit(db,'node_enrolled',None,p['id'],{});db.commit();return {'id':p['id'],'enrolled':True,'replayed':False}
    def nodes(self,identity,pid=None):
        if pid:manager(self.hub,identity,pid)
        elif not identity['global_admin']:raise BoardError('需要实例所有者',403)
        with self.hub.connection() as db:rows=list(db.execute('SELECT * FROM orch_nodes'))
        result=[]
        for r in rows:
            definition=json.loads(r['definition'])
            if pid and pid not in definition['projects']:continue
            caps=json.loads(r['capabilities'])
            if pid:
                definition['projects']=[pid];caps={key:{**value,'roots':{pid:value.get('roots',{}).get(pid,[])}} for key,value in caps.items()}
            result.append({'id':r['id'],**definition,'can_revoke':bool(pid and definition.get('managed_project')==pid),'online':bool(r['enabled'] and time.time()-r['last_seen']<90),'enabled':bool(r['enabled']),'last_seen':r['last_seen'],'capabilities':caps})
        return {'nodes':result}
    def revoke(self,identity,p):
        if not identity['global_admin']:raise BoardError('需要实例所有者',403)
        fields(p,{'id','reason'},{'id','reason'});text(p['reason'],'撤销原因')
        with self.hub.connection() as db:
            db.execute('BEGIN IMMEDIATE');db.execute('UPDATE orch_nodes SET enabled=0 WHERE id=?',(p['id'],));self.hub.audit(db,'node_revoked',None,identity['actor']['id'],p);db.commit()
        return {'revoked':p['id'],'running_work':'撤销控制面权限；失联运行须在原节点核对停止，不能假定已终止'}
    def heartbeat(self,node,p):
        fields(p,{'capabilities','observations'},{'capabilities'});caps=p['capabilities']
        if type(caps) is not dict or set(caps)-RUNTIMES:raise BoardError('运行时类型无效')
        for key,c in caps.items():
            fields(c,{'ready','version','models','roots','reason'},{'ready','version','models','roots','reason'})
            if type(c['ready']) is not bool or type(c['models']) is not list or len(c['models'])>500 or type(c['roots']) is not dict:raise BoardError('能力结构无效')
            text(c['version'],'运行时版本',200);text(c['reason'],'能力说明',2000)
            for model in c['models']:text(model,'模型路由',240)
            for pid,roots in c['roots'].items():
                if pid not in json.loads(node['definition'])['projects'] or type(roots) is not list:raise BoardError('节点项目/根越界',403)
                for root in roots:label(root)
        with self.hub.connection() as db:
            db.execute('BEGIN IMMEDIATE');self.live(db,node);observations=p.get('observations',[])
            if type(observations) is not list or len(observations)>32:raise BoardError('运行时观察需最多32项')
            for observation in observations:
                fields(observation,{'binding','session','status'},{'binding','session','status'})
                row=db.execute('SELECT * FROM orch_bindings WHERE id=?',(observation['binding'],)).fetchone()
                if not row or json.loads(row['definition'])['node']!=node['id'] or row['session']!=observation['session']:raise BoardError('只能报告本机原绑定会话',403)
                if observation['status'] not in ('approval_required','needs_recovery'):raise BoardError('不支持此观察状态')
                if row['status']!=observation['status']:
                    b=json.loads(row['definition']);db.execute('UPDATE orch_bindings SET status=? WHERE id=?',(observation['status'],row['id']));self.hub.audit(db,'runtime_observation',row['project'],node['id'],observation)
                    latest=db.execute("SELECT id FROM orch_jobs WHERE binding=? AND status='accepted' AND json_extract(body,'$.operation') IN ('notify','resume') ORDER BY rowid DESC LIMIT 1",(row['id'],)).fetchone();incident=latest['id'] if latest else row['session']
                    if observation['status']=='needs_recovery' and latest:db.execute("UPDATE orch_jobs SET status='needs_recovery' WHERE id=?",(latest['id'],))
                    for se in db.execute('SELECT id,definition FROM orch_bindings WHERE project=? AND id<>?',(row['project'],row['id'])).fetchall():
                        if json.loads(se['definition'])['role']=='se':self.enqueue(db,se['id'],observation['status']+':'+row['id']+':'+incident,{'operation':'notify','kind':'runtime_approval' if observation['status']=='approval_required' else 'runtime_recovery','task':b['task'],'binding':row['id'],'summary':'原生运行时要求本机授权或核对异常结果；先核对原会话，不自动批准、重放或重建会话'})
            db.execute('UPDATE orch_nodes SET capabilities=?,last_seen=? WHERE id=? AND enabled=1',(canonical(caps),time.time(),node['id']));db.commit()
        return {'heartbeat':True}
    def enqueue(self,db,binding,event,body):
        jid='job-'+uuid.uuid4().hex
        db.execute("INSERT OR IGNORE INTO orch_jobs(id,binding,event,body,status) VALUES(?,?,?,?,'queued')",(jid,binding,event,canonical(body)))
        return db.execute('SELECT id FROM orch_jobs WHERE binding=? AND event=?',(binding,event)).fetchone()[0]
    def apply(self,identity,pid,request):
        actor=manager(self.hub,identity,pid);fields(request,{'request_id','action','payload'},{'request_id','action','payload'});label(request['request_id']);p=request['payload'];action=request['action']
        with self.hub.connection() as db:
            db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT * FROM orch_requests WHERE actor=? AND id=?',(actor['id']+'@'+pid,request['request_id'])).fetchone()
            if old:
                if old['hash']!=digest(request):raise BoardError('请求ID已绑定其他内容',409)
                return {**json.loads(old['result']),'replayed':True}
            if action=='bind':
                keys={'id','node','runtime','model','root','role','task','scope'};fields(p,keys,keys);label(p['id']);label(p['root']);text(p['model'],'模型',240)
                if p['runtime'] not in RUNTIMES or p['role'] not in ('se','worker'):raise BoardError('会话类型无效')
                if p['role']=='se' and p['task']:raise BoardError('SE绑定不占用Worker任务')
                if p['role']=='worker':
                    t=self.hub.store(pid).get(p['task'])
                    if t['scope_hash']!=p['scope']:raise BoardError('任务范围已变化',409)
                n=db.execute('SELECT * FROM orch_nodes WHERE id=? AND enabled=1',(p['node'],)).fetchone();caps=json.loads(n['capabilities']).get(p['runtime'],{}) if n else {}
                if n and p['role'] not in json.loads(n['definition']).get('roles',['se','worker']):raise BoardError('该接入端未授权此项目角色',403)
                if not n or time.time()-n['last_seen']>=90 or pid not in json.loads(n['definition'])['projects'] or not caps.get('ready') or p['model'] not in caps.get('models',[]) or p['root'] not in caps.get('roots',{}).get(pid,[]):raise BoardError('节点、项目、工作根或真实模型能力未就绪',409)
                if db.execute('SELECT 1 FROM orch_bindings WHERE id=?',(p['id'],)).fetchone():raise BoardError('绑定已存在，不可换项目/运行时',409)
                if p['role']=='worker':
                    for existing in db.execute('SELECT definition FROM orch_bindings WHERE project=?',(pid,)):
                        previous=json.loads(existing[0])
                        if previous['role']=='worker' and previous['task']==p['task']:raise BoardError('该任务已绑定原Worker会话；请恢复原绑定，不能重复派发',409)
                with self.hub.store(pid).connection() as project_db:
                    cursors={table:project_db.execute('SELECT COALESCE(MAX(seq),0) FROM '+table).fetchone()[0] for table in ('events','operations_events')}
                worker='orch-'+uuid.uuid4().hex[:24] if p['role']=='worker' else actor['id'];definition={**p,'project':pid,'actor':worker,'creator':actor['id'],'since':cursors,'scope_version':t['scope_version'] if p['role']=='worker' else None}
                if p['role']=='worker':
                    from .governance import blockers
                    if t['status']!='planned' or not t['spec'].get('claimable') or not t['spec'].get('registered'):raise BoardError('仅向Worker派发当前已发布、未领取任务',409)
                    with self.hub.store(pid).connection() as project_db:reasons=blockers(project_db,t,{'id':worker,'role':'worker'},getattr(self.hub.store(pid),'registry',None))
                    if reasons:raise BoardError('任务尚未就绪：'+'；'.join(reasons),409)
                db.execute("INSERT INTO orch_bindings VALUES(?,?,?,?,NULL,'creating')",(p['id'],pid,worker,canonical(definition)));job=self.enqueue(db,p['id'],'create',{'operation':'create'});result={'binding':p['id'],'job':job,'actor':worker}
            elif action=='recover':
                keys={'job','session','status','summary','evidence'};fields(p,keys,keys);text(p['summary'],'核对说明',4000);text(p['evidence'],'本机收据/运行证据位置',2000)
                row=db.execute('SELECT j.*,b.project,b.session AS original_session FROM orch_jobs j JOIN orch_bindings b ON b.id=j.binding WHERE j.id=? AND b.project=?',(p['job'],pid)).fetchone()
                if not row:raise BoardError('本项目工作不存在',404)
                if row['status']!='needs_recovery' or p['status'] not in ('accepted','failed'):raise BoardError('只能核对未知结果，不自动重放',409)
                if row['original_session'] and p['session']!=row['original_session']:raise BoardError('必须沿用原会话',409)
                if p['status']=='accepted' and not p['session']:raise BoardError('需真实会话ID',409)
                db.execute('UPDATE orch_jobs SET status=?,result=? WHERE id=?',(p['status'],canonical(p),p['job']))
                if p['session']:db.execute("UPDATE orch_bindings SET session=?,status='ready' WHERE id=?",(p['session'],row['binding']))
                result={'recovered':p['job'],'status':p['status'],'evidence':p['evidence']}
            else:
                fields(p,{'binding','summary','scope','previous_scope','scope_version'},{'binding','summary'});text(p['summary'],'操作说明',4000);b=db.execute('SELECT * FROM orch_bindings WHERE id=? AND project=?',(p['binding'],pid)).fetchone()
                if not b:raise BoardError('本项目绑定不存在',404)
                if action not in ('notify','resume','stop'):raise BoardError('编排动作无效')
                if action!='stop' and not b['session']:raise BoardError('会话尚未建立，先核对未知创建结果',409)
                if {'scope','previous_scope','scope_version'} & set(p):
                    definition=json.loads(b['definition'])
                    if action!='resume' or definition['role']!='worker' or not {'scope','previous_scope','scope_version'}<=set(p):raise BoardError('只有明确恢复原Worker可确认新范围')
                    if type(p['scope_version']) is not int:raise BoardError('范围代次需整数')
                    current=self.hub.store(pid).get(definition['task'])
                    if p['previous_scope']!=definition['scope'] or p['scope']!=current['scope_hash'] or p['scope_version']!=current['scope_version']:raise BoardError('范围已变化，核对原绑定与当前任务后决定',409)
                    if db.execute("SELECT 1 FROM orch_jobs WHERE binding=? AND status IN ('running','needs_recovery')",(p['binding'],)).fetchone():raise BoardError('先核对未确认的旧动作，不能通过改范围释放它',409)
                    definition.update(scope=p['scope'],scope_version=p['scope_version']);db.execute('UPDATE orch_bindings SET definition=? WHERE id=?',(canonical(definition),p['binding']))
                    db.execute("UPDATE orch_jobs SET status='superseded' WHERE binding=? AND status='queued'",(p['binding'],))
                result={'job':self.enqueue(db,p['binding'],'manual:'+request['request_id'],{'operation':action,'summary':p['summary']})}
            db.execute('INSERT INTO orch_requests VALUES(?,?,?,?)',(actor['id']+'@'+pid,request['request_id'],digest(request),canonical(result)));self.hub.audit(db,'orchestration_'+action,pid,actor['id'],{'request_id':request['request_id'],'payload':p,'result':result});db.commit();return result
    def listing(self,identity,pid):
        self.hub.authorize(identity,pid);actor=self.hub.effective_actor(identity,pid);man=actor['project_role'] in ('owner','se','reviewer')
        with self.hub.connection() as db:
            bindings=[{**json.loads(r['definition']),'session':r['session'],'status':r['status']} for r in db.execute('SELECT * FROM orch_bindings WHERE project=?',(pid,)) if man or r['actor']==actor['id']]
            ids={x['id'] for x in bindings};jobs=[{k:r[k] for k in ('id','binding','event','status','expires','result')} for r in db.execute('SELECT * FROM orch_jobs') if r['binding'] in ids]
        return {'bindings':bindings,'jobs':jobs,'nodes':self.nodes(identity,pid)['nodes'] if man else [],'node_management':man,'completion':'已接收仅代表运行时接收；交付验收仍以任务事件为准'}
    def collect(self,node):
        """Derive durable notifications from original journals; UNIQUE deduplicates restarts."""
        with self.hub.connection() as db:bindings=[dict(r) for r in db.execute('SELECT * FROM orch_bindings')]
        projects={r['project'] for r in bindings if json.loads(r['definition'])['node']==node['id']}
        from .operations import load
        for pid in projects:
            bs=[b for b in bindings if b['project']==pid];workers={json.loads(b['definition'])['task']:b for b in bs if json.loads(b['definition'])['role']=='worker'};ses=[b for b in bs if json.loads(b['definition'])['role']=='se']
            with self.hub.connection() as db:cursor=db.execute('SELECT events,operations FROM orch_cursors WHERE node=? AND project=?',(node['id'],pid)).fetchone()
            event_cursor,op_cursor=tuple(cursor) if cursor else (0,0)
            with self.hub.store(pid).connection() as pdb:
                pdb.execute('BEGIN')
                row=pdb.execute("SELECT json_extract(payload,'$.state.wf_threads') FROM operations_events ORDER BY seq DESC LIMIT 1").fetchone();v={'wf_threads':json.loads(row[0]) if row and row[0] else {}}
                events=list(pdb.execute("SELECT seq,id,task_id,kind,actor FROM events WHERE seq>? AND kind IN ('submit','accept','request_changes','merge','native')",(event_cursor,)))
                floor=max(op_cursor,min(json.loads(b['definition'])['since']['operations_events'] for b in bs))
                ops=list(pdb.execute("SELECT seq,actor,json_extract(payload,'$.action') AS action,json_extract(payload,'$.payload') AS body FROM operations_events WHERE seq>? AND json_extract(payload,'$.action') IN ('thread_open','thread_reply','thread_decide')",(floor,)))
                new_cursors=[pdb.execute('SELECT COALESCE(MAX(seq),0) FROM '+table).fetchone()[0] for table in ('events','operations_events')]
            notices=[]
            for e in events:
                targets=ses if e['kind']=='submit' else [workers[e['task_id']]] if e['task_id'] in workers else []
                notices += [(b,'task:'+e['id'],{'operation':'notify','task':e['task_id'],'kind':e['kind'],'event':e['id']}) for b in targets if b['actor']!=e['actor'] and e['seq']>json.loads(b['definition'])['since']['events']]
            for e in ops:
                a=e['action'];p=json.loads(e['body'])
                if a not in ('thread_open','thread_reply','thread_decide'):continue
                th=v.get('wf_threads',{}).get(p.get('thread',p.get('id')))
                if not th:continue
                target=workers.get(th['task']);targets=[target] if target and e['actor']!=target['actor'] else ses
                notices += [(b,'comment:'+str(e['seq']),{'operation':'notify','task':th['task'],'kind':a,'thread':th['id'],'event':str(e['seq'])}) for b in targets if b['actor']!=e['actor'] and e['seq']>json.loads(b['definition'])['since']['operations_events']]
            with self.hub.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                for b,event,body in notices:self.enqueue(db,b['id'],event,body)
                db.execute('INSERT INTO orch_cursors VALUES(?,?,?,?) ON CONFLICT(node,project) DO UPDATE SET events=MAX(events,excluded.events),operations=MAX(operations,excluded.operations)',(node['id'],pid,*new_cursors))
                db.commit()
    def poll(self,node):
        self.collect(node);now=time.time()
        with self.hub.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self.live(db,node)
            db.execute("UPDATE orch_jobs SET status='needs_recovery' WHERE status='running' AND expires<?",(now,))
            rows=list(db.execute("SELECT j.*,b.definition,b.session FROM orch_jobs j JOIN orch_bindings b ON b.id=j.binding WHERE j.status='queued' AND j.available<=? ORDER BY CASE WHEN json_extract(j.body,'$.operation')='stop' THEN 0 ELSE 1 END,j.rowid",(now,)))
            for row in rows:
                b=json.loads(row['definition'])
                if b['node']!=node['id'] or b['project'] not in json.loads(node['definition'])['projects']:continue
                # Retain ordering; never create/send a second input while an
                # earlier action on the same managed session is uncertain.
                if db.execute("SELECT 1 FROM orch_jobs WHERE binding=? AND status IN ('running','needs_recovery')",(row['binding'],)).fetchone():continue
                lease=secrets.token_urlsafe(32);db.execute("UPDATE orch_jobs SET status='running',lease=?,expires=? WHERE id=?",(digest(lease),now+90,row['id']));self.hub.audit(db,'node_job_claim',b['project'],node['id'],{'job':row['id']});db.commit();return {'job':row['id'],'lease':lease,'expires':now+90,'binding':{**b,'session':row['session']},'body':json.loads(row['body'])}
            db.commit();return {'job':None}
    def report(self,node,p):
        fields(p,{'job','lease','status','session','summary'},{'job','lease','status','session','summary'});text(p['summary'],'收据说明',4000)
        if p['status'] not in ('heartbeat','accepted','failed','needs_recovery','busy'):raise BoardError('节点收据状态无效')
        with self.hub.connection() as db:
            db.execute('BEGIN IMMEDIATE');self.live(db,node);row=db.execute('SELECT j.*,b.definition FROM orch_jobs j JOIN orch_bindings b ON b.id=j.binding WHERE j.id=?',(p['job'],)).fetchone()
            if not row or json.loads(row['definition'])['node']!=node['id'] or not secrets.compare_digest(row['lease'] or '',digest(p['lease'])):raise BoardError('工作租约无效',403)
            if row['status']==p['status'] and row['result']==canonical({'summary':p['summary'],'session':p['session']}):return {'reported':p['job'],'status':p['status'],'replayed':True}
            if row['status']!='running' or row['expires']<time.time():raise BoardError('工作已失联，需人工核对本机收据恢复',409)
            if p['status']=='heartbeat':db.execute('UPDATE orch_jobs SET expires=? WHERE id=?',(time.time()+90,p['job']))
            else:
                status='queued' if p['status']=='busy' else p['status'];session=p['session'];label(session) if session else None
                b=json.loads(row['definition']);old=db.execute('SELECT session FROM orch_bindings WHERE id=?',(row['binding'],)).fetchone()[0]
                if old and session and old!=session:raise BoardError('不能以新会话代替原会话恢复',409)
                if p['status']=='accepted' and json.loads(row['body'])['operation']=='create' and not session:raise BoardError('创建收据必须含真实会话ID',409)
                db.execute('UPDATE orch_jobs SET status=?,result=?,available=? WHERE id=?',(status,canonical({'summary':p['summary'],'session':session}),time.time()+10 if status=='queued' else 0,p['job']))
                if session:db.execute('UPDATE orch_bindings SET session=?,status=? WHERE id=?',(session,'ready' if p['status']=='accepted' else p['status'],row['binding']))
                if p['status']=='accepted' and json.loads(row['body'])['operation']=='create':self.enqueue(db,row['binding'],'initial-input',{'operation':'notify','kind':'start','task':b['task']})
                self.hub.audit(db,'node_job_'+p['status'],b['project'],node['id'],{'job':p['job'],'session':session,'summary':p['summary']})
            db.commit();return {'reported':p['job'],'status':p['status']}
    def profile(self,node,p):
        fields(p,{'binding'},{'binding'})
        with self.hub.connection() as db:row=db.execute('SELECT * FROM orch_bindings WHERE id=?',(p['binding'],)).fetchone()
        if not row:raise BoardError('绑定不存在',404)
        binding=json.loads(row['definition'])
        if binding['node']!=node['id'] or binding['project'] not in json.loads(node['definition'])['projects'] or binding['role']!='worker':raise BoardError('只能领取该节点自己绑定的Worker身份，不能领取SE/维护身份',403)
        # Separate global lock protects first issuance; the existing private
        # profile survives a lost response and is never regenerated on retry.
        path=self.hub.state/'_private/orchestration'/('worker-'+digest(binding['id'])+'.json')
        with self.hub._bootstrap_lock:
            if path.is_file():value=json.loads(path.read_text('utf8'))
            else:
                value={'project_id':binding['project'],'actor':binding['actor'],'role':'agent','token':secrets.token_urlsafe(32)}
                path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                self.hub.write_private(path,value)
            store=self.hub.store(binding['project'])
            try:store.authenticate(value['token'])
            except BoardError:
                # A revoked actor is retained in actors; register_actor refuses
                # overwrite. A crash before issuance can safely finish once.
                store.register_actor(binding['actor'],'agent',_token=value['token'])
            with store.connection() as project_db:
                project_db.execute('BEGIN IMMEDIATE')
                from .governance import load as gov_load
                if binding['actor'] not in gov_load(project_db)['members']:
                    from .convergence import gov_append
                    gov_append(store,project_db,{'id':binding['creator'],'role':'reviewer'},'member',{'actor':binding['actor'],'role':'worker','scope':'由本项目SE绑定到节点 '+node['id']+' 的具体任务 '+binding['task']+'；无管理权限','actor_kind':'agent'})
                project_db.commit()
            with self.hub.connection() as db:
                db.execute('BEGIN IMMEDIATE');db.execute('INSERT OR IGNORE INTO credentials VALUES(?,?,?)',(token_hash(value['token']),binding['project'],binding['actor']));db.commit()
        # Revocation is authoritative even if a private old profile remains.
        self.hub.resolve(value['token']);return value
