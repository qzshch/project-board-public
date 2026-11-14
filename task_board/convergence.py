"""Bounded third-batch completion over existing project journals.

Draft simulation uses a SAVEPOINT and original validators. Reuse is authority
granted by SE, not a worker risk declaration. Attempts record execution facts;
this module never starts agents, creates worktrees or schedules other projects.
"""
from copy import deepcopy
import json,re,time,uuid
from .store import BoardError,fields,text,integer,identifiers,evidence,digest,canonical
from .operations import manager
from .workflow import uid,task,current,input_anchor,reader,run_refs

KEYS=('drafts','rules','bindings','workspaces','attempt_policies','attempts','sessions','selections','templates','instances')
ACTIONS={'draft_save','draft_preview','draft_publish','draft_reject','rule_register','rule_review','rule_retire','rule_bind','rule_unbind','workspace_register','attempt_policy','attempt_open','attempt_heartbeat','attempt_finish','attempt_recover','attempt_select','session_attach','template_register','template_review','template_retire','template_instantiate','template_import'}
GOV_KINDS={'module_plan','milestone_plan','planning_decision','contract_freeze'}
OP_KINDS={'case','criteria_defaults','rule_register'}
MANAGERS={'owner','se','reviewer'}
RESERVED={'running','needs_recovery'}

def prepare(v):
    for key in KEYS:v.setdefault('cv_'+key,{})
    return v
def checked(p,keys):fields(p,set(keys.split()),set(keys.split()))
def row(p,actor,now):return {**deepcopy(p),'by':actor['id'],'at':now}
def exact(rows,key):
    if type(key) is not str or key not in rows:raise BoardError('本项目对象不存在',404)
    return rows[key]
def array(value,label,maximum=64):
    if type(value) is not list or len(value)>maximum:raise BoardError(label+'需有界数组')
def boolean(value):
    if type(value) is not bool:raise BoardError('需要布尔值')
def version(p):
    from .planning import ref_of
    return ref_of(p)
def public_refs(v,g,ts,refs,actor,r):
    from .coordination import prepare as co_prepare,reference
    co_prepare(v);array(refs,'来源',32)
    for ref in refs:reference(v,g,ts,ref,actor,r)
def paths(values):
    from .git_reader import safe_path
    identifiers(values,'授权路径')
    if not values:raise BoardError('需明确有限路径')
    for path in values:safe_path(path.rstrip('/'))
def within(path,allowed):return any(path==a.rstrip('/') or path.startswith(a.rstrip('/')+'/') for a in allowed)
def risky(path):
    # Conservative escalation, not semantic proof of low risk. Unknown effects
    # still require a manager. Symlinks and executable config are checked too.
    parts=re.split(r'[/._-]',path.casefold())
    return bool(set(parts)&{'auth','authentication','authorization','permission','permissions','security','migration','migrations','database','db','deploy','deployment','production','secret','secrets','credential','credentials'}) or path.startswith(('.github/','.env'))

def gov_append(store,db,actor,action,p):
    from .governance import load,Governance
    g=load(db);seq=g.pop('revision');previous=g.pop('head');Governance(store)._mutate(db,g,actor,'owner',action,deepcopy(p))
    rid='cv-'+uuid.uuid4().hex;request={'request_id':rid,'expected_revision':seq,'action':action,'payload':p};event={'action':action,'payload':deepcopy(p),'state':g,'at':time.time()}
    h=digest({'seq':seq+1,'actor':actor['id'],'request_id':rid,'event':event,'previous':previous})
    db.execute('INSERT INTO governance_events VALUES(?,?,?,?,?,?,?)',(seq+1,actor['id'],rid,digest(request),canonical(event),previous,h));return g

def draft_items(items):
    array(items,'关联修改',32)
    if not items:raise BoardError('需关联修改')
    seen=set()
    for item in items:
        checked(item,'key kind payload');uid(item['key']);text(item['kind'],'修改类型',40)
        if item['key'] in seen or item['kind'] not in GOV_KINDS|OP_KINDS|{'task_create','task_scope'} or type(item['payload']) is not dict:raise BoardError('草案修改类型、键或载荷无效')
        seen.add(item['key'])
        if item['kind']=='module_plan' and 'knowledge_refs' not in item['payload']:raise BoardError('新草案模块须显式列knowledge_refs，无引用填[]')
        p=item['payload']
        list_keys={'module_plan':('depends_on','interfaces','decisions','planning_tasks','knowledge_refs','inputs','outputs'),'milestone_plan':('modules','tasks'),'planning_decision':('research_tasks',),'rule_register':('contracts','cases'),'case':('targets','resources')}
        for key in list_keys.get(item['kind'],()):
            if key in p:identifiers(p[key],key)
        for key in ('id','version','module','parent'):
            if key in p and type(p[key]) is not str:raise BoardError(key+'需字符串')
        if item['kind'].startswith('task_'):
            spec=p.get('spec')
            if type(spec) is not dict or type(spec.get('id')) is not str:raise BoardError('spec需对象及任务ID')
            if 'depends_on' in spec:identifiers(spec['depends_on'],'任务依赖')
            w=spec.get('work',{})
            if type(w) is not dict:raise BoardError('work需对象')
            for key in ('contracts','assets'):
                if key in w:identifiers(w[key],key)
            if 'planning' in w and (type(w['planning']) is not dict or type(w['planning'].get('module')) is not str):raise BoardError('planning需明确模块版本')
    return deepcopy(items)

def order_items(items):
    producers={};deps={e['key']:set() for e in items}
    def output(item):
        p=item['payload'];kind=item['kind']
        if kind in ('task_create','task_scope'):return 'task:'+str(p.get('spec',{}).get('id'))
        if kind in ('module_plan','contract_freeze','case','rule_register','milestone_plan'):return kind+':'+str(p.get('id'))+'@'+str(p.get('version'))
        return kind+':'+str(p.get('id'))
    for e in items:
        out=output(e)
        if out in producers:raise BoardError('草案重复修改同一对象：'+out,409)
        producers[out]=e['key']
        if e['kind']=='module_plan':
            name='module:'+str(e['payload'].get('id'))
            if name in producers:raise BoardError('同一批每个模块只登记一个新版本',409)
            producers[name]=e['key']
    for e in items:
        p=e['payload'];refs=[];kind=e['kind']
        if kind=='module_plan':
            refs+=['module_plan:'+x for x in p.get('depends_on',[])]+['contract_freeze:'+x for x in p.get('interfaces',[])]+['planning_decision:'+x for x in p.get('decisions',[])]+['task:'+x for x in p.get('planning_tasks',[])]
            if p.get('parent'):refs+=['module:'+p['parent']]
        if kind.startswith('task_'):
            spec=p.get('spec',{});w=spec.get('work',{})
            refs+=['task:'+x for x in spec.get('depends_on',[])]+['contract_freeze:'+x for x in w.get('contracts',[])]
            if w.get('planning'):refs+=['module_plan:'+w['planning']['module']]
        if kind=='milestone_plan':refs+=['module_plan:'+x for x in p.get('modules',[])]+['task:'+x for x in p.get('tasks',[])]
        if kind=='rule_register':refs+=['module_plan:'+p.get('module','')]+['contract_freeze:'+x for x in p.get('contracts',[])]+['case:'+x for x in p.get('cases',[])]
        if kind=='case':
            identifiers(p.get('targets',[]),'覆盖关系')
            for target in p.get('targets',[]):
                typ,_,key=target.partition(':');refs.append({'module':'module_plan:','task':'task:','contract':'contract_freeze:'}.get(typ,'unknown:')+key)
        for ref in refs:
            if ref in producers:deps[e['key']].add(producers[ref])
    result=[];pending={e['key']:e for e in items}
    while pending:
        ready=[key for key in pending if not deps[key]&pending.keys()]
        if not ready:raise BoardError('草案关联成环：'+' → '.join(pending),409)
        for key in ready:result.append(pending.pop(key))
    return result

