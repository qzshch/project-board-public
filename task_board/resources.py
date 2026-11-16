"""Project resource directory: locations and handoff metadata, never file serving.

Mutable caches/logs/runtime are not reusable releases. Their registration does
not publish files, grant OS permissions, verify contents or change asset pins.
"""
from copy import deepcopy
import json,re,time
from urllib.parse import urlsplit,unquote,parse_qsl
from .store import BoardError,fields,text,integer,identifiers,digest

CATEGORIES={'cache':'缓存','research':'调研材料','art':'美术与媒体','archive':'历史归档',
            'test_records':'测试记录与产物','logs':'日志','runtime':'运行态','documentation':'接手资料','other':'其他资源'}
KINDS={'nas','smb','ssh','local','http','repo'}
VISIBILITY={'project','managers','operator'}


def visible(entry,role='agent',operator=False):
    return operator or entry['visibility']=='project' or (entry['visibility']=='managers' and role in ('owner','se','reviewer'))


def audience(actor,g,operator=False):
    return g['members'].get((actor or {}).get('id'),{}).get('role',(actor or {}).get('role','agent')),bool(operator)


def pointer(value):
    text(value,'资源位置',2000)
    if any(ord(c)<32 for c in value):raise BoardError('资源位置不得包含控制字符')
    decoded=unquote(value).replace('\\','/').casefold()
    if any(p in decoded.split('/') for p in ('_private','.ssh','.git')) or any(s in decoded for s in ('operator.html','id_ed25519','id_rsa')):
        raise BoardError('不登记密钥、私有身份目录或一次性管理员入口；填写申请访问的方式')
    if any(p=='.env' or p.startswith('.env.') for p in decoded.split('/')):raise BoardError('不登记环境凭据文件')
    if re.match(r'^[a-z][a-z0-9+.-]*://',value,re.I):
        try:parsed=urlsplit(value)
        except ValueError:raise BoardError('资源URL格式无效')
        navigation={'project','panel','task','ref','version'}
        query=parse_qsl(parsed.query,keep_blank_values=True)
        if parsed.scheme not in ('http','https','smb','ssh') or parsed.username or parsed.password or parsed.fragment or any(k not in navigation or len(v)>300 or any(ord(c)<32 for c in v) for k,v in query):
            raise BoardError('使用稳定、不含用户信息/鉴权参数的HTTP、SMB或SSH位置')
    return value


def filtered(g,role='agent',operator=False):
    return {k:deepcopy(e) for k,e in g.get('resource_entries',{}).items() if visible(e,role,operator)}


