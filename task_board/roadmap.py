"""Product stages and presentation hierarchy; never task admission policy.

Only stage review has stage prerequisites. Focus and classification do not
rewrite execution scopes, interfaces, dependency locks or task receipts.
"""
from copy import deepcopy
from collections import Counter
import re,time
from .store import BoardError,fields,text,identifiers,digest,evidence

ACTIONS={'stage_plan','stage_focus','stage_review','function_tree'}
RESULTS={'accepted':{'accepted','merged','native_accepted','baseline_merged'},
         'merged':{'merged','native_accepted','baseline_merged'},'native_accepted':{'native_accepted'}}
PRIORITIES={'P0':0,'P1':1,'P2':2,'P3':3}


def prepare(g):
    for key in ('product_stages','product_stage_heads','function_trees'):g.setdefault(key,{})
    g.setdefault('stage_focus',None);g.setdefault('function_tree_head',None)


def uid(value,label='ID'):
    if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,79}',value):raise BoardError(label+'需1至80位字母数字或 . _ / -')
    return value


def task_results(ts,refs):
    result={}
    for tid in refs:
        t=ts[tid];s=t.get('latest_submission') or {}
        result[tid]={'scope':t['scope_hash'],'version':t['scope_version'],'status':t['status'],'submission':s.get('id'),
                     'implementation':s.get('implementation_commit'),'artifact':s.get('artifact'),'accepted':t['accepted'],
                     **{key:{k:v.get(k) for k in ('event','commit')} if (v:=t.get(key)) else None for key in ('last_merge','native')}}
    return result


def stage_check(g,ts,ops,git,ref,cache=None):
    cache={} if cache is None else cache
    if ref in cache:return cache[ref]
    plan=g.get('product_stages',{}).get(ref)
    if not plan:return {'ready':False,'passed':False,'blockers':['阶段版本不存在'],'scope':''}
    blockers=[];requirements=plan['tasks'];refs=[r['task'] for r in requirements]
    if not refs:blockers.append('尚未关联实际交付任务')
    if not plan['input_anchor']:blockers.append('尚未冻结阶段验收基线')
    task_progress=[]
    for requirement in requirements:
        t=ts[requirement['task']];ok=t['status'] in RESULTS[requirement['stage']]
        if not ok:blockers.append('阶段交付 '+requirement['task']+' 尚未达到 '+requirement['stage'])
        task_progress.append({**requirement,'status':t['status'],'ready':ok,'title':t['spec']['title']})
    findings={f['id']:f for f in ops.get('wf_findings',{}).values() if f['task'] in refs and f.get('blocking') and f['status'] not in ('fixed','dismissed') and f.get('scope')==ts[f['task']]['scope_hash'] and f.get('scope_version')==ts[f['task']]['scope_version']}
    blockers+=['关联任务仍有阻塞发现：'+key for key in findings]
    predecessors={r:stage_check(g,ts,ops,git,r,cache) for r in plan['entry_stages']}
    for r,state in predecessors.items():
        if not state['passed']:blockers.append('阶段验收前置尚未通过：'+r)
    repo=git['repos'].get(plan['repo']) if plan['repo'] else None
    if plan['input_anchor'].startswith('git:') and (not repo or not repo['enabled']):blockers.append('阶段仓库未绑定或已停用')
    scope=digest({'plan':{k:v for k,v in plan.items() if k not in ('reviews','by','at')},'tasks':task_results(ts,refs),
                  'findings':findings,'entry_stages':{r:{'scope':s['scope'],'passed':s['passed']} for r,s in predecessors.items()},
                  'repository':{k:repo.get(k) for k in ('repository','enabled')} if repo else None})
    review=plan['reviews'][-1] if plan['reviews'] else None
    passed=bool(not blockers and review and review['result']=='pass' and review['scope']==scope)
    head=(repo or {}).get('refs',{}).get((repo or {}).get('default_branch'))
    result={'scope':scope,'ready':not blockers,'passed':passed,'blockers':blockers,'tasks':task_progress,
            'review_current':bool(review and review['scope']==scope),'latest_review':review,
            'input_anchor':plan['input_anchor'],'current_repository_head':head,
            'repository_synced_at':(repo or {}).get('synced_at'),'repository_sync_error':(repo or {}).get('sync_error'),
            'baseline_matches_current':head==plan['input_anchor'][4:] if head and plan['input_anchor'].startswith('git:') else None,
            'verification_origin':'SE逐项证据核对；固定版本通过不等于后续修改已经验证'}
    cache[ref]=result;return result