def read_set(v,g,ts,items,refs):
    """Only citations and potentially coupled boundaries invalidate a preview."""
    from .planning import module_check,prepare as planning_prepare
    planning_prepare(g)
    reads={'章程':digest({k:g.get('knowledge',{}).get(k) for k in ('background','goals','non_goals','constraints')})}
    locations={x['location']:x for k in ('materials','entries') for x in g.get('knowledge',{}).get(k,[])}
    for item in items:
        p=item['payload'];kind=item['kind'];spec=p.get('spec',{});w=spec.get('work',{});module=w.get('planning',{}).get('module') or p.get('module')
        for path in p.get('knowledge_refs',[]):reads['材料:'+path]=digest(locations.get(path))
        tids=[*spec.get('depends_on',[]),*p.get('planning_tasks',[]),*p.get('research_tasks',[])]
        if kind.startswith('task_'):tids+=[spec.get('id')]
        for tid in tids:reads['任务:'+str(tid)]=digest(ts.get(tid))
        for ref in [*w.get('contracts',[]),*p.get('interfaces',[]),*p.get('contracts',[])]:reads['接口:'+ref]=digest(g.get('contracts',{}).get(ref))
        for ref in p.get('decisions',[]):reads['决策:'+ref]=digest(g.get('planning_decisions',{}).get(ref))
        for ref in (p.get('depends_on',[]) if kind=='module_plan' else []):reads['模块:'+ref]=digest(module_check(g,ts,ref))
        if module:reads['模块:'+module]=digest(module_check(g,ts,module))
        if kind=='module_plan':
            reads['模块目标:'+p['id']]=digest(g.get('module_heads',{}).get(p['id']))
            for ref in g.get('module_heads',{}).values():
                other=g['modules'][ref]
                if set(p.get('outputs',[]))&set(other['inputs']) or set(p.get('inputs',[]))&set(other['outputs']):reads['产物边界:'+ref]=digest(other)
        if kind=='contract_freeze':reads['接口目标:'+p['id']+'@'+p['version']]=digest(g.get('contracts',{}).get(p['id']+'@'+p['version']))
        for alias in w.get('assets',[]):reads['资产:'+alias]=digest(w.get('asset_locks',{}).get(alias) or g.get('assets',{}).get(alias) or g.get('consumption',{}).get(alias))
        for case in p.get('cases',[]):reads['用例:'+case]=digest([v['cases'].get(case),v['case_status'].get(case,{}).get('status')])
    from .coordination import reference
    for ref in refs:
        maps={'intake':v.get('co_intakes',{}),'task':ts,'module':g.get('modules',{}),'resource':g.get('resource_entries',{}),'finding':v.get('wf_findings',{}),'run':v['runs'],'case':v['cases'],'thread':v.get('wf_threads',{}),'checkpoint':v.get('co_checkpoints',{}),'batch':v.get('co_batches',{}),'asset':g.get('assets',{})}
        reads['来源:'+ref['kind']+':'+ref['id']]=digest(maps.get(ref['kind'],{}).get(ref['id']))
    return reads

def simulate(store,db,v,draft,actor,modules,rules=(),dry=True):
    from .governance import load,tasks
    from .workflow import mutate as wf_mutate
    from .quality import mutate as quality_mutate
    work=deepcopy(v) if dry else v;effects=[]
    if dry:db.execute('SAVEPOINT cv_draft')
    try:
        for item in order_items(draft['items']):
            kind=item['kind'];p=deepcopy(item['payload'])
            if kind.startswith('task_'):
                action='create' if kind=='task_create' else 'scope';tid=p.get('spec',{}).get('id');t=tasks(db).get(tid)
                if action=='create' and t or action=='scope' and not t:raise BoardError('任务创建/变更基线不匹配',409)
                validated=store._validate(db,actor,tid,t,action,p);store._append(db,actor,tid,action,validated);p=validated
            elif kind in GOV_KINDS:gov_append(store,db,actor,kind,p)
            elif kind=='rule_register':
                rule_g=load(db)
                if getattr(store,'registry',None):rule_g['consumption']=store.registry.consumption()
                mutate(work,db,actor,'owner',kind,p,time.time(),rule_g,tasks(db),store)
            elif kind=='criteria_defaults':wf_mutate(work,db,actor,'owner',kind,p,time.time(),load(db),tasks(db),store)
            else:quality_mutate(work,db,actor,'owner',kind,p,time.time(),load(db),tasks(db))
            effects.append({'key':item['key'],'kind':kind,'payload':p})
        from .planning import module_check
        remaining=list(modules)
        while remaining:
            progressed=False
            for ref in remaining[:]:
                g=load(db);c=module_check(g,tasks(db),ref)
                if c['blockers']:continue
                gov_append(store,db,actor,'module_review',{'ref':ref,'scope':c['scope'],'result':'approve','summary':'SE批准关联规划草案：'+draft['title'],'evidence':draft['evidence']});remaining.remove(ref);progressed=True
            if not progressed:raise BoardError('所选模块仍有未知项或未满足依赖：'+'、'.join(remaining),409)
        g=load(db);ts=tasks(db)
        for ref in rules:
            rule=exact(work['cv_rules'],ref);state=rule_state(work,g,ts,rule,time.time())
            if state['reasons']!=['治理规则未批准']:raise BoardError('规则引用未就绪：'+ref,409)
            rule['review']={'result':'approve','context':state['context'],'reason':'SE批准关联草案','by':actor['id'],'at':time.time()}
        readiness={ref:module_check(g,ts,ref) for ref in [e['payload']['id']+'@'+e['payload']['version'] for e in draft['items'] if e['kind']=='module_plan']}
        # Publish and preview use the same normalized effects. UUIDs, wall time
        # and generated event IDs are intentionally absent from the manifest.
        result={'effects':effects,'modules':{ref:{k:c[k] for k in ('scope','ready','blockers')} for ref,c in readiness.items()}}
    finally:
        if dry:db.execute('ROLLBACK TO cv_draft');db.execute('RELEASE cv_draft')
    return result

def rule_context(v,g,ts,rule):
    from .planning import module_check
    module=module_check(g,ts,rule['module'])
    return {'模块':digest([module['scope'],module['ready']]),
            **{'接口:'+ref:digest(g.get('contracts',{}).get(ref)) for ref in rule['contracts']},
            **{'资产:'+ref:digest(g.get('assets',{}).get(ref) or g.get('consumption',{}).get(ref)) for ref in rule['assets']},
            **{'用例:'+ref:digest([v['cases'].get(ref),v['case_status'].get(ref,{}).get('status')]) for ref in rule['cases']}}