def validate(p,g,tasks):
    keys={'id','title','category','description','owner','visibility','locations','version','mutable',
          'integrity','availability','retention','tasks','modules','asset_refs','usage_notes','reason'}
    fields(p,keys|{'expected_version','information_role'},keys)
    if p.get('information_role','reference') not in ('reference','snapshot'):raise BoardError('资料角色需 reference 或 snapshot')
    if type(p['id']) is not str or not re.fullmatch('[a-z][a-z0-9-]{0,79}',p['id']):raise BoardError('资源ID需小写字母、数字和短横线')
    for k in ('category','visibility','availability'):
        if type(p[k]) is not str:raise BoardError(k+'需字符串')
    if p['category'] not in CATEGORIES or p['visibility'] not in VISIBILITY:raise BoardError('资源分类或可见范围无效')
    if p['id'].startswith('operator-')!=(p['visibility']=='operator'):raise BoardError('实例管理员入口使用operator-专用ID，不能原地改变权限范围')
    if p['availability'] not in ('available','request_access','offline','missing','unknown'):raise BoardError('可用性需明确登记')
    if type(p['mutable']) is not bool:raise BoardError('mutable需布尔')
    for k in ('title','description','owner','version','retention','usage_notes','reason'):text(p[k],k,4000 if k!='title' else 200)
    if p['owner']!='root' and p['owner'] not in g['members']:raise BoardError('维护者需为本项目已登记成员',409)
    if type(p['locations']) is not list or not 1<=len(p['locations'])<=8:raise BoardError('需1至8个资源位置')
    for loc in p['locations']:
        fields(loc,{'kind','location','machine','access'},{'kind','location','machine','access'})
        if type(loc['kind']) is not str or loc['kind'] not in KINDS:raise BoardError('位置类型无效')
        pointer(loc['location']);text(loc['machine'],'所属机器',200);text(loc['access'],'访问方式与授权条件',4000)
        if loc['kind']=='http' and urlsplit(loc['location']).scheme not in ('http','https'):raise BoardError('HTTP入口需HTTP(S)地址')
    fields(p['integrity'],{'kind','sha256','subject'},{'kind','sha256','subject'});it=p['integrity']
    if it['kind'] not in ('none','file','manifest'):raise BoardError('摘要类型无效')
    if it['kind']=='none':
        if it['sha256']!='' or it['subject']!='':raise BoardError('未登记摘要时不填写占位摘要')
    else:
        if not re.fullmatch('[0-9a-f]{64}',str(it['sha256'])) or it['sha256']=='0'*64:raise BoardError('需实际SHA256，不用全零占位')
        text(it['subject'],'摘要覆盖的文件或清单',2000)
    if not p['mutable'] and it['kind']=='none':raise BoardError('固定版本需登记实际文件或清单摘要')
    for key in ('tasks','modules','asset_refs'):identifiers(p[key],key)
    if not set(p['tasks'])<=set(tasks) or not set(p['modules'])<=set(g.get('modules',{})):raise BoardError('关联需为本项目已有任务/模块',409)
    allowed=set(g['assets'])|set(g.get('consumption',{}))
    if not set(p['asset_refs'])<=allowed:raise BoardError('关联资产需为本项目已有版本或固定消费',409)
    return {**{k:deepcopy(p[k]) for k in keys},'information_role':p.get('information_role','reference')}


def mutate(db,g,actor,role,action,p,registry=None):
    entries=g.setdefault('resource_entries',{});operator=bool(actor.get('global_admin'))
    if type(p.get('id')) is not str:raise BoardError('资源ID需字符串')
    if p['id'].startswith('operator-') and not operator:raise BoardError('需要实例管理员',403)
    old=entries.get(p['id']);now=time.time()
    if action=='resource_register':
        if len(entries)>=512:raise BoardError('资源登记达到上限',409)
        if old:raise BoardError('资源ID不可覆盖，请更新现有版本',409)
        from .governance import tasks
        value=validate(p,{**g,'consumption':registry.consumption() if registry else g.get('consumption',{})},tasks(db))
        if value['visibility']=='operator' and not operator:raise BoardError('需要实例管理员',403)
        entries[p['id']]={**value,'entry_version':1,'status':'active','created_at':now,'updated_at':now,'updated_by':actor['id'],'origin':'registered'}
    else:
        if not old or not visible(old,role,operator):raise BoardError('资源入口不存在',404)
        integer(p.get('expected_version'),'资源版本')
        if p['expected_version']!=old['entry_version']:raise BoardError('资源版本已变化，重读后决定',409)
        if action=='resource_classify':
            fields(p,{'id','expected_version','information_role','reason'},{'id','expected_version','information_role','reason'})
            if p['information_role'] not in ('reference','snapshot'):raise BoardError('资料角色无效')
            text(p['reason'],'分类依据',4000)
            old.update(information_role=p['information_role'],entry_version=old['entry_version']+1,updated_at=now,updated_by=actor['id'],reason=p['reason'])
        elif action=='resource_update':
            if old['status']=='retired':raise BoardError('已停用入口保留历史，使用新ID登记替代位置',409)
            from .governance import tasks
            value=validate({**p,'information_role':p.get('information_role',old.get('information_role','reference'))},{**g,'consumption':registry.consumption() if registry else g.get('consumption',{})},tasks(db))
            entries[p['id']]={**value,'entry_version':old['entry_version']+1,'status':'active','created_at':old['created_at'],'updated_at':now,'updated_by':actor['id'],'origin':'registered'}
        elif action=='resource_retire':
            fields(p,{'id','expected_version','reason'},{'id','expected_version','reason'});text(p['reason'],'停止推荐依据',4000)
            if old['status']=='retired':raise BoardError('入口已经停用',409)
            old.update(status='retired',entry_version=old['entry_version']+1,updated_at=now,updated_by=actor['id'],reason=p['reason'])
        else:raise BoardError('资源动作不存在',404)