def task_hints(g,ts):
    """Recommendation metadata, deliberately not consulted by claim validators."""
    stages=g.get('product_stages',{});focus=g.get('stage_focus') or {};heads=g.get('product_stage_heads',{})
    out={tid:{'focused':False,'stages':[],'stage_priority':'P3'} for tid in ts}
    refs=list(dict.fromkeys([*heads.values(),*([focus['ref']] if focus.get('ref') in stages else [])]))
    for ref in refs:
        p=stages[ref]
        for requirement in p['tasks']:
            row=out[requirement['task']];row['stages'].append(ref)
            if ref==focus.get('ref'):row['focused']=True
            if PRIORITIES[p['priority']]<PRIORITIES[row['stage_priority']]:row['stage_priority']=p['priority']
    return out


def priority_key(t,hints):
    h=hints.get(t['spec']['id'],{})
    return (PRIORITIES.get(t['spec'].get('priority'),2),not h.get('focused',False),PRIORITIES.get(h.get('stage_priority'),3),t['spec']['id'])


def tree_projection(g,ts):
    definition=g.get('function_trees',{}).get(g.get('function_tree_head'))
    module_ids=set(g.get('module_heads',{}));nodes=deepcopy(definition['nodes']) if definition else []
    if not definition:
        nodes=[{'id':mid,'title':g['modules'][ref]['title'],'description':'沿用既有模块父子关系，尚未配置独立功能分类','parent':g['modules'][ref]['parent'] if g['modules'][ref]['parent'] in module_ids else '', 'module_ids':[mid],'task_ids':[]} for mid,ref in g.get('module_heads',{}).items()]
    module_map={mid:n['id'] for n in nodes for mid in n['module_ids'] if mid in module_ids}
    task_map={tid:n['id'] for n in nodes for tid in n['task_ids'] if tid in ts}
    for tid,t in ts.items():
        if tid in task_map:continue
        mid=t['spec'].get('work',{}).get('planning',{}).get('module','').rsplit('@',1)[0]
        if mid in module_map:task_map[tid]=module_map[mid]
    by_id={n['id']:n for n in nodes}
    for n in nodes:
        n['children']=[];n['tasks']=[];n['modules']=[{'id':mid,'ref':g['module_heads'][mid],'title':g['modules'][g['module_heads'][mid]]['title']} for mid in n['module_ids'] if mid in module_ids]
    for n in nodes:
        if n['parent'] in by_id:by_id[n['parent']]['children'].append(n['id'])
    for tid,nid in task_map.items():
        t=ts[tid];by_id[nid]['tasks'].append({'id':tid,'title':t['spec']['title'],'status':t['status'],'kind':t['spec']['kind'],'priority':t['spec']['priority']})
    def totals(nid,visiting=None):
        visiting=set(visiting or ())
        if nid in visiting:return Counter()
        visiting.add(nid);n=by_id[nid];count=Counter(t['status'] for t in n['tasks'])
        for child in n['children']:count.update(totals(child,visiting))
        n['counts']=dict(count);n['task_count']=sum(count.values());return count
    roots=[n['id'] for n in nodes if n['parent'] not in by_id]
    for nid in roots:totals(nid)
    unclassified=[{'id':tid,'title':t['spec']['title'],'status':t['status'],'kind':t['spec']['kind']} for tid,t in ts.items() if tid not in task_map]
    return {'definition':definition,'nodes':nodes,'roots':roots,'task_map':task_map,
            'unclassified_tasks':unclassified,'unclassified_modules':sorted(module_ids-set(module_map)),
            'total_tasks':len(ts),'classified_tasks':len(task_map),'source':'function_tree' if definition else 'existing_module_parents'}