def register_rule(v,p,actor,now,g,ts):
    checked(p,'id version title module paths categories level repo contracts assets default_items cases plan_mode expires_at reason evidence');ref=version(p)
    if ref in v['cv_rules']:raise BoardError('治理规则版本不可覆盖',409)
    for key in ('title','reason'):text(p[key],key,4000)
    exact(g.get('modules',{}),p['module']);paths(p['paths']);identifiers(p['categories'],'任务类型');identifiers(p['contracts'],'接口');identifiers(p['cases'],'用例');identifiers(p['default_items'],'默认完成清单')
    from .governance import CATEGORIES
    if not p['categories'] or not set(p['categories'])<=CATEGORIES or p['level'] not in ('light','standard') or p['plan_mode'] not in ('module_covered','se_review'):raise BoardError('规则类别、档位或实施策略无效')
    if p['level']=='light' and any(risky(path) for path in p['paths']):raise BoardError('高风险路径不能批准轻量复用',409)
    if type(p['assets']) is not dict or len(p['assets'])>32:raise BoardError('资产需固定SHA映射')
    for alias,sha in p['assets'].items():
        text(alias,'资产引用',180)
        if type(sha) is not str or not re.fullmatch('[0-9a-f]{64}',sha):raise BoardError('资产需实际SHA')
        asset=g.get('assets',{}).get(alias) or g.get('consumption',{}).get(alias)
        if not asset or asset['sha256']!=sha:raise BoardError('规则资产版本不匹配',409)
    if not p['default_items'] or len(p['default_items'])>16:raise BoardError('需1至16条默认完成要求')
    for refcase in p['cases']:
        if refcase not in v['cases'] or v['case_status'][refcase]['status']!='active':raise BoardError('规则用例不存在或已撤回',409)
    for refcontract in p['contracts']:
        if g.get('contracts',{}).get(refcontract,{}).get('status')!='frozen':raise BoardError('规则接口未冻结',409)
    integer(p['expires_at'],'有效期UTC秒',1)
    if not now<p['expires_at']<=now+366*86400:raise BoardError('规则需未来一年内的明确有效期')
    if type(p['repo']) is not str:raise BoardError('仓库ID需字符串')
    if p['evidence']:evidence(p['evidence'])
    v['cv_rules'][ref]={**row(p,actor,now),'review':None,'retired':None}
    return ref

def rule_state(v,g,ts,rule,now):
    from .planning import module_check
    context=rule_context(v,g,ts,rule);review=rule.get('review');reasons=[]
    if rule.get('retired'):reasons.append('规则已撤回')
    if now>=rule['expires_at']:reasons.append('规则已到期')
    if not module_check(g,ts,rule['module'])['ready']:reasons.append('模块当前规划未通过')
    module=g.get('modules',{}).get(rule['module'])
    if module and g.get('module_heads',{}).get(module['id'])!=rule['module']:reasons.append('模块已新增规划版本，需SE核对迁移')
    if any(g.get('contracts',{}).get(ref,{}).get('status')!='frozen' for ref in rule['contracts']):reasons.append('接口不再冻结')
    if any(v['case_status'].get(ref,{}).get('status')!='active' for ref in rule['cases']):reasons.append('用例已撤回')
    if any((g.get('assets',{}).get(ref) or g.get('consumption',{}).get(ref) or {}).get('sha256')!=sha for ref,sha in rule['assets'].items()):reasons.append('资产固定消费已变化')
    if any((g.get('consumption',{}).get(ref) or {}).get('status')=='withdrawn' for ref in rule['assets']):reasons.append('共享资产已撤回，须更换明确版本')
    if not review or review['result']!='approve':reasons.append('治理规则未批准')
    elif review['context']!=context:reasons += ['引用变化：'+key for key in sorted(set(context)|set(review['context'])) if context.get(key)!=review['context'].get(key)]
    return {'valid':not reasons,'reasons':reasons,'context':context,'context_hash':digest(context)}

def binding_state(v,t,g,ts=None,now=None):
    binding=v.get('cv_bindings',{}).get(t['spec']['id'])
    if not binding:return None
    rule=v.get('cv_rules',{}).get(binding['ref']);now=now or time.time();reasons=[]
    if not current(binding,t):reasons.append('任务范围已变化')
    state=rule_state(v,g,ts or {t['spec']['id']:t},rule,now) if rule else {'valid':False,'reasons':['规则不存在']}
    reasons+=state['reasons'];w=t['spec'].get('work',{})
    if rule:
        if w.get('planning',{}).get('module')!=rule['module'] or w.get('category') not in rule['categories']:reasons.append('模块或任务类型越出批准边界')
        if any(not within(path.rstrip('/'),rule['paths']) for path in t['spec']['allowed_paths']):reasons.append('任务路径越出批准边界')
        if set(w.get('contracts',[]))!=set(rule['contracts']):reasons.append('接口版本越出批准边界')
        locks={alias:lock['sha256'] for alias,lock in w.get('asset_locks',{}).items()}
        if locks!=rule['assets']:reasons.append('资产固定版本越出批准边界')
        assessment=v.get('assessments',{}).get(t['spec']['id'])
        if assessment and current(assessment,t) and assessment['flags']:reasons.append('已知影响需SE逐卡判断')
    return {'valid':not reasons,'reasons':list(dict.fromkeys(reasons)),'rule':rule,'binding':binding}

def reuse_effective(v,t,g):
    binding=v.get('cv_bindings',{}).get(t['spec']['id'])
    if not binding:return None
    # Full research dependencies are checked by normal planning admission. The
    # rule's module scope is evaluated with the real task map when mutating.
    state=binding_state(v,t,g,g.get('_cv_tasks'))
    return {'valid':state['valid'],'level':state['rule']['level'] if state['rule'] else 'strict','reason':'沿用SE批准规则 '+binding['ref'] if state['valid'] else '；'.join(state['reasons']),'rule':binding['ref']}

def rule_delivery(store,db,v,t,p,g,ts):
    state=binding_state(v,t,g,ts)
    if not state:return
    if not state['valid']:raise BoardError('治理规则失效：'+'；'.join(state['reasons']),409)
    rule=state['rule'];w=t['spec']['work']
    from .assurance import NONCODE
    if w['category'] not in NONCODE or rule['repo']:
        if not rule['repo']:raise BoardError('代码规则需实际只读仓库核验',409)
        rd,_=reader(store,db,rule['repo']);implementation=p.get('implementation_commit');rd.commit(implementation)
        from .workflow import ancestry
        if not ancestry(rd,w['baseline'],implementation):raise BoardError('规则交付基线不在实际实现链',409)
        for file in rd.files(w['baseline'],implementation):
            path=file['path'];rd.allowed(path)
            if not within(path,rule['paths']) or not within(path,t['spec']['allowed_paths']) or risky(path):raise BoardError('实际变更越界或需SE升级评审：'+path,409)
            for item in rd.tree(implementation,path):
                if item['path']==path and item['mode'] not in ('100644','100755'):raise BoardError('未知链接/子模块影响须SE核定',409)
    if rule['cases']:
        from .quality import validate_delivery
        validate_delivery(v,t,p)

