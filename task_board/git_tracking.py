"""Project-scoped GitHub bindings and read-only commit traceability.

Only operator-created mirrors can be read. Web requests cannot set paths,
credentials, remotes, commands or trigger a push. Each state change is audited.
"""
from copy import deepcopy
import json,re,time
from pathlib import Path
from .store import BoardError,canonical,digest,fields,text,integer
from .git_reader import Reader,sha,safe_path


def setup(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS git_events(seq INTEGER PRIMARY KEY,actor TEXT NOT NULL,
      request_id TEXT NOT NULL,request_hash TEXT NOT NULL,payload TEXT NOT NULL,prev_hash TEXT NOT NULL,
      hash TEXT NOT NULL,UNIQUE(actor,request_id));
      CREATE TRIGGER IF NOT EXISTS git_no_update BEFORE UPDATE ON git_events BEGIN SELECT RAISE(ABORT,'append only'); END;
      CREATE TRIGGER IF NOT EXISTS git_no_delete BEFORE DELETE ON git_events BEGIN SELECT RAISE(ABORT,'append only'); END;''')


def load(db):
    row=db.execute('SELECT * FROM git_events ORDER BY seq DESC LIMIT 1').fetchone()
    if row:return {'revision':row['seq'],'head':row['hash'],**json.loads(row['payload'])['state']}
    return {'revision':0,'head':'0'*64,'repos':{},'links':[],'policy':{'patterns':[],'exceptions':{},'reason':'源码进Git；缓存、调研、归档、资产、测试记录、日志与运行态留本地/NAS'}}


def repo_name(value):
    if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}',value) or value.split('/')[1] in ('.','..'):
        raise BoardError('GitHub仓库需owner/name，不接受URL、令牌或任意主机')
    return value


def repo_id(value):
    if type(value) is not str or not re.fullmatch('[a-z][a-z0-9-]{0,47}',value):raise BoardError('仓库ID需小写字母数字及短横线')
    return value


class Tracking:
    def __init__(self,store):self.store=store

    @property
    def project(self):return self.store.registry.project

    @property
    def root(self):return self.store.registry.hub.state

    def mirror(self,rid,repo):
        """Compare both the project binding and private operator configuration."""
        rid=repo_id(rid);config=self.root/'_private/github.json'
        try:entry=json.loads(config.read_text('utf8'))['projects'][self.project][rid]
        except (FileNotFoundError,KeyError):raise BoardError('仓库尚未由实例管理员配置只读接入',409)
        if entry.get('repository')!=repo['repository']:raise BoardError('实例接入与项目绑定不一致',409)
        p=self.root/'git-mirrors'/self.project/(rid+'.git')
        marker=p/'PROJECT-BOARD-MIRROR.json'
        if not marker.is_file() or marker.is_symlink():raise BoardError('仓库尚未完成第一次同步',409)
        if p.is_symlink() or any(parent.is_symlink() for parent in [p.parent,p.parent.parent]):raise BoardError('仓库路径不能是链接',409)
        if json.loads(marker.read_text())!={'project':self.project,'id':rid,'repository':repo['repository']}:raise BoardError('只读镜像身份不匹配',409)
        return p

    def state(self):
        with self.store.connection() as db:v=load(db)
        for rid,repo in v['repos'].items():
            try:check=json.loads((self.root/'git-mirrors'/self.project/(rid+'.check.json')).read_text())
            except (FileNotFoundError,ValueError):continue
            if check.get('repository')==repo['repository']:
                repo['last_check']={k:check.get(k) for k in ('at','error')}
        return v

    def apply(self,actor,request):
        from .governance import role,tasks,load as governance_load
        from .operations import manager
        fields(request,{'request_id','expected_revision','action','payload'},{'request_id','expected_revision','action','payload'})
        rid=text(request['request_id'],'请求ID',100);integer(request['expected_revision'],'Git版本');action=text(request['action'],'操作',40);p=request['payload']
        if type(p) is not dict:raise BoardError('payload需对象')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');r=role(db,actor)
            if action in ('sync_result',):
                if r not in ('tracker','owner','se','reviewer'):raise BoardError('需要项目Git同步身份',403)
            else:manager(r)
            old=db.execute('SELECT * FROM git_events WHERE actor=? AND request_id=?',(actor['id'],rid)).fetchone()
            if old:
                if old['request_hash']!=digest(request):raise BoardError('请求ID已绑定其他内容',409)
                return {'revision':old['seq'],'hash':old['hash'],'replayed':True}
            v=load(db);seq=v.pop('revision');previous=v.pop('head')
            if seq!=request['expected_revision']:raise BoardError('Git记录已变化；重读后决定',409)
            if action=='bind':
                fields(p,{'id','repository','title','reason'},{'id','repository','title','reason'});key=repo_id(p['id']);name=repo_name(p['repository']);text(p['title'],'仓库名称',200);text(p['reason'],'绑定依据',4000)
                if key in v['repos']:raise BoardError('仓库ID不可覆盖；更换仓库用新ID保留旧关联',409)
                v['repos'][key]={**deepcopy(p),'enabled':True,'refs':{},'synced_at':None,'sync_error':None,'request':1,'synced_request':0,'history':[]}
            elif action=='policy':
                fields(p,{'patterns','exceptions','reason'},{'patterns','exceptions','reason'});text(p['reason'],'存储边界依据',4000)
                if type(p['patterns']) is not list or len(p['patterns'])>100 or type(p['exceptions']) is not dict or len(p['exceptions'])>100:raise BoardError('存储规则需有限的模式列表和逐文件审核例外')
                for pattern in p['patterns']:text(pattern,'项目本地模式',500)
                for path,why in p['exceptions'].items():safe_path(path);text(why,'逐文件纳入依据',2000)
                v['policy']=deepcopy(p)
            elif action=='link':
                fields(p,{'repo','commit','task','scope','reason'},{'repo','commit','task','scope','reason'});key=repo_id(p['repo']);sha(p['commit']);text(p['reason'],'关联依据',4000)
                repo=v['repos'].get(key);task=tasks(db).get(p['task'])
                if not repo or not repo['enabled'] or not task or task['scope_hash']!=p['scope']:raise BoardError('仓库/任务不存在或范围已变',409)
                Reader(self.mirror(key,repo)).commit(p['commit'])
                link={**deepcopy(p),'scope_version':task['scope_version'],'actor':actor['id'],'at':time.time()}
                if any(l['repo']==key and l['commit']==p['commit'] and l['task']==p['task'] and l['scope_version']==task['scope_version'] for l in v['links']):raise BoardError('当前范围已关联该提交',409)
                v['links'].append(link)
            else:
                key=repo_id(p.get('repo'));repo=v['repos'].get(key)
                if not repo:raise BoardError('项目仓库不存在',404)
                if action=='enable':
                    fields(p,{'repo','enabled','reason'},{'repo','enabled','reason'})
                    if type(p['enabled']) is not bool:raise BoardError('enabled需布尔')
                    text(p['reason'],'启停依据',4000);repo['enabled']=p['enabled'];repo['request']+=1
                elif action=='sync_request':
                    fields(p,{'repo','reason'},{'repo','reason'});text(p['reason'],'同步依据',4000)
                    if not repo['enabled']:raise BoardError('仓库已停用',409)
                    repo['request']+=1
                elif action=='sync_result':
                    fields(p,{'repo','repository','request','refs','error','default_branch','alerts','rewritten'},{'repo','repository','request','refs','error','default_branch','alerts','rewritten'})
                    if p['repository']!=repo['repository'] or p['request']!=repo['request'] or not repo['enabled']:raise BoardError('同步结果的绑定/请求已变',409)
                    if type(p['error']) is not str or len(p['error'])>1000:raise BoardError('同步错误说明无效')
                    if type(p['refs']) is not dict or len(p['refs'])>10000 or type(p['alerts']) is not list or len(p['alerts'])>500:raise BoardError('同步结果超限')
                    for ref,h in p['refs'].items():
                        if not re.fullmatch(r'refs/(heads|tags)/[^\s\x00-\x1f]+',ref):raise BoardError('Git引用无效')
                        sha(h)
                    for row in p['alerts']:
                        fields(row,{'path','reason'},{'path','reason'});text(row['path'],'告警路径',1000);text(row['reason'],'告警依据',2000)
                    if type(p['rewritten']) is not list or any(type(ref) is not str or ref not in repo['refs'] for ref in p['rewritten']):raise BoardError('重写引用无效')
                    if type(p['default_branch']) is not str or len(p['default_branch'])>200:raise BoardError('默认分支无效')
                    if not p['error']:
                        reader=Reader(self.mirror(key,repo))
                        values=sorted(set(p['refs'].values()))
                        if values:
                            checked=reader.git(['cat-file','--batch-check'],input_data=('\n'.join(values)+'\n').encode()).decode().splitlines()
                            if len(checked)!=len(values) or any(not row.startswith(value+' commit ') for value,row in zip(values,checked)):raise BoardError('同步引用未指向实际提交对象',404)
                        repo.update(refs=deepcopy(p['refs']),synced_at=time.time(),default_branch=p['default_branch'],alerts=deepcopy(p['alerts']))
                    repo.update(sync_error=p['error'] or None,synced_request=p['request'])
                    repo['history']=(repo['history']+[{'at':time.time(),'error':p['error'],'rewritten':p['rewritten'],'ref_count':len(p['refs'])}])[-100:]
                else:raise BoardError('Git动作不存在',404)
            event={'action':action,'payload':deepcopy(p),'state':v,'at':time.time()};h=digest({'seq':seq+1,'actor':actor['id'],'request_id':rid,'event':event,'previous':previous})
            db.execute('INSERT INTO git_events VALUES(?,?,?,?,?,?,?)',(seq+1,actor['id'],rid,digest(request),canonical(event),previous,h));db.commit()
            return {'revision':seq+1,'hash':h}

    def verify(self):
        previous='0'*64
        with self.store.connection() as db:rows=list(db.execute('SELECT * FROM git_events ORDER BY seq'))
        for i,row in enumerate(rows,1):
            h=digest({'seq':i,'actor':row['actor'],'request_id':row['request_id'],'event':json.loads(row['payload']),'previous':previous})
            if row['seq']!=i or row['prev_hash']!=previous or row['hash']!=h:raise BoardError('Git审计链损坏',409)
            previous=h
        return {'passed':True,'events':len(rows),'head':previous}

    def relation_context(self):
        from .governance import tasks
        from .operations import load as operations_load
        with self.store.connection() as db:
            db.execute('BEGIN');ts=tasks(db);ops=operations_load(db);v=load(db)
        return ts,ops,v

    def relations(self,commit,rid,context=None):
        ts,ops,v=context or self.relation_context();result={'tasks':[],'runs':[],'assets':[]}
        for tid,t in ts.items():
            anchors={'baseline':t['spec'].get('work',{}).get('baseline'),'implementation':(t.get('latest_submission') or {}).get('implementation_commit'),'merge':(t.get('last_merge') or {}).get('commit'),'native':(t.get('native') or {}).get('commit')}
            kinds=[k for k,h in anchors.items() if h==commit]
            explicit=[l for l in v['links'] if l['repo']==rid and l['commit']==commit and l['task']==tid]
            if kinds or explicit:result['tasks'].append({'id':tid,'title':t['spec']['title'],'status':t['status'],'matches':kinds,'explicit':[{'reason':l['reason'],'current':l['scope_version']==t['scope_version'] and l['scope']==t['scope_hash']} for l in explicit]})
        result['runs']=[{'id':r['id'],'status':r['status'],'suite':r['suite'],'tasks':list(r['scopes'])} for r in ops['runs'].values() if r['input_anchor']=='git:'+commit]
        result['assets']=[{'ref':ref,'title':c['title'],'stage':c['stage']} for ref,c in ops['candidates'].items() if c.get('input_anchor')=='git:'+commit]
        return result

    def query(self,endpoint,query):
        v=self.state()
        if endpoint=='':return v
        rid=repo_id(query.get('repo',[''])[0]);repo=v['repos'].get(rid)
        if not repo or not repo['enabled']:raise BoardError('项目仓库不存在或已停用',404)
        reader=Reader(self.mirror(rid,repo),v['policy']);get=lambda key,default='':query.get(key,[default])[0]
        def number(key,default,max_value):
            try:n=int(get(key,str(default)))
            except (ValueError,TypeError):raise BoardError('分页参数无效')
            if n<0 or n>max_value:raise BoardError('分页参数超限')
            return n
        refs=repo['refs'];default=repo.get('default_branch','');default=default if default in refs else next(iter(refs),'')
        if endpoint=='log':
            head=reader.resolve(get('ref',default),refs);path=get('path')
            if path:reader.allowed(path)
            for field in ('q','author'):
                if len(get(field))>300:raise BoardError('搜索过长')
            result=reader.log(head,number('offset',0,100000),path,get('q'),get('author'))
            context=self.relation_context()
            for c in result['commits']:c['relations']=self.relations(c['sha'],rid,context)
            return result
        head=reader.resolve(get('head',get('commit',default)),refs)
        if endpoint=='commit':
            c=reader.commit(head);c.update(files=reader.files(c['parents'][0] if c['parents'] else '',head),relations=self.relations(head,rid));return c
        if endpoint=='tree':return {'files':reader.tree(head,get('path')),'anchor':head}
        if endpoint=='blame':return {**reader.blame(head,get('path'),max(1,number('start',1,1000000))),'anchor':head}
        if endpoint in ('compare','patch'):
            base=get('base')
            if base:reader.commit(sha(base))
            elif endpoint=='compare':raise BoardError('比较需要明确base与head')
            if endpoint=='patch':return {'patch':reader.patch(base,head,get('path')),'base':base,'head':head}
            return {'base':base,'head':head,'files':reader.files(base,head),'meaning':'比较两个固定快照；不是自动合并或验收'}
        raise BoardError('Git查询不存在',404)