def run_records(op,g):
    """Reuse existing project-authorized runner receipts, not filesystem scans."""
    result=[]
    for run in op['runs'].values():
        if not run.get('suite') or not run.get('finished'):continue
        for a in run['artifacts']:
            try:pointer(a['location'])
            except BoardError:continue
            category='logs' if a['path'].endswith(('.log','.jsonl')) or 'logs.sha256' in a['path'] else 'test_records'
            result.append({'id':'run:'+run['id']+':'+digest(a)[:12],'title':a['path'],'category':category,
                'description':'运行 '+run['id']+' · '+run['status']+' · '+run['input_anchor'],
                'owner':(run.get('lease') or {}).get('actor','root'),'visibility':'project',
                'locations':[{'kind':'nas' if a['location'].startswith('/') else 'local','location':a['location'],'machine':run.get('environment','执行器'),
                    'access':'先通过本项目运行回执核对SHA；文件读取需该执行机器的项目范围授权，请联系SE。位置来自完成回传，现状未自动复核。'}],
                'version':run['input_anchor'],'mutable':False,'integrity':{'kind':'file','sha256':a['sha256'],'subject':a['path']},
                'availability':'unknown','retention':'按本项目证据保留规则维护；不要把运行记录当源码提交。',
                'tasks':list(run['scopes']),'modules':[],'asset_refs':[ref for ref,asset in g['assets'].items() if asset['sha256']==a['sha256'] and asset['location']==a['location']],
                'usage_notes':'运行结果不是可复用资产审核；固定版本消费仍按资产流程。','reason':'由本项目自动化运行回执派生，原件不上传Git。',
                'entry_version':1,'status':'active','created_at':run['finished'],'updated_at':run['finished'],
                'updated_by':(run.get('lease') or {}).get('actor','root'),'origin':'run_artifact','run':run['id'],
                'test_status':run['status'],'scope_versions':run.get('scope_versions',{}),'scopes':run['scopes']})
    return result


def knowledge_records(g):
    """Expose existing authorized project entries without guessing their type."""
    rows=[];owner=next((id for id,m in g['members'].items() if m['role']=='owner'),'root')
    for group in ('materials','entries'):
        for item in g.get('knowledge',{}).get(group,[]):
            try:pointer(item['location'])
            except BoardError:continue
            location=item['location'];kind='http' if location.startswith(('http://','https://')) else 'smb' if location.startswith('\\\\') else 'nas' if location.startswith('/') else 'local' if re.match('[A-Za-z]:',location) else 'repo'
            fixed=bool(re.fullmatch('[0-9a-f]{64}',str(item.get('sha256',''))) and item['sha256']!='0'*64)
            rows.append({'id':'knowledge:'+group+':'+digest(item)[:16],'title':item['title'],'category':'other','description':'既有项目知识中的材料 / 入口，尚未按资源分类补全。原登记的版本与摘要保留，未自动判断许可、机器权限或现状。',
                'owner':owner,'visibility':'project','locations':[{'kind':kind,'location':location,'machine':'以原登记与SE交接说明为准','access':'按本项目原授权访问，具体机器与文件权限向SE核对；不提供全局凭据。'}],
                'version':item['version'],'mutable':not fixed,'integrity':{'kind':'file' if fixed else 'none','sha256':item['sha256'] if fixed else '','subject':item['title'] if fixed else ''},
                'availability':'unknown','retention':'由SE补充材料的保留规则；不因目录展示自动移动或上传原件。','tasks':[],'modules':[],'asset_refs':[],'usage_notes':'来源既有项目知识，使用前按原登记核对输入版本和许可。','reason':'继承已有入口元数据，不自动建立新权限或改写原材料。',
                'entry_version':1,'status':'active','created_at':0,'updated_at':0,'updated_by':owner,'origin':'knowledge'})
    return rows