def attempt_state(v,e,t,now):
    if not current(e,t):return 'needs_recovery' if e['status'] in RESERVED else e['status']
    if e['status']=='running' and e['lease']['expires']<=now:return 'needs_recovery'
    return e['status']

def lease_check(e,p,actor,t,now):
    if e['actor']!=actor['id']:raise BoardError('仅此尝试执行者操作',403)
    if e['status']!='running' or not current(e,t) or e['lease']['id']!=p.get('lease') or e['lease']['expires']<=now:raise BoardError('尝试租约、范围或状态已失效，须SE核对',409)

def attempt_enforce(v,t,action,p,actor,now):
    policy=v.get('cv_attempt_policies',{}).get(t['spec']['id'])
    if not policy:return
    attempts=[e for e in v.get('cv_attempts',{}).values() if e['task']==t['spec']['id']]
    if action=='progress':
        e=exact(v.get('cv_attempts',{}),p.get('attempt_id'))
        if e['task']!=t['spec']['id']:raise BoardError('尝试不属于当前任务',409)
        lease_check(e,{'lease':p.get('attempt_lease')},actor,t,now);return
    if action=='submit':
        selection=v.get('cv_selections',{}).get(t['spec']['id']);e=v.get('cv_attempts',{}).get(p.get('attempt_id'))
        if not selection or not current(selection,t) or selection['id']!=p.get('selection_id') or not e or selection['attempt']!=e['id'] or e['status']!='selected':raise BoardError('提交需SE当前选择的有效尝试与回执',409)
        anchor='git:'+p['implementation_commit'] if p.get('implementation_commit') else 'sha256:'+p.get('artifact',{}).get('sha256','')
        if anchor!=e['result']['input_anchor']:raise BoardError('提交输入与SE选择的候选不一致',409)
        if any(a['status'] in RESERVED for a in attempts):raise BoardError('其他尝试或旧工作区仍需核对，不能交付',409)

def enforce(store,db,t,action,p,actor):
    from .operations import load
    from .governance import load as gov,tasks
    v=load(db);g=gov(db);ts=tasks(db);g['_cv_tasks']=ts
    if getattr(store,'registry',None):g['consumption']=store.registry.consumption()
    if action in ('accept','merge','native'):
        binding=binding_state(v,t,g,ts)
        if binding and not binding['valid']:raise BoardError('治理规则引用变化，需SE核定：'+'；'.join(binding['reasons']),409)
    if action=='submit':rule_delivery(store,db,v,t,p,g,ts)
    if action in ('submit','progress'):attempt_enforce(v,t,action,p,actor,time.time())

def validate_template(p):
    checked(p,'id version title description parameters items resource_categories reason');version(p)
    for key in ('title','description','reason'):text(p[key],key,4000)
    identifiers(p['parameters'],'模板参数');identifiers(p['resource_categories'],'资源分类')
    from .resources import CATEGORIES
    if not set(p['resource_categories'])<=set(CATEGORIES) or len(p['parameters'])>24:raise BoardError('模板分类或参数无效')
    for param in p['parameters']:uid(param)
    draft_items(p['items'])
    def walk(value,key=''):
        if key.casefold() in {'token','password','secret','private_key','credentials','profile','state','members','actors','connection','worktree_path'}:raise BoardError('模板不得携带凭据、身份或运行快照')
        if type(value) is dict:
            for k,val in value.items():walk(val,k)
        elif type(value) is list:
            for val in value:walk(val,key)
        elif type(value) is str:
            if '-----BEGIN ' in value or re.search(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})',value):raise BoardError('模板含疑似凭据')
            if key in ('owner','baseline') and not re.fullmatch(r'\$\{[A-Za-z0-9._-]+\}',value):raise BoardError('模板负责人和基线必须使用参数')
            if key in ('location','shared_location') and not re.fullmatch(r'\$\{[A-Za-z0-9._-]+\}',value):raise BoardError('模板机器位置必须使用新项目参数')
            unknown=set(re.findall(r'\$\{([^}]+)\}',value))-set(p['parameters'])
            if unknown:raise BoardError('模板引用未声明参数')
    walk(p);return deepcopy(p)

def expand(value,params):
    if type(value) is dict:return {k:expand(v,params) for k,v in value.items()}
    if type(value) is list:return [expand(v,params) for v in value]
    if type(value) is str:return re.sub(r'\$\{([^}]+)\}',lambda m:params[m[1]],value)
    return value