def mutate(db,g,actor,role,action,p,store):
    from .governance import tasks,MANAGERS
    if role not in MANAGERS:raise BoardError('需本项目SE管理阶段与功能树',403)
    prepare(g);ts=tasks(db)
    if action=='function_tree':
        fields(p,{'version','nodes','reason'},{'version','nodes','reason'});uid(p['version'],'组织版本');text(p['reason'],'组织调整依据',4000)
        if p['version'] in g['function_trees']:raise BoardError('组织版本不可覆盖',409)
        if type(p['nodes']) is not list or len(p['nodes'])>256:raise BoardError('功能节点最多256个')
        seen=set();modules=set();assigned=set();by_id={}
        for n in p['nodes']:
            fields(n,{'id','title','description','parent','module_ids','task_ids'},{'id','title','description','parent','module_ids','task_ids'})
            uid(n['id']);text(n['title'],'功能名称',200)
            if type(n['description']) is not str or len(n['description'])>4000:raise BoardError('功能说明过长或类型无效')
            if type(n['parent']) is not str or len(n['parent'])>80:raise BoardError('父功能无效')
            if n['id'] in seen:raise BoardError('功能ID重复')
            seen.add(n['id']);by_id[n['id']]=n
            identifiers(n['module_ids'],'关联模块',2048);identifiers(n['task_ids'],'关联任务',10000)
            if not set(n['module_ids'])<=set(g.get('module_heads',{})) or not set(n['task_ids'])<=set(ts):raise BoardError('关联必须属于本项目现有模块/任务',409)
            if modules.intersection(n['module_ids']) or assigned.intersection(n['task_ids']):raise BoardError('模块或任务只能有一个主归属',409)
            modules.update(n['module_ids']);assigned.update(n['task_ids'])
        for n in p['nodes']:
            chain={n['id']};parent=n['parent']
            while parent:
                if parent not in by_id:raise BoardError('父功能不存在',409)
                if parent in chain:raise BoardError('功能层级成环',409)
                chain.add(parent)
                if len(chain)>12:raise BoardError('功能树最多12层')
                parent=by_id[parent]['parent']
        g['function_trees'][p['version']]={**deepcopy(p),'by':actor['id'],'at':time.time()};g['function_tree_head']=p['version'];return
    if action=='stage_plan':
        keys={'id','version','title','goal','scope','non_goals','priority','input_anchor','repo','tasks','criteria','entry_stages','reviewer','reason'}
        fields(p,keys,keys);uid(p['id']);uid(p['version'],'阶段版本');ref=p['id']+'@'+p['version']
        if ref in g['product_stages']:raise BoardError('阶段版本不可覆盖',409)
        for key in ('title','goal','scope','non_goals','reason'):text(p[key],key,4000)
        if type(p['priority']) is not str or p['priority'] not in PRIORITIES:raise BoardError('阶段优先级无效')
        if type(p['input_anchor']) is not str or p['input_anchor'] and not re.fullmatch(r'(git:[0-9a-f]{40}|sha256:[0-9a-f]{64})',p['input_anchor']):raise BoardError('阶段基线需完整Git/SHA256锚点，未知可暂留空')
        if type(p['repo']) is not str or len(p['repo'])>80:raise BoardError('仓库ID无效')
        if p['input_anchor'].startswith('git:') and not p['repo']:raise BoardError('Git基线需项目仓库')
        if not p['input_anchor'].startswith('git:') and p['repo']:raise BoardError('非Git基线不声明仓库')
        if type(p['reviewer']) is not str or p['reviewer']!='root' and g['members'].get(p['reviewer'],{}).get('role') not in ('owner','se','reviewer'):raise BoardError('阶段审核者需本项目负责人/SE',409)
        if type(p['tasks']) is not list or len(p['tasks'])>2048:raise BoardError('阶段任务需有界列表')
        assigned=set()
        for item in p['tasks']:
            fields(item,{'task','stage'},{'task','stage'})
            if type(item['task']) is not str or item['task'] not in ts:raise BoardError('任务不属于本项目',404)
            if item['task'] in assigned:raise BoardError('阶段任务重复')
            assigned.add(item['task'])
            if type(item['stage']) is not str or item['stage'] not in RESULTS:raise BoardError('需明确 accepted/merged/native_accepted')
        identifiers(p['entry_stages'],'阶段验收前置',64)
        if not set(p['entry_stages'])<=set(g['product_stages']):raise BoardError('阶段验收前置版本不存在',409)
        pending=[(ref,1) for ref in p['entry_stages']];depths={}
        while pending:
            before,depth=pending.pop()
            if depth>32:raise BoardError('阶段验收前置最多32层')
            if depths.get(before,0)>=depth:continue
            depths[before]=depth
            pending.extend((ref,depth+1) for ref in g['product_stages'][before]['entry_stages'])
        if type(p['criteria']) is not list or not 1<=len(p['criteria'])<=32:raise BoardError('需1至32项产品验收条件')
        ids=set()
        for c in p['criteria']:
            fields(c,{'id','expected'},{'id','expected'});uid(c['id']);text(c['expected'],'产品验收条件',4000)
            if c['id'] in ids:raise BoardError('阶段验收条件重复')
            ids.add(c['id'])
        g['product_stages'][ref]={**deepcopy(p),'by':actor['id'],'at':time.time(),'reviews':[]};g['product_stage_heads'][p['id']]=ref;return
    if action=='stage_focus':
        fields(p,{'ref','reason'},{'ref','reason'});text(p['reason'],'聚焦依据',4000)
        if type(p['ref']) is not str or p['ref'] and p['ref'] not in g['product_stages']:raise BoardError('阶段版本不存在',404)
        if p['ref'] and p['ref'] not in g['product_stage_heads'].values():raise BoardError('请选择当前阶段版本',409)
        g['stage_focus']={**deepcopy(p),'by':actor['id'],'at':time.time()};return
    fields(p,{'ref','scope','input_anchor','result','checks','summary','evidence'},{'ref','scope','input_anchor','result','checks','summary','evidence'})
    if type(p['ref']) is not str or p['ref'] not in g['product_stages']:raise BoardError('阶段版本不存在',404)
    plan=g['product_stages'][p['ref']]
    if actor['id']!=plan['reviewer']:raise BoardError('仅指定阶段审核者可核定',403)
    from .operations import load as operations_load
    from .git_tracking import load as git_load
    git=git_load(db);check=stage_check(g,ts,operations_load(db),git,p['ref'])
    if p['scope']!=check['scope'] or p['input_anchor']!=plan['input_anchor']:raise BoardError('阶段范围/基线已变化，重读后核对',409)
    if type(p['result']) is not str or p['result'] not in ('pass','fail'):raise BoardError('阶段结论无效')
    if type(p['checks']) is not list or not 1<=len(p['checks'])<=32:raise BoardError('需逐项核对阶段标准')
    ids=set()
    for row in p['checks']:
        fields(row,{'id','result','summary'},{'id','result','summary'});uid(row['id']);text(row['summary'],'核对结论',4000)
        if row['id'] in ids or type(row['result']) is not str or row['result'] not in ('pass','fail'):raise BoardError('核对项重复或结论无效')
        ids.add(row['id'])
    if ids!={c['id'] for c in plan['criteria']}:raise BoardError('必须核对全部产品验收条件',409)
    text(p['summary'],'阶段核对依据',4000);evidence(p['evidence']);observation=None
    if p['result']=='pass':
        if p['ref'] not in g['product_stage_heads'].values():raise BoardError('历史阶段版本不可作为当前阶段新通过',409)
        if check['blockers'] or any(c['result']!='pass' for c in p['checks']):raise BoardError('；'.join(check['blockers']) or '逐项标准尚未通过',409)
        if plan['input_anchor'].startswith('git:'):
            from .workflow import reader,ancestry
            rd,repo=reader(store,db,plan['repo']);target=plan['input_anchor'][4:];rd.commit(target)
            for item in plan['tasks']:
                t=ts[item['task']]
                if item['stage']=='accepted':continue
                anchor=(t.get('native') if item['stage']=='native_accepted' else t.get('last_merge')) or {}
                commit=anchor.get('commit')
                if not commit or not ancestry(rd,commit,target):raise BoardError('阶段基线未核实包含任务成果：'+item['task'],409)
            observation={'repository':repo['repository'],'target':target,'commit_observed':True,'meaning':'只读对象与提交包含关系；场景是否通过由SE逐项证据核对'}
    plan['reviews'].append({**deepcopy(p),'by':actor['id'],'at':time.time(),'git_observation':observation})


def projection(g,ts,ops,git):
    prepare(g);cache={};stages={ref:{'plan':deepcopy(p),'state':stage_check(g,ts,ops,git,ref,cache)} for ref,p in g['product_stages'].items()}
    return {'schema':1,'stages':stages,'heads':g['product_stage_heads'],'focus':g['stage_focus'],
            'tree':tree_projection(g,ts),'task_hints':task_hints(g,ts),
            'policy':'阶段用于优先级和交付范围；不自动阻止独立任务领取。硬依赖、接口、权限及资源仍按原规则校验。'}


def snapshot(store,actor):
    from .governance import load,tasks
    from .operations import load as operations_load
    from .git_tracking import load as git_load
    with store.connection() as db:
        db.execute('BEGIN');g=load(db);ts=tasks(db);op=operations_load(db);git=git_load(db)
    result=projection(g,ts,op,git);result.update(project_id=store.registry.project,revision=g['revision']);return result