class Directory:
    def __init__(self,store):self.store=store

    def context(self,actor=None,operator=False):
        from .governance import load,tasks
        from .operations import load as operations_load
        with self.store.connection() as db:
            db.execute('BEGIN');g=load(db);op=operations_load(db);ts=tasks(db)
        role,operator=audience(actor,g,operator)
        registered=list(filtered(g,role,operator).values())
        known=knowledge_records(g)
        known=[e for e in known if not any(r['status']=='active' and r['integrity']['sha256']==e['integrity']['sha256'] and any(loc['location']==e['locations'][0]['location'] for loc in r['locations']) for r in registered)]
        entries=registered+known+run_records(op,g)
        return g,entries,ts,role,operator

    def listing(self,actor=None,operator=False,query=None,brief_task=None):
        g,rows,tasks,_,_=self.context(actor,operator);query=query or {};get=lambda k,d='':query.get(k,[d])[0]
        task_id=brief_task or get('task');category=get('category');origin=get('origin');needle=get('q').casefold()
        if category and category not in CATEGORIES:raise BoardError('分类无效')
        if origin and origin not in ('registered','run_artifact','knowledge'):raise BoardError('来源无效')
        if task_id and task_id not in tasks:raise BoardError('本项目任务不存在',404)
        if len(needle)>300:raise BoardError('搜索过长')
        if task_id:
            t=tasks[task_id];module=t['spec'].get('work',{}).get('planning',{}).get('module')
            rows=[e for e in rows if (not e['tasks'] and not e['modules']) or task_id in e['tasks'] or module in e['modules']]
            for e in rows:
                if e['origin']=='run_artifact':e['record_scope_current']=e['scopes'].get(task_id)==t['scope_hash'] and e['scope_versions'].get(task_id)==t['scope_version']
        view=get('view','all')
        if view not in ('current','history','all'):raise BoardError('资料视图无效')
        for e in rows:
            e['information_role']=e.get('information_role','snapshot' if e['origin']=='run_artifact' or e['category'] in ('archive','test_records','logs') else 'reference')
            e['authority']='external_reference' if e['information_role']=='reference' else 'historical_snapshot'
        if get('retired')!='true':rows=[e for e in rows if e['status']!='retired']
        if view!='all':rows=[e for e in rows if (e['information_role']=='snapshot' or e['status']=='retired')==(view=='history')]
        counts={k:sum(e['category']==k for e in rows) for k in CATEGORIES}
        rows=[e for e in rows if (not category or e['category']==category) and (not origin or e['origin']==origin) and (not needle or needle in json.dumps(e,ensure_ascii=False).casefold())]
        rows.sort(key=lambda e:(e['origin']!='registered',-e['updated_at'],e['id']))
        try:offset=int(get('offset','0'));limit=int(get('limit','100'))
        except ValueError:raise BoardError('分页参数无效')
        if not 0<=offset<=100000 or not 1<=limit<=200:raise BoardError('分页参数超限')
        return {'revision':g['revision'],'entries':rows[offset:offset+limit],'total':len(rows),'next':offset+limit if offset+limit<len(rows) else None,'counts':counts,'categories':CATEGORIES}

    def entry(self,rid,actor=None,operator=False,history=False):
        g,rows,_,role,operator=self.context(actor,operator);entry=next((e for e in rows if e['id']==rid),None)
        if not entry:raise BoardError('资源入口不存在',404)
        if not history:return {'revision':g['revision'],'entry':entry}
        versions=[]
        if entry['origin']!='registered':versions=[entry]
        else:
            with self.store.connection() as db:
                for row in db.execute("SELECT payload FROM governance_events ORDER BY seq"):
                    event=json.loads(row['payload'])
                    if event['action'] not in ('resource_register','resource_update','resource_retire','resource_classify') or event['payload']['id']!=rid:continue
                    previous=event['state']['resource_entries'][rid]
                    if visible(previous,role,operator):versions.append(previous)
        return {'revision':g['revision'],'id':rid,'versions':versions}