def mutate(v,db,actor,r,action,p,now,g,ts,store):
    prepare(v)
    for key in {'id','version','ref','title','reason','task','scope','manifest_hash','context_hash','result','repo','location','machine','branch','actor','workspace','attempt','lease','input_anchor','summary','status','session','tool','model','previous','checkpoint','template','document'}&p.keys():
        if type(p[key]) is not str or len(p[key])>(100000 if key=='document' else 8000):raise BoardError(key+'需有界字符串')
    if action=='draft_save':
        checked(p,'id version title items references reason evidence');ref=version(p);text(p['title'],'草案标题',200);text(p['reason'],'规划依据',8000);items=draft_items(p['items']);public_refs(v,g,ts,p['references'],actor,r)
        if ref in v['cv_drafts']:raise BoardError('草案版本不可覆盖',409)
        if p['evidence']:evidence(p['evidence'])
        v['cv_drafts'][ref]={**row(p,actor,now),'items':items,'status':'draft','preview':None};return {'draft':ref}
    if action in ('draft_preview','draft_publish','draft_reject'):
        manager(r);draft=exact(v['cv_drafts'],p.get('ref'))
        if draft['status']!='draft':raise BoardError('仅待审草案可预览/发布/退回',409)
        if action=='draft_reject':
            checked(p,'ref reason');text(p['reason'],'退回依据');draft.update(status='rejected',decision=row(p,actor,now));return
        public_refs(v,g,ts,draft['references'],actor,r)
        if action=='draft_preview':
            checked(p,'ref approve_modules approve_rules');identifiers(p['approve_modules'],'所选模块');identifiers(p['approve_rules'],'所选规则')
            created_modules={e['payload']['id']+'@'+e['payload']['version'] for e in draft['items'] if e['kind']=='module_plan'}
            created_rules={e['payload']['id']+'@'+e['payload']['version'] for e in draft['items'] if e['kind']=='rule_register'}
            if not set(p['approve_modules'])<=created_modules or not set(p['approve_rules'])<=created_rules:raise BoardError('只能批准本草案新增的明确版本',409)
            compiled=simulate(store,db,v,draft,actor,p['approve_modules'],p['approve_rules']);reads=read_set(v,g,ts,draft['items'],draft['references'])
            preview={'compiled':compiled,'reads':reads,'approve_modules':p['approve_modules'],'approve_rules':p['approve_rules'],'draft_hash':digest({k:draft[k] for k in ('id','version','title','items','references','reason','evidence')}),'approver':actor['id']}
            preview['manifest_hash']=digest(preview);draft['preview']=preview;return {'manifest_hash':preview['manifest_hash'],'order':[e['key'] for e in compiled['effects']]}
        checked(p,'ref manifest_hash reason evidence');text(p['reason'],'批量批准依据');evidence(p['evidence']);preview=draft.get('preview')
        if not preview or preview['manifest_hash']!=p['manifest_hash'] or preview['approver']!=actor['id']:raise BoardError('需同一SE核对当前预览摘要',409)
        reads=read_set(v,g,ts,draft['items'],draft['references']);changed=[key for key in set(reads)|set(preview['reads']) if reads.get(key)!=preview['reads'].get(key)]
        if changed:raise BoardError('草案预览已过期：'+'；'.join(sorted(changed)),409)
        compiled=simulate(store,db,v,draft,actor,preview['approve_modules'],preview['approve_rules'])
        if compiled!=preview['compiled']:raise BoardError('实际影响或固定资产已变化，重新预览',409)
        simulate(store,db,v,draft,actor,preview['approve_modules'],preview['approve_rules'],False)
        draft.update(status='published',decision=row(p,actor,now));return {'draft':p['ref'],'applied':len(compiled['effects'])}
    if action=='rule_register':
        manager(r);ref=register_rule(v,p,actor,now,g,ts)
        if p['repo']:reader(store,db,p['repo'])
        return {'rule':ref}
    if action in ('rule_review','rule_retire'):
        manager(r);rule=exact(v['cv_rules'],p.get('ref'));text(p.get('reason'),'核定依据')
        if action=='rule_retire':
            checked(p,'ref reason');rule['retired']=row(p,actor,now);return
        checked(p,'ref context_hash result reason evidence');evidence(p['evidence']);state=rule_state(v,g,ts,rule,now)
        if p['context_hash']!=state['context_hash'] or p['result'] not in ('approve','reject'):raise BoardError('规则评审范围已变化',409)
        if p['result']=='approve' and (rule['retired'] or now>=rule['expires_at']):raise BoardError('过期或撤回的规则需新版本',409)
        from .planning import module_check
        if p['result']=='approve' and not module_check(g,ts,rule['module'])['ready']:raise BoardError('先核定模块规划',409)
        rule['review']={**row(p,actor,now),'context':state['context']};return
    if action in ('rule_bind','rule_unbind'):
        t=task(db,p)
        if action=='rule_unbind':
            manager(r);checked(p,'task scope scope_version reason');text(p['reason'],'移除绑定依据');v['cv_bindings'].pop(p['task'],None);return
        checked(p,'task scope scope_version ref reason');text(p['reason'],'采用批准规则依据')
        if t['status'] not in {'planned','active','changes_requested'}:raise BoardError('交付后不能改用治理规则；先由SE重新打开范围',409)
        if t['owner'] not in (None,actor['id']) and r not in MANAGERS:raise BoardError('只能为本人任务采用规则',403)
        w=t['spec'].get('work',{})
        if r not in MANAGERS and g.get('members',{}).get(actor['id'],{}).get('role',r)!=w.get('role'):raise BoardError('执行角色不匹配',403)
        rule=exact(v['cv_rules'],p['ref']);trial=deepcopy(v);trial['cv_bindings'][p['task']]={**row(p,actor,now)};state=binding_state(trial,t,g,ts,now)
        if not state['valid']:raise BoardError('不能复用：'+'；'.join(state['reasons']),409)
        from .assurance import FLAGS,STRICT,effective,NONCODE
        # Existing manager assessments with any risk flag require SE handling;
        # a rule never erases known permission, production or unknown impacts.
        if rule['level']=='light' and (w.get('contracts') or w.get('couplings')):raise BoardError('共享接口/耦合不能以轻量规则绕过',409)
        if w['category'] not in NONCODE:
            if not rule['repo']:raise BoardError('代码规则需项目只读仓库',409)
            rd,_=reader(store,db,rule['repo']);rd.commit(w['baseline'])
        old_plan=v.get('wf_plans',{}).get(v.get('wf_plan_heads',{}).get(p['task']))
        if old_plan and (not current(old_plan,t) or not set(rule['default_items'])<=set(x['expected'] for x in old_plan['items'])):raise BoardError('现有验收计划需SE明确合并完成要求',409)
        if old_plan and rule['repo'] and (not old_plan['git_required'] or old_plan['repo']!=rule['repo']):raise BoardError('现有验收计划须SE补齐相同仓库的Git核验',409)
        old_tests=v['test_plans'].get(p['task'])
        if old_tests and (not current(old_tests,t) or not set(old_tests['cases'])<=set(rule['cases'])):raise BoardError('不能覆盖或削弱现有测试计划',409)
        from .workflow import prepare as wf_prepare
        wf_prepare(v)
        if not old_plan:
            plan_id='reuse-'+uuid.uuid4().hex;items=[{'id':'DEL-'+str(i+1),'deliverable':d['id'],'expected':d['label'],'method':'inspection'} for i,d in enumerate(t['spec']['deliverables'])]
            items += [{'id':'DOD-'+str(i+1),'deliverable':t['spec']['deliverables'][0]['id'],'expected':x,'method':'inspection'} for i,x in enumerate(rule['default_items'])]
            v['wf_plans'][plan_id]={'id':plan_id,'task':p['task'],'scope':t['scope_hash'],'scope_version':t['scope_version'],'items':items,'default_items':rule['default_items'],'defaults':'','repo':rule['repo'],'git_required':bool(rule['repo']),'actor':rule['review']['by'],'at':now,'reason':'实例化已批准规则 '+p['ref']};v['wf_plan_heads'][p['task']]=plan_id
        if rule['cases']:v['test_plans'][p['task']]={'task':p['task'],'scope':t['scope_hash'],'scope_version':t['scope_version'],'cases':rule['cases'],'actor':rule['review']['by'],'at':now,'reason':'实例化已批准规则 '+p['ref']}
        v['cv_bindings'][p['task']]={**row(p,actor,now),'context_hash':digest(rule_context(v,g,ts,rule))}
        if rule['plan_mode']=='se_review':v.setdefault('co_plan_policy',{})[p['task']]={**{k:p[k] for k in ('task','scope','scope_version')},'required':True,'reason':'SE批准的规则要求独立实施计划','actor':rule['review']['by'],'at':now}
        return {'rule':p['ref'],'criteria_plan':v['wf_plan_heads'][p['task']]}
    if action=='workspace_register':
        manager(r);checked(p,'id task location machine branch paths resources reason');uid(p['id']);exact(ts,p['task']);paths(p['paths']);identifiers(p['resources'],'资源');text(p['machine'],'机器',200);text(p['branch'],'分支',200);text(p['reason'],'工作区授权依据')
        from .resources import pointer
        pointer(p['location'])
        if p['id'] in v['cv_workspaces']:raise BoardError('工作区登记不可覆盖，使用新ID',409)
        t=ts[p['task']]
        if any(not within(path.rstrip('/'),t['spec']['allowed_paths']) for path in p['paths']) or not set(p['resources'])<=set(t['spec']['work']['resources']):raise BoardError('工作区授权不能扩大任务路径或资源',409)
        v['cv_workspaces'][p['id']]=row(p,actor,now);return
    if action=='attempt_policy':
        manager(r);checked(p,'task scope scope_version actors workspaces max_parallel lease_seconds reason');t=task(db,p);identifiers(p['actors'],'允许执行者');identifiers(p['workspaces'],'允许工作区');integer(p['max_parallel'],'并行上限',1);integer(p['lease_seconds'],'租约秒',30);text(p['reason'],'尝试管理依据')
        if not p['actors'] or not p['workspaces'] or p['max_parallel']>8 or p['lease_seconds']>3600:raise BoardError('需有限执行者/工作区，最多8路，租约30至3600秒')
        for aid in p['actors']:
            role=g['members'].get(aid,{}).get('role','')
            if role not in MANAGERS and role!=t['spec']['work']['role']:raise BoardError('执行者角色未获此任务授权',409)
        for wid in p['workspaces']:
            if exact(v['cv_workspaces'],wid)['task']!=p['task']:raise BoardError('工作区不属于此任务',409)
        if any(e['task']==p['task'] and e['status'] in RESERVED for e in v['cv_attempts'].values()):raise BoardError('先核对并结束已有活跃尝试，再更改策略',409)
        v['cv_attempt_policies'][p['task']]=row(p,actor,now);return
    if action=='attempt_open':
        checked(p,'task scope scope_version id workspace reason');t=task(db,p);uid(p['id']);text(p['reason'],'尝试路径及接续依据')
        policy=exact(v['cv_attempt_policies'],p['task'])
        if not current(policy,t) or actor['id'] not in policy['actors'] or p['workspace'] not in policy['workspaces']:raise BoardError('范围、执行者或工作区未获当前策略批准',403)
        from .governance import ACTIVE
        if t['status'] not in ACTIVE:raise BoardError('先按原流程领取当前任务',409)
        if p['id'] in v['cv_attempts']:raise BoardError('尝试ID不可覆盖',409)
        active=[e for e in v['cv_attempts'].values() if e['task']==p['task'] and e['status'] in RESERVED]
        if len(active)>=policy['max_parallel'] or any(attempt_state(v,e,t,now)=='needs_recovery' for e in active):raise BoardError('达到尝试上限或旧执行者待核对',409)
        ws=v['cv_workspaces'][p['workspace']];key=lambda w:(w['machine'].casefold(),w['location'].replace('\\','/').rstrip('/').casefold())
        for e in v['cv_attempts'].values():
            if e['status'] not in RESERVED:continue
            other=v['cv_workspaces'][e['workspace']]
            a,b=key(ws),key(other)
            if a[0]==b[0] and (a[1]==b[1] or a[1].startswith(b[1]+'/') or b[1].startswith(a[1]+'/')) or set(ws['resources'])&set(other['resources']):raise BoardError('工作区或排他资源仍被旧尝试占用',409)
        lease={'id':uuid.uuid4().hex,'expires':now+policy['lease_seconds']};v['cv_attempts'][p['id']]={**row(p,actor,now),'actor':actor['id'],'status':'running','lease':lease,'baseline':t['spec']['work']['baseline'],'asset_locks':deepcopy(t['spec']['work'].get('asset_locks',{})),'contracts':deepcopy(t['spec']['work']['contracts']),'result':None};return {'attempt':p['id'],'lease':lease['id']}
    if action in ('attempt_heartbeat','attempt_finish','session_attach'):
        e=exact(v['cv_attempts'],p.get('attempt'));t=ts[e['task']];lease_check(e,p,actor,t,now)
        if action=='attempt_heartbeat':
            checked(p,'attempt lease');policy=v['cv_attempt_policies'][e['task']];e['lease']['expires']=now+policy['lease_seconds'];return
        if action=='session_attach':
            checked(p,'attempt lease id session tool model machine previous checkpoint reason');uid(p['id']);text(p['session'],'会话引用',1000);text(p['tool'],'工具',200);text(p['model'],'报告的模型或unknown',200);text(p['machine'],'机器',200);text(p['reason'],'接续说明')
            if p['id'] in v['cv_sessions']:raise BoardError('会话引用不可覆盖',409)
            if p['previous'] and exact(v['cv_sessions'],p['previous'])['attempt']!=e['id']:raise BoardError('前序会话不属于此尝试',409)
            if p['checkpoint']:
                cp=exact(v.get('co_checkpoints',{}),p['checkpoint'])
                if cp['task']!=e['task']:raise BoardError('检查点不属于当前任务',409)
            v['cv_sessions'][p['id']]={**row({k:val for k,val in p.items() if k!='lease'},actor,now),'task':e['task'],'evidence_class':'session_reference_not_process_proof'};return
        checked(p,'attempt lease status input_anchor runs evidence stopped summary');boolean(p['stopped']);text(p['summary'],'实际结果与停止核对');evidence(p['evidence']);identifiers(p['runs'],'实际运行')
        if p['status'] not in ('candidate','failed','cancelled'):raise BoardError('尝试结果无效')
        if not p['stopped']:
            e.update(status='needs_recovery',result=row({k:val for k,val in p.items() if k!='lease'},actor,now));return
        if p['status']=='candidate':input_anchor(p['input_anchor']);run_refs(v,t,p['runs'],p['input_anchor'])
        elif p['input_anchor']:input_anchor(p['input_anchor'])
        e.update(status=p['status'],result=row({k:val for k,val in p.items() if k!='lease'},actor,now));return
    if action=='attempt_recover':
        manager(r);checked(p,'attempt stopped machine summary evidence');e=exact(v['cv_attempts'],p['attempt']);boolean(p['stopped']);text(p['machine'],'核对机器',200);text(p['summary'],'进程/工作区/资源实际核对');evidence(p['evidence'])
        if attempt_state(v,e,ts[e['task']],now)!='needs_recovery':raise BoardError('仅失联/旧范围或明确待恢复尝试可接手核对',409)
        e['recovery']=row(p,actor,now);e['status']='abandoned' if p['stopped'] else 'needs_recovery';return
    if action=='attempt_select':
        manager(r);checked(p,'task scope scope_version attempt reason evidence');t=task(db,p);e=exact(v['cv_attempts'],p['attempt']);text(p['reason'],'候选选择依据');evidence(p['evidence'])
        if e['task']!=p['task'] or not current(e,t) or e['status']!='candidate':raise BoardError('只能选择当前范围已停止并完成的候选',409)
        if any(a['task']==p['task'] and a['status'] in RESERVED for a in v['cv_attempts'].values()):raise BoardError('先核对其他活跃/失联尝试',409)
        for a in v['cv_attempts'].values():
            if a['task']==p['task'] and a['status'] in ('candidate','selected'):a['status']='superseded'
        e['status']='selected';selection={**row(p,actor,now),'id':uuid.uuid4().hex};v['cv_selections'][p['task']]=selection;return {'selection_id':selection['id'],'attempt':e['id']}
    if action in ('template_register','template_import'):
        manager(r)
        if action=='template_import':
            checked(p,'asset document reason');text(p['reason'],'导入依据');consumption=store.registry.consumption().get(p['asset']);sha=__import__('hashlib').sha256(p['document'].encode()).hexdigest()
            if not consumption or consumption['sha256']!=sha:raise BoardError('模板导入必须匹配显式固定共享消费SHA',409)
            store.registry.get(consumption['release'],store.registry.project)
            try:definition=json.loads(p['document'])
            except ValueError:raise BoardError('模板文档需JSON')
            p=definition
        else:consumption=None
        definition=validate_template(p);ref=version(p)
        if ref in v['cv_templates']:raise BoardError('模板版本不可覆盖',409)
        v['cv_templates'][ref]={**row(definition,actor,now),'review':None,'retired':None,'source':consumption};return {'template':ref}
    if action in ('template_review','template_retire'):
        manager(r);template=exact(v['cv_templates'],p.get('ref'));text(p.get('reason'),'模板核定依据')
        if action=='template_retire':checked(p,'ref reason');template['retired']=row(p,actor,now);return
        checked(p,'ref definition_hash result reason');definition=template_definition(template)
        if p['definition_hash']!=digest(definition) or p['result'] not in ('approve','reject') or template['retired']:raise BoardError('模板已变化、撤回或评审无效',409)
        template['review']=row(p,actor,now);return
    if action=='template_instantiate':
        checked(p,'template id version parameters reason evidence');template=exact(v['cv_templates'],p['template']);text(p['reason'],'实例化依据');ref=version(p)
        if template['retired'] or (template['review'] or {}).get('result')!='approve':raise BoardError('模板尚未批准或已撤回',409)
        if template['source']:store.registry.get(template['source']['release'],store.registry.project)
        if type(p['parameters']) is not dict or set(p['parameters'])!=set(template['parameters']):raise BoardError('需准确填写所有已声明参数')
        for value in p['parameters'].values():text(value,'模板参数值',2000)
        if p['evidence']:evidence(p['evidence'])
        items=expand(template['items'],p['parameters']);draft_items(items)
        if ref in v['cv_drafts']:raise BoardError('实例草案版本已存在',409)
        v['cv_drafts'][ref]={'id':p['id'],'version':p['version'],'title':template['title']+' · '+p['id'],'items':items,'references':[],'reason':p['reason'],'evidence':p['evidence'],'status':'draft','preview':None,'by':actor['id'],'at':now}
        v['cv_instances'][ref]={**row(p,actor,now),'definition_hash':digest(template_definition(template))};return {'draft':ref,'requires_se_approval':True}
    raise BoardError('未知收敛动作',404)

