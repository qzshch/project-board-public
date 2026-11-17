"""Optional project-local historical drafts. Approval is atomic with usage imports.

Raw conversations stay on their original machine. This journal stores bounded
metadata; it does not infer work hours, billing, task acceptance or missing usage.
"""
import json,math,re,time
from copy import deepcopy
from .store import BoardError,canonical,digest,fields,text,integer
from .governance import role,tasks,load as governance_load
from .operations import manager,load
from .resources import pointer
from .usage import Usage,normalize_counters,COUNTERS
from .timing import PHASES


def exists(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='retrospective_events'").fetchone())


def setup(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS retrospective_events(
      seq INTEGER PRIMARY KEY,actor TEXT NOT NULL,request_id TEXT NOT NULL,
      request_hash TEXT NOT NULL,payload TEXT NOT NULL,prev_hash TEXT NOT NULL,
      hash TEXT NOT NULL,UNIQUE(actor,request_id));
      CREATE TRIGGER IF NOT EXISTS retrospective_no_update BEFORE UPDATE ON retrospective_events
      BEGIN SELECT RAISE(ABORT,'append only'); END;
      CREATE TRIGGER IF NOT EXISTS retrospective_no_delete BEFORE DELETE ON retrospective_events
      BEGIN SELECT RAISE(ABORT,'append only'); END;''')


def state(db):
    batches={};head='0'*64;revision=0
    if not exists(db):return batches,revision,head
    for row in db.execute('SELECT * FROM retrospective_events ORDER BY seq'):
        event=json.loads(row['payload'])
        if row['prev_hash']!=head or row['hash']!=digest({'seq':row['seq'],'actor':row['actor'],'request_id':row['request_id'],'event':event,'previous':head}):raise BoardError('整理归档审计链损坏',409)
        head=row['hash'];revision=row['seq'];p=event['payload'];bid=p['id']
        b=batches.setdefault(bid,{'id':bid,'versions':{},'approved_version':None})
        if event['action']=='submit':
            b['version']=p['version'];b['versions'][str(p['version'])]={'draft':p,'author':row['actor'],'at':event['at'],'status':'pending','hash':digest(p)}
        else:
            version=b['versions'][str(p['version'])];version.update(status=p['decision'],reviewer=row['actor'],reviewed_at=event['at'],reason=p['reason'])
            if p['decision']=='approved':b['approved_version']=p['version']
    return batches,revision,head


def approved_times(db):
    batches,_,_=state(db);result={}
    for bid,b in batches.items():
        if not b['approved_version']:continue
        version=b['versions'][str(b['approved_version'])]
        for e in version['draft']['entries']:
            if e['kind']!='time':continue
            sid='retro-'+digest([bid,e['id']])
            result[sid]={**deepcopy(e),'actor_kind':'unknown','corrections':[{'seconds':e['seconds'],'reason':e['reason'],'actor':version['reviewer'],'at':version['reviewed_at']}],
                         'retrospective':{'id':bid,'version':b['approved_version'],'source':'historical_declaration','reviewer':version['reviewer']}}
    return result


def archive_entries(db):
    batches,_,_=state(db);result=[]
    for bid,b in batches.items():
        if not b['approved_version']:continue
        v=b['versions'][str(b['approved_version'])];p=v['draft'];a=p['archive']
        result.append({'id':'retro-'+digest(bid)[:24],'title':p['title'],'category':'archive','description':'事后整理归档；'+p['summary'],
          'owner':v['author'],'visibility':'project','locations':[{'kind':a['kind'],'location':a['path'],'machine':a['machine'],'access':a['access']}],
          'version':str(b['approved_version']),'mutable':False,'integrity':{'kind':'manifest','sha256':a['sha256'],'subject':a['path']},
          'availability':'unknown','retention':a['retention'],'tasks':sorted({e['task'] for e in p['entries'] if e.get('task')}),'modules':[],'asset_refs':[],
          'usage_notes':'SE核定元数据；读取原件时仍须复核清单SHA。缺失：'+'；'.join(p['missing']),
          'reason':v['reason'],'entry_version':b['approved_version'],'status':'active','created_at':v['at'],'updated_at':v['reviewed_at'],
          'origin':'retrospective','information_role':'snapshot','retrospective':bid,'updated_by':v['reviewer']})
    return result


def timestamp(value):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<value<=time.time()+300:raise BoardError('时间需有效UTC秒')
    return value


def evidence_ref(p):
    fields(p,{'path','sha256'},{'path','sha256'});pointer(p['path'])
    if re.search(r'(^|[/\\])(admin|node-private|owner-profile|se-profile)\.json$',p['path'],re.I):raise BoardError('不能把私有身份登记为归档证据')
    if not re.fullmatch('[0-9a-f]{64}',str(p['sha256'])) or p['sha256']=='0'*64:raise BoardError('需实际来源SHA256')


def usage_delta(basis):
    fields(basis,{'mode','before','after'},{'mode','before','after'});normalize_counters(basis['after'])
    if basis['mode']=='call':
        if basis['before'] is not None:raise BoardError('逐调用读数不填写累计基线')
        return basis['after']
    if basis['mode']!='cumulative':raise BoardError('需明确逐调用或累计差值口径')
    if basis['before'] is None:return dict.fromkeys(COUNTERS)
    normalize_counters(basis['before']);counts={}
    for key in COUNTERS:
        a,b=basis['after'][key],basis['before'][key]
        if a is not None and b is not None and a<b:raise BoardError('累计计数重置或次序异常，不能负抵扣',409)
        counts[key]=a-b if a is not None and b is not None else None
    normalize_counters(counts);return counts


class Retrospective:
    def __init__(self,store):
        self.store=store;self.usage=Usage(store)
        with store.connection() as db:setup(db)

    def head(self,actor):
        with self.store.connection() as db:
            role(db,actor);row=db.execute('SELECT seq,hash FROM retrospective_events ORDER BY seq DESC LIMIT 1').fetchone()
        return {'revision':row['seq'] if row else 0,'head':row['hash'] if row else '0'*64}

    def listing(self,actor):
        with self.store.connection() as db:
            db.execute('BEGIN');role(db,actor);batches,revision,head=state(db)
        return {'batches':batches,'revision':revision,'head':head,'semantics':'historical metadata; pending versions do not change statistics; approved prior version remains until replacement approval'}

    def validate(self,db,p,actor,r,batches,review=False):
        fields(p,{'id','version','title','summary','period','archive','entries','missing'}, {'id','version','title','summary','period','archive','entries','missing'})
        if not re.fullmatch('[a-z][a-z0-9-]{0,79}',str(p['id'])):raise BoardError('整理批次ID需小写字母、数字及短横线')
        integer(p['version'],'整理版本',1);text(p['title'],'标题',200);text(p['summary'],'整理说明',4000)
        b=batches.get(p['id'])
        if p['version']!=(b['version'] if b and review else b['version']+1 if b else 1):raise BoardError('整理版本已变化，重读后决定',409)
        if b and not review and b['versions'][str(b['version'])]['author']!=actor['id'] and r not in ('owner','se','reviewer'):raise BoardError('只能修订自己提交的整理批次',403)
        fields(p['period'],{'start','end'},{'start','end'});start=timestamp(p['period']['start']);end=timestamp(p['period']['end'])
        if start>=end:raise BoardError('整理时间段无效')
        a=p['archive'];fields(a,{'path','sha256','machine','access','retention','kind'},{'path','sha256','machine','access','retention','kind'});evidence_ref({k:a[k] for k in ('path','sha256')})
        if a['kind'] not in ('local','nas','http'):raise BoardError('归档位置类型无效')
        for k in ('machine','access','retention'):text(a[k],k,2000)
        if type(p['missing']) is not list or len(p['missing'])>64:raise BoardError('缺失清单需最多64项')
        for item in p['missing']:text(item,'缺失说明',1000)
        if type(p['entries']) is not list or len(p['entries'])>64:raise BoardError('每批最多64条补录，大型原件仅登记清单入口')
        ts=tasks(db);g=governance_load(db);seen=set()
        for e in p['entries']:
            if type(e) is not dict:raise BoardError('补录条目需对象')
            common={'id','kind','actor','session','task','scope','scope_version','start','end','phase','origin','reason'}
            extra={'basis','model','attribution'} if e.get('kind')=='usage' else {'seconds','mode','rework'}
            fields(e,common|extra,common|extra);text(e['id'],'条目ID',100)
            for key in ('kind','actor','phase'):text(e[key],key,256)
            if type(e['task']) is not str or type(e['scope']) is not str:raise BoardError('任务/范围需字符串')
            integer(e['scope_version'],'任务范围版本')
            if e['id'] in seen:raise BoardError('条目ID重复')
            seen.add(e['id'])
            if e['kind'] not in ('usage','time'):raise BoardError('补录类型无效')
            if e['actor'] not in g['members'] and e['actor']!='root':raise BoardError('执行者不属于本项目',404)
            if not start<=timestamp(e['start'])<timestamp(e['end'])<=end:raise BoardError('条目必须在整理时间段内')
            if e['phase'] not in PHASES|{'unknown'}:raise BoardError('阶段未知时填写unknown')
            text(e['reason'],'补录/分类依据',4000);evidence_ref(e['origin'])
            if type(e['session']) is not str or len(e['session'])>256:raise BoardError('原生会话ID无效')
            if e['task']:
                t=ts.get(e['task'])
                if not t:raise BoardError('本项目任务不存在',404)
                if e['scope']!=t['scope_hash'] or e['scope_version']!=t['scope_version']:
                    from .store import reduce_event
                    historical=None;matched=False
                    for row in db.execute('SELECT * FROM events WHERE task_id=? ORDER BY seq',(e['task'],)):
                        historical=reduce_event(historical,{**dict(row),'payload':json.loads(row['payload'])})
                        matched |= historical['scope_hash']==e['scope'] and historical['scope_version']==e['scope_version']
                    if not matched:raise BoardError('任务范围无对应历史证据；未知归属仅归档说明',409)
            elif e['scope']!='' or e['scope_version']!=0:raise BoardError('项目协调条目不填写任务范围')
            if e['kind']=='usage':
                text(e['model'],'模型（未知可填unknown）',256);usage_delta(e['basis'])
                if e['attribution'] not in ('bound_task','project_overhead','unattributed') or bool(e['task'])!=(e['attribution']=='bound_task'):raise BoardError('任务归因与任务ID不一致')
                if not e['session']:raise BoardError('用量补录需原生Session ID')
            else:
                if not e['task']:raise BoardError('工时补录需已有任务；项目协调可仅归档说明')
                if e['mode'] not in ('work','wait','pause') or type(e['rework']) is not bool:raise BoardError('时段类型或返修标签无效')
                if type(e['seconds']) not in (int,float) or not math.isfinite(e['seconds']) or not 0<=e['seconds']<=e['end']-e['start']:raise BoardError('有效投入不能超过自然时段；不能由会话历时推断投入')
        if b and b['approved_version']:
            old={e['id']:e for e in b['versions'][str(b['approved_version'])]['draft']['entries'] if e['kind']=='usage'}
            new={e['id']:e for e in p['entries']}
            for key,e in old.items():
                if key not in new or any(new[key][k]!=e[k] for k in ('kind','actor','session','task','scope','scope_version','start','end')):raise BoardError('已入账用量保留原条目与归属；纠错修订计数，未知用null',409)

    def apply(self,actor,request):
        fields(request,{'request_id','project_id','action','payload'},{'request_id','project_id','action','payload'});text(request['request_id'],'请求ID',100)
        if request['project_id']!=self.store.registry.project:raise BoardError('整理包不属于本项目',404)
        p=request['payload'];action=request['action']
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');r=role(db,actor)
            if r in ('viewer','tracker','runner','restorer'):raise BoardError('此身份不能整理归档',403)
            old=db.execute('SELECT * FROM retrospective_events WHERE actor=? AND request_id=?',(actor['id'],request['request_id'])).fetchone()
            if old:
                if old['request_hash']!=digest(request):raise BoardError('请求ID已绑定其他内容',409)
                return {**json.loads(old['payload'])['result'],'replayed':True}
            batches,seq,head=state(db)
            if action=='submit':
                self.validate(db,p,actor,r,batches);result={'id':p['id'],'version':p['version'],'status':'pending','draft_hash':digest(p)}
            elif action=='decide':
                manager(r);fields(p,{'id','version','draft_hash','decision','reason'},{'id','version','draft_hash','decision','reason'});text(p['reason'],'核定依据',4000)
                text(p['id'],'批次ID',100);integer(p['version'],'整理版本',1);text(p['draft_hash'],'草案摘要',64)
                b=batches.get(p['id']);v=b['versions'].get(str(p['version'])) if b else None
                if not v:raise BoardError('本项目整理草案不存在',404)
                if p['version']!=b['version'] or v['status']!='pending' or p['draft_hash']!=v['hash']:raise BoardError('整理草案已变化或已核定',409)
                if p['decision'] not in ('approved','rejected'):raise BoardError('核定结果无效')
                imports=[]
                if p['decision']=='approved':
                    # Revalidate all scope, member and shape assumptions at approval.
                    self.validate(db,v['draft'],actor,r,batches,review=True)
                    imports=self.import_entries(db,actor,v['draft'],v['author'])
                result={'id':p['id'],'version':p['version'],'status':p['decision'],'usage_receipts':imports}
            else:raise BoardError('整理动作无效')
            event={'action':action,'payload':deepcopy(p),'result':result,'at':time.time()};h=digest({'seq':seq+1,'actor':actor['id'],'request_id':request['request_id'],'event':event,'previous':head})
            db.execute('INSERT INTO retrospective_events VALUES(?,?,?,?,?,?,?)',(seq+1,actor['id'],request['request_id'],digest(request),canonical(event),head,h));db.commit();return {**result,'revision':seq+1,'hash':h}

    def import_entries(self,db,actor,p,author):
        # Compare against real existing records, not just this draft's IDs.
        prior_times=approved_times(db);live=load(db)['sessions'];receipts=[]
        for e in p['entries']:
            if e['kind']=='time':
                for other in [*live.values(),*prior_times.values(),*[x for x in p['entries'] if x['kind']=='time' and x['id']!=e['id']]]:
                    if other.get('retrospective',{}).get('id')==p['id']:continue
                    if other['actor']==e['actor'] and max(other['start'],e['start'])<min(other['end'] or time.time(),e['end']):raise BoardError('同一执行者已有重叠时段；先核对原记录，不能重复补录',409)
                continue
            sample='retro-'+digest([p['id'],e['id']]);previous=db.execute('SELECT * FROM token_usage WHERE actor=? AND sample=? ORDER BY revision DESC LIMIT 1',(e['actor'],sample)).fetchone()
            if previous and json.loads(previous['payload']).get('retrospective',{}).get('batch')!=p['id']:raise BoardError('补录样本ID与既有记录冲突，不能覆盖',409)
            # Legacy streams lack reliable interval bounds: reject instead of
            # manufacturing a disjoint historical segment or counting twice.
            for row in db.execute("SELECT payload FROM token_usage WHERE json_extract(payload,'$.observation.session')=? AND sample<>?",(e['session'],sample)):
                existing=json.loads(row[0]);bounds=existing.get('retrospective',{}).get('period')
                if not bounds or max(bounds['start'],e['start'])<min(bounds['end'],e['end']):raise BoardError('该会话已有用量或重叠导入；保留现有账本，仅归档核对结果',409)
            for other in p['entries']:
                if other['kind']=='usage' and other['id']!=e['id'] and other['session']==e['session'] and max(other['start'],e['start'])<min(other['end'],e['end']):raise BoardError('草案内同一会话用量区间重叠',409)
            observation={'sample':sample,'revision':previous['revision']+1 if previous else 1,'session':e['session'],'task':e['task'],'phase':e['phase'],'model':e['model'],'source':'imported','mode':'call','epoch':'retrospective','ordinal':0,'from_start':False,'occurred':e['end'],'counters':usage_delta(e['basis']),'origin':e['origin'],'attribution':e['attribution']}
            if previous:
                before=json.loads(previous['payload'])['observation']
                if {k:v for k,v in observation.items() if k!='revision'}=={k:v for k,v in before.items() if k!='revision'}:
                    receipts.append({'seq':previous['seq'],'hash':previous['hash'],'replayed':True});continue
            receipts.append(self.usage.append_in(db,actor,observation,{'batch':p['id'],'version':p['version'],'subject_actor':e['actor'],'submitted_by':author,'period':{'start':e['start'],'end':e['end']},'reason':e['reason']}))
        return receipts