def template_definition(t):return {key:deepcopy(t[key]) for key in ('id','version','title','description','parameters','items','resource_categories','reason')}

def commutes(action,p,actor,old,new):
    if action in ('attempt_heartbeat','attempt_finish','session_attach'):
        aid=p.get('attempt');return type(aid) is str and old.get('cv_attempts',{}).get(aid)==new.get('cv_attempts',{}).get(aid)
    if action in ('draft_save','workspace_register'):return True
    if action in ('draft_preview','draft_publish','draft_reject'):
        ref=p.get('ref');return type(ref) is str and old.get('cv_drafts',{}).get(ref)==new.get('cv_drafts',{}).get(ref)
    return False

def sanitize(v,g,actor,r):
    from .coordination import sanitize as co_sanitize,prepare as co_prepare
    from .resources import visible
    co_prepare(v);co_sanitize(v,g,actor,r)
    allowed_resources={key for key,e in g.get('resource_entries',{}).items() if visible(e,r,actor.get('global_admin',False))}
    def allowed(ref):
        return ref['kind']!='resource' or ref['id'] in allowed_resources
    v['cv_drafts']={ref:d for ref,d in v.get('cv_drafts',{}).items() if all(allowed(source) and (source['kind']!='intake' or source['id'] in v.get('co_intakes',{})) for source in d['references'])}
    for e in v.get('cv_attempts',{}).values():
        if e['actor']!=actor['id']:e['lease']={k:val for k,val in e['lease'].items() if k!='id'}
    return v

def workbench(store,db,v,g,ts,actor,r,now):
    from .workflow import snapshot as workflow_snapshot
    from .finishing import TERMINAL
    # Existing workflow rules remain authoritative; only the authorized current
    # action set is added, not another task/delivery queue.
    base=workflow_snapshot(store,actor)['inbox'];items=[{**e,'reason':'按当前任务协作与交付门禁处理'} for e in base if e['kind']!='rollback' and (not e.get('task') or ts[e['task']]['status'] not in TERMINAL or e['kind'] in ('thread','finding'))]
    def add(kind,id,title,taskid='',status='待处理',reason='',action='',seed=None):items.append({'kind':kind,'id':id,'title':title,'task':taskid,'status':status,'reason':reason,'action':action,'seed':seed or {}})
    manager_role=r in MANAGERS
    if manager_role:
        for ref,d in v['cv_drafts'].items():
            if d['status']=='draft':add('draft',ref,d['title'],status='待规划预览 / 批准',reason='相关修改集中核对后一次原子发布')
        for ref,rule in v['cv_rules'].items():
            state=rule_state(v,g,ts,rule,now)
            if not rule['retired'] and not state['valid']:add('rule',ref,rule['title'],status='规则待核定',reason='；'.join(state['reasons']),action='rule_review',seed={'ref':ref,'context_hash':state['context_hash']})
        for ref,tpl in v['cv_templates'].items():
            if not tpl['retired'] and (tpl['review'] or {}).get('result')!='approve':add('template',ref,tpl['title'],status='模板待核定',action='template_review',seed={'ref':ref,'definition_hash':digest(template_definition(tpl))})
        for p in v.get('co_plans',{}).values():
            if ts[p['task']]['status'] in TERMINAL:continue
            if v.get('co_plan_heads',{}).get(p['task'])!=p['id']:continue
            from .coordination import plan_context
            if p['context']!=plan_context(v,ts[p['task']],g):add('implementation',p['id'],'实施计划引用已变化',p['task'],reason='当前范围/验收计划/接口改变，核对新版本')
            elif (p.get('review') or {}).get('result')!='approve':add('implementation',p['id'],'实施计划待审核',p['task'],action='execution_review',seed={'plan':p['id']})
        for e in v.get('co_intakes',{}).values():
            if e['status']=='triage':add('intake',e['id'],e['title'],status='待分诊',action='intake_decide',seed={**deepcopy(e),'expected_version':e['version']})
        for e in v.get('co_gates',{}).values():
            if ts[e['task']]['status'] in TERMINAL:continue
            if e.get('retired'):continue
            from .coordination import gate_ok
            if not current(e,ts[e['task']]) or not gate_ok(v,e,e['input_anchor'],now):add('condition',e['id'],'条件未满足 / 需重新核验',e['task'],reason='已停用历史不进入当前待办')
        for ref,m in g.get('milestone_plans',{}).items():
            if g.get('milestone_heads',{}).get(m['id'])!=ref:continue
            from .planning import milestone_check
            state=milestone_check(g,ts,ref)
            if not state['passed'] and not state['blockers']:add('milestone',ref,'阶段验证：'+m['goal'],reason='任务完成不等于里程碑通过')
    for e in v['cv_attempts'].values():
        if not manager_role and e['actor']!=actor['id']:continue
        status=attempt_state(v,e,ts[e['task']],now)
        if status=='needs_recovery':add('recovery',e['id'],'尝试与工作区待核对',e['task'],status='待恢复',reason='未确认旧执行者停止前保留资源',action='attempt_recover' if manager_role else '',seed={'attempt':e['id']})
        elif status=='candidate' and manager_role:add('candidate',e['id'],'待选择候选成果',e['task'],action='attempt_select',seed={'attempt':e['id']})
    from .governance import blockers,ACTIVE
    active=[];available=[]
    for tid,t in ts.items():
        own_attempts=[e['id'] for e in v['cv_attempts'].values() if e['task']==tid and e['actor']==actor['id'] and current(e,t) and e['status'] in RESERVED|{'candidate','selected'}]
        if (t['owner']==actor['id'] or own_attempts) and t['status'] in ACTIVE:active.append({'id':tid,'title':t['spec']['title'],'status':t['status'],'scope_version':t['scope_version'],'participation':'owner' if t['owner']==actor['id'] else 'participant','attempts':own_attempts})
        if t['status']=='planned' and t['spec'].get('work') and (manager_role or t['spec']['work']['role']==r or t['spec']['work']['role']=='agent'):
            available.append({'id':tid,'title':t['spec']['title'],'blockers':blockers(db,t,actor,getattr(store,'registry',None),context=(ts,g,v))})
    # Stable identity and deterministic priority, independent of model prose.
    unique={e['kind']+':'+e['id']:e for e in items};rank={'recovery':0,'thread':1,'submission':2,'criterion':3,'draft':4,'implementation':5,'rule':6}
    return {'role':'se' if manager_role else 'worker','items':sorted(unique.values(),key=lambda e:(rank.get(e['kind'],10),e['id'])),'my_tasks':active,'claimable':available,'source':'current_authorized_state','not_agent_scheduler':True}

def snapshot(store,actor,task_id=None):
    from .operations import load
    from .governance import load as gov,tasks,role
    with store.connection() as db:
        db.execute('BEGIN');v=prepare(load(db));g=gov(db);ts=tasks(db);r=role(db,actor);now=time.time();g['_cv_tasks']=ts
        if getattr(store,'registry',None):g['consumption']=store.registry.consumption()
        if task_id and task_id not in ts:raise BoardError('本项目任务不存在',404)
        sanitize(v,g,actor,r);data={key:deepcopy(v['cv_'+key]) for key in KEYS}
        data['revision']=v['revision'];data['schema']=1
        for ref,d in data['drafts'].items():
            if d['preview'] and d['status']=='draft':
                reads=read_set(v,g,ts,d['items'],d['references']);d['changed']=[key for key in set(reads)|set(d['preview']['reads']) if reads.get(key)!=d['preview']['reads'].get(key)]
        for ref,rule in data['rules'].items():rule['readiness']=rule_state(v,g,ts,rule,now)
        for tid,b in data['bindings'].items():b['readiness']={k:val for k,val in binding_state(v,ts[tid],g,ts).items() if k in ('valid','reasons')}
        for e in data['attempts'].values():e['effective_status']=attempt_state(v,e,ts[e['task']],now)
        for t in data['templates'].values():t['definition_hash']=digest(template_definition(t))
        data['workbench']=workbench(store,db,v,g,ts,actor,r,now)
        if task_id:
            for key in ('attempts','attempt_policies','sessions','workspaces','selections'):data[key]={k:e for k,e in data[key].items() if e['task']==task_id}
            data['bindings']={k:e for k,e in data['bindings'].items() if k==task_id}
            data['workbench']['items']=[e for e in data['workbench']['items'] if e.get('task')==task_id]
        return data

def context_pack(store,actor,tid,since=''):
    from .brief import build_brief
    # Do not recursively call this function from brief: brief embeds just a URL
    # and small attempt references, while this endpoint performs task slicing.
    project=store.registry.project;brief=build_brief(store,tid,project,'',actor);co=brief['continuation'];module=brief['module_plan'];locations=set((module or {}).get('knowledge_refs',[]));materials=[{**m,'source_kind':'material'} for m in brief['read_materials']]+[{**m,'source_kind':'entry'} for m in brief['project_entries']]
    if module is not None and 'knowledge_refs' in module:materials=[m for m in materials if m['location'] in locations]
    unique={}
    for m in materials:
        if m['location'] in unique:
            first=unique[m['location']];first.setdefault('source_kinds',[first['source_kind']]).append(m['source_kind'])
            registrations=first.setdefault('registrations',[{k:first.get(k,'') for k in ('source_kind','version','sha256')}]);registrations.append({k:m.get(k,'') for k in ('source_kind','version','sha256')})
            first['source_conflict']=len({(x['version'],x['sha256']) for x in registrations})>1
        else:unique[m['location']]=m
    materials=list(unique.values())
    conv=snapshot(store,actor,tid);sources=[]
    def source(kind,id,value):
        sources.append({'kind':kind,'id':id,'sha256':digest(value),'summary':value,'readback':{'task':tid,'kind':kind,'id':id}})
    source('task',tid,{k:brief[k] for k in ('task_id','scope_version','scope_hash','role','baseline','allowed_paths','inputs','outputs','exclusive_resources','constraints','acceptance')})
    if module:source('module',module['id']+'@'+module['version'],{k:module[k] for k in ('goal','scope','non_goals','path','acceptance','unknowns')})
    for m in materials[:32]:source(m['source_kind'],m['location'],m)
    for ref,c in brief['contracts'].items():source('contract',ref,c)
    for ref,a in brief['assets'].items():source('asset',ref,a)
    for ref,d in brief['planning_decisions'].items():source('decision',ref,d)
    for ref,t in brief['collaboration']['threads'].items():
        if t['status']!='resolved':source('thread',ref,{'title':t['title'],'kind':t['kind'],'status':t['status'],'latest':t['messages'][-1] if t['messages'] else None})
    for ref,f in brief['collaboration']['findings'].items():
        if f['status'] not in ('fixed','dismissed'):source('finding',ref,f)
    cursor=since or co['resume']['since']
    from .coordination import feed
    changes=feed(store,actor,{'cursor':[cursor],'limit':['100'],'task':[tid]})
    packet={'schema':1,'task':tid,'scope':brief['scope_hash'],'scope_version':brief['scope_version'],'sources':sources,'resume':co['resume'],'plans':co['plans'],'criteria':brief['collaboration']['current_plan'],'tests':brief['test_plan'],'rule':conv['bindings'].get(tid),'attempts':conv['attempts'],'sessions':conv['sessions'],'selection':conv['selections'].get(tid),'resources':brief['resource_directory'],'changes':changes,'materials_truncated':len(materials)>32,'instructions':['核对当前范围、批准规则/计划、未决发现和资源访问条件','摘要是有来源的读视图，不替代实际原件或正式变更','变化通知可能含项目公共边界更新；按readback重新读取，has_more时继续分页','原始聊天和日志留本地/NAS；会话引用不证明进程已经停止']}
    packet['material_readback']={'endpoint':'/api/projects/'+project+'/brief?task='+tid,'remaining_locations':[m['location'] for m in materials[32:]],'reason':'最多32条摘要，剩余入口按同一范围brief读取' if len(materials)>32 else ''}
    packet['project_id']=project;packet['sha256']=digest(packet);return packet
