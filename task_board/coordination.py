"""Project-scoped discovery, continuation and read-only observations.

The operations journal remains the single writer. Checkpoints and human gates
are attributed statements, not proof of an external process or natural person.
"""
from copy import deepcopy
import base64,json,re,time,uuid,statistics
from .store import BoardError,fields,text,integer,identifiers,digest,evidence
from .operations import manager
from .workflow import task,current,own,uid,input_anchor,reader

KEYS=('intakes','links','checkpoints','plans','plan_heads','plan_policy','batches','causes','improvements','wip','gates','observers','observations','resource_checks','consumers')
ACTIONS={'intake_open','intake_decide','intake_convert','source_link','checkpoint','execution_policy','execution_plan','execution_review','review_batch','root_cause','improvement','wip_policy','condition_gate','gate_retire','gate_confirm','observer_authorize','condition_observe','resource_observe','consumer_ack'}
ROOT_CAUSES={'requirements','interface','missing_input','implementation','test_gap','environment','planning','unknown'}
TABLES=('events','governance_events','operations_events','git_events')

def prepare(v):
    for k in KEYS:v.setdefault('co_'+k,{})
    return v

def commutes(action,p,actor,old,new):
    if action=='consumer_ack':
        consumer=p.get('consumer')
        return type(consumer) is str and old.get('co_consumers',{}).get(actor['id'],{}).get(consumer)==new.get('co_consumers',{}).get(actor['id'],{}).get(consumer)
    if action=='intake_open':return type(p.get('id')) is str and p['id'] not in new.get('co_intakes',{})
    if action in ('checkpoint','resource_observe','condition_observe'):
        if action=='checkpoint':return type(p.get('task')) is str and old.get('co_plan_heads',{}).get(p['task'])==new.get('co_plan_heads',{}).get(p['task'])
        key='co_observations' if action=='condition_observe' else 'co_resource_checks'
        return type(p.get('id')) is str and old.get(key,{}).get(p['id'])==new.get(key,{}).get(p['id']) and old.get('co_observers',{}).get(actor['id'])==new.get('co_observers',{}).get(actor['id'])
    return False

def checked(p,keys):fields(p,set(keys.split()),set(keys.split()))
def record(p,actor,now):return {**deepcopy(p),'actor':actor['id'],'at':now}
def bounded(value,label,maximum=8000):return text(value,label,maximum)
def boolean(value):
    if type(value) is not bool:raise BoardError('需布尔值')
def sequence(values,label,maximum=64):
    if type(values) is not list or len(values)>maximum:raise BoardError(label+'需有界数组')
def exact(mapping,key):
    if type(key) is not str or key not in mapping:raise BoardError('本项目对象不存在',404)
    return mapping[key]
def resource(g,rid,actor,r):
    from .resources import visible
    e=exact(g.get('resource_entries',{}),rid)
    if not visible(e,r,actor.get('global_admin',False)):raise BoardError('资源入口不存在',404)
    return e

def reference(v,g,ts,ref,actor,r,public=True):
    checked(ref,'kind id');kind=ref['kind'];key=ref['id'];bounded(kind,'来源类型',40);bounded(key,'来源ID',180)
    maps={'task':ts,'thread':v.get('wf_threads',{}),'finding':v.get('wf_findings',{}),'run':v['runs'],
          'intake':v['co_intakes'],'module':g.get('modules',{}),'asset':g.get('assets',{}),
          'checkpoint':v['co_checkpoints'],'batch':v['co_batches'],'case':v['cases']}
    if kind=='resource':
        e=resource(g,key,actor,r)
        if public and e['visibility']!='project':raise BoardError('项目公开来源不引用管理/实例私有入口',403)
        return e
    if kind not in maps:raise BoardError('来源类型无效')
    return exact(maps[kind],key)

def plan_context(v,t,g):
    w=t['spec'].get('work',{})
    return digest({'scope':t['scope_hash'],'version':t['scope_version'],'baseline':w.get('baseline'),
                   'criteria':v.get('wf_plan_heads',{}).get(t['spec']['id']),
                   'contracts':{ref:g.get('contracts',{}).get(ref) for ref in w.get('contracts',[])}})

def plan_required(v,t,g):
    from .assurance import effective,STRICT
    policy=v.get('co_plan_policy',{}).get(t['spec']['id'])
    e=effective(v,t,g)
    binding=v.get('cv_bindings',{}).get(t['spec']['id'])
    rule=v.get('cv_rules',{}).get(binding['ref']) if binding and current(binding,t) else None
    if rule and rule['plan_mode']=='se_review':return True
    # Adoption is explicit per task; historical strict deliveries stay readable.
    return bool(policy and e['level']!='light' and (policy['required'] or e['level']=='strict' and bool(set(e['flags']) & STRICT)))

def admission(v,t,g,ts):
    out=[];tid=t['spec']['id'];module=t['spec'].get('work',{}).get('planning',{}).get('module','').split('@')[0]
    if plan_required(v,t,g):
        p=v.get('co_plans',{}).get(v.get('co_plan_heads',{}).get(tid))
        if not p or p['context']!=plan_context(v,t,g) or not p.get('review') or p['review']['result']!='approve':out.append('实施计划需当前范围批准')
    policy=v.get('co_wip',{}).get(module)
    from .governance import ACTIVE
    if policy and policy['mode']=='enforce' and t['status'] not in ACTIVE:
        active=[x for x in ts.values() if x['spec']['id']!=tid and x['status'] in ACTIVE and x['spec'].get('work',{}).get('planning',{}).get('module','').split('@')[0]==module]
        if len(active)>=policy['limit']:out.append('模块在制任务达到上限：'+module)
    out+=gate_blockers(v,t,'claim','git:'+t['spec'].get('work',{}).get('baseline',''),time.time())
    return out

def gate_ok(v,gate,anchor,now):
    if gate['input_anchor']!=anchor:return False
    if gate['kind']=='timer':return now>=gate['not_before']
    if gate['kind']=='human':return bool(gate.get('confirmation'))
    obs=v.get('co_observations',{}).get(gate['id']);auth=v.get('co_observers',{}).get(obs.get('actor')) if obs else None
    return bool(obs and auth and auth['enabled'] and obs['authorization']==digest(auth) and gate['id'] in auth['targets'] and 'condition' in auth['kinds'] and obs['gate_hash']==digest({k:x for k,x in gate.items() if k!='confirmation'}) and obs['status']=='passed' and 0<=now-obs['at']<=gate['ttl'])

def gate_blockers(v,t,stage,anchor,now):
    return ['条件门未满足或观察已过期：'+e['id'] for e in v.get('co_gates',{}).values() if not e.get('retired') and e['task']==t['spec']['id'] and (not current(e,t) or stage in e['stages'] and not gate_ok(v,e,anchor,now))]

def enforce(db,t,stage,p,registry=None):
    if stage=='submit':return
    from .operations import load
    from .governance import load as gov,tasks
    from .workflow import submission_anchor
    v=load(db);g=gov(db);g['_cv_tasks']=tasks(db)
    if registry:g['consumption']=registry.consumption()
    reasons=[]
    if plan_required(v,t,g):
        plan=v.get('co_plans',{}).get(v.get('co_plan_heads',{}).get(t['spec']['id']))
        if not plan or plan['context']!=plan_context(v,t,g) or plan.get('review',{}).get('result')!='approve':reasons.append('实施计划已失效或未批准')
    anchor=('git:'+p['implementation_commit'] if p.get('implementation_commit') else 'sha256:'+p['artifact']['sha256'] if p.get('artifact') else '') if stage=='submit' else 'git:'+p['commit'] if stage in ('merge','native') else submission_anchor(t)
    reasons+=gate_blockers(v,t,stage,anchor,time.time())
    if stage=='accept':reasons+=gate_blockers(v,t,'submit',anchor,time.time())
    if reasons:raise BoardError('；'.join(reasons),409)

def heads(db):
    return {table:db.execute('SELECT coalesce(max(seq),0) FROM '+table).fetchone()[0] for table in TABLES}

def cursor_encode(value):return base64.urlsafe_b64encode(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).decode().rstrip('=')
def cursor_decode(value):
    if not value:return {k:0 for k in TABLES}
    try:
        if type(value) is not str or len(value)>500:raise ValueError()
        d=json.loads(base64.urlsafe_b64decode(value+'='*(-len(value)%4)))
        if set(d)!=set(TABLES) or any(type(x) is not int or x<0 for x in d.values()):raise ValueError()
        return d
    except Exception:raise BoardError('事件游标格式无效')

def mutate(v,db,actor,r,action,p,now,g,ts,store):
    prepare(v)
    for key in {'attempt_id','attempt_lease','selection_id','id','title','body','status','reason','duplicate','scope','task','session','input_anchor','completed','remaining','tests','obstacles','next_step','recheck','validation','risks','stop_conditions','plan','result','repo','base','target','previous','summary','finding','category','hypothesis','module','gate_hash','commit','entry_hash','observed_sha256','consumer','cursor','state'} & p.keys():
        if type(p[key]) is not str or len(p[key])>8000:raise BoardError(key+'需有界字符串')
    if action=='intake_open':
        checked(p,'id kind title body sources');uid(p['id']);sequence(p['sources'],'来源',16)
        if p['kind'] not in ('requirement','bug','research','debt','improvement'):raise BoardError('需求类型无效')
        bounded(p['title'],'标题',200);bounded(p['body'],'现象、目标和依据')
        if p['id'] in v['co_intakes']:raise BoardError('需求ID不可覆盖',409)
        for ref in p['sources']:reference(v,g,ts,ref,actor,r)
        v['co_intakes'][p['id']]={**record(p,actor,now),'status':'triage','version':1,'history':[],'tasks':[],'modules':[]};return {'intake':p['id']}
    if action in ('intake_decide','intake_convert'):
        manager(r);e=exact(v['co_intakes'],p.get('id'));integer(p.get('expected_version'),'需求版本')
        if e.get('product_model_version'):raise BoardError('此记录已采用产品模型，使用产品版本与核验流程',409)
        if p['expected_version']!=e['version']:raise BoardError('需求已有新处置',409)
        if action=='intake_decide':
            checked(p,'id expected_version status reason duplicate tasks modules')
            if p['status'] not in ('triage','research','approved','planned','deferred','rejected','duplicate','resolved'):raise BoardError('分诊状态无效')
            for key,mapping in [('tasks',ts),('modules',g.get('modules',{}))]:
                identifiers(p[key],key)
                for keyid in p[key]:exact(mapping,keyid)
            bounded(p['reason'],'处置依据')
            if p['status']=='duplicate':
                target=exact(v['co_intakes'],p['duplicate']);seen={p['id']}
                while target:
                    if target['id'] in seen:raise BoardError('重复关系成环',409)
                    seen.add(target['id']);target=v['co_intakes'].get(target.get('duplicate'))
            elif p['duplicate']:raise BoardError('非重复处置不填写duplicate')
            if p['status']=='planned' and not p['tasks']:raise BoardError('进入执行需明确已有任务',409)
            e.update({k:deepcopy(p[k]) for k in ('status','duplicate','tasks','modules')})
        else:
            checked(p,'id expected_version spec reason');bounded(p['reason'],'转任务依据')
            if e['status'] not in ('approved','research'):raise BoardError('先批准或决定调研，再转换任务',409)
            if type(p['spec']) is not dict:raise BoardError('spec需对象')
            tid=p['spec'].get('id')
            if tid in ts:raise BoardError('任务ID已存在',409)
            payload=store._validate(db,actor,tid,None,'create',{'spec':p['spec'],'reason':p['reason']})
            store._append(db,actor,tid,'create',payload);e.update(status='planned',tasks=[*e['tasks'],tid])
            v['co_links'][uuid.uuid4().hex]={'from':{'kind':'task','id':tid},'to':{'kind':'intake','id':e['id']},'relation':'derived_from','actor':actor['id'],'at':now}
        e['version']+=1;e['history'].append(record(p,actor,now));return {'intake':e['id'],'version':e['version']}
    if action=='source_link':
        checked(p,'id from to relation reason');uid(p['id']);bounded(p['reason'],'来源关系依据')
        for ref in (p['from'],p['to']):reference(v,g,ts,ref,actor,r)
        if p['from']==p['to'] or p['relation'] not in ('discovered_from','derived_from','related','supersedes'):raise BoardError('来源关系无效')
        if p['id'] in v['co_links']:raise BoardError('来源关系ID已存在',409)
        if r not in ('owner','se','reviewer'):
            source=reference(v,g,ts,p['from'],actor,r)
            if source.get('owner',source.get('actor',source.get('author')))!=actor['id']:raise BoardError('仅为本人任务或发现追加来源',403)
        # Provenance is never interpreted as a scheduling dependency.
        if p['relation'] in ('derived_from','supersedes'):
            adjacency={}
            for e in v['co_links'].values():
                if e['relation'] in ('derived_from','supersedes'):adjacency.setdefault(digest(e['from']),[]).append(digest(e['to']))
            pending=[digest(p['to'])];seen=set()
            while pending:
                key=pending.pop()
                if key==digest(p['from']):raise BoardError('来源关系成环',409)
                if key not in seen:seen.add(key);pending+=adjacency.get(key,[])
        v['co_links'][p['id']]=record(p,actor,now);return
    if action=='checkpoint':
        keys=set('task scope scope_version id input_anchor completed remaining tests obstacles resources next_step recheck session'.split())
        fields(p,keys|{'attempt_id','attempt_lease','selection_id'},keys)
        t=task(db,p);uid(p['id']);input_anchor(p['input_anchor'])
        from .finishing import participant,public_record
        if p.get('selection_id'):own(t,actor,r)
        else:participant(v,t,p,actor)
        from .convergence import attempt_enforce
        if p.get('selection_id'):
            anchor=p['input_anchor'];fixed={'implementation_commit':anchor[4:]} if anchor.startswith('git:') else {'artifact':{'sha256':anchor[7:]}}
            attempt_enforce(v,t,'submit',{**p,**fixed},actor,now)
        else:attempt_enforce(v,t,'progress',p,actor,now)
        if p['id'] in v['co_checkpoints']:raise BoardError('检查点不可覆盖',409)
        for key in ('completed','remaining','tests','obstacles','next_step','recheck','session'):bounded(p[key],key,4000)
        identifiers(p['resources'],'资源')
        if not set(p['resources'])<=set(t['spec'].get('work',{}).get('resources',[])):raise BoardError('检查点资源越出任务登记',409)
        if p.get('attempt_id') and not p.get('selection_id'):
            active=v['cv_attempts'][p['attempt_id']];workspace=v['cv_workspaces'][active['workspace']]
            if not set(p['resources'])<=set(workspace['resources']):raise BoardError('检查点资源越出本人尝试授权',409)
        v['co_checkpoints'][p['id']]={**record(public_record(p),actor,now),'cursor':cursor_encode(heads(db)),'task_revision':t['revision'],'plan':v['co_plan_heads'].get(p['task']),'evidence_class':'worker_statement'};return {'checkpoint':p['id']}
    if action=='execution_policy':
        manager(r);checked(p,'task scope scope_version required reason');task(db,p);boolean(p['required']);bounded(p['reason'],'实施评审选择依据');v['co_plan_policy'][p['task']]=record(p,actor,now);return
    if action=='execution_plan':
        checked(p,'task scope scope_version id steps paths validation risks stop_conditions');t=task(db,p)
        if t['owner'] and t['owner']!=actor['id']:manager(r)
        elif not t['owner']:manager(r)
        uid(p['id']);sequence(p['steps'],'实施步骤',32);identifiers(p['paths'],'修改路径')
        if not p['steps']:raise BoardError('需实施步骤')
        from .governance import overlaps
        for path in p['paths']:
            from .git_reader import safe_path
            safe_path(path.rstrip('/'))
            if not any(path==a or path.startswith(a.rstrip('/')+'/') for a in t['spec']['allowed_paths']):raise BoardError('实施路径越出任务范围',409)
        for step in p['steps']:bounded(step,'步骤',2000)
        for key in ('validation','risks','stop_conditions'):bounded(p[key],key,4000)
        if p['id'] in v['co_plans']:raise BoardError('实施计划版本不可覆盖',409)
        v['co_plans'][p['id']]={**record(p,actor,now),'context':plan_context(v,t,g),'review':None};v['co_plan_heads'][p['task']]=p['id'];return {'plan':p['id']}
    if action=='execution_review':
        manager(r);checked(p,'task scope scope_version plan result reason');t=task(db,p);e=exact(v['co_plans'],p['plan']);bounded(p['reason'],'评审依据')
        if e['task']!=p['task'] or e['context']!=plan_context(v,t,g) or v['co_plan_heads'].get(p['task'])!=p['plan']:raise BoardError('实施计划已过期',409)
        if p['result'] not in ('approve','reject'):raise BoardError('评审结果无效')
        from .workflow import independent
        independent(t,actor,v,g);e['review']=record(p,actor,now);return
    if action=='review_batch':
        manager(r);checked(p,'task scope scope_version id repo base target previous summary comments');t=task(db,p);uid(p['id']);bounded(p['summary'],'评审批次摘要');sequence(p['comments'],'行内评论',32)
        if p['id'] in v['co_batches']:raise BoardError('评审批次不可覆盖',409)
        rd,_=reader(store,db,p['repo']);rd.commit(p['base']);rd.commit(p['target']);files=rd.files(p['base'],p['target']);paths={x[k] for x in files for k in ('path','old_path') if x.get(k)}
        if p['previous']:
            previous=exact(v['co_batches'],p['previous'])
            if previous['task']!=p['task'] or previous['repo']!=p['repo'] or previous['target']!=p['base']:raise BoardError('增量评审需接续原目标提交',409)
        comments=[]
        for i,c in enumerate(p['comments']):
            checked(c,'path line side body blocking criterion');integer(c['line'],'评论行',1);bounded(c['body'],'发现');boolean(c['blocking'])
            bounded(c['path'],'差异路径',1000);bounded(c['side'],'差异侧',10)
            if c['path'] not in paths or c['side'] not in ('left','right'):raise BoardError('评论必须锚定本批实际差异文件',409)
            rd.allowed(c['path']);content=rd.blame(p['base'] if c['side']=='left' else p['target'],c['path'],c['line'])
            if not content['lines']:raise BoardError('评论行不存在',409)
            from .workflow import mutate as wf_mutate
            fid=p['id']+'-'+str(i+1)
            wf_mutate(v,db,actor,r,'review_open',{'task':p['task'],'scope':p['scope'],'scope_version':p['scope_version'],'id':fid,'criterion':c['criterion'],'description':c['body'],'acceptance':p['summary'],'blocking':c['blocking'],'anchor':{'commit':p['base'] if c['side']=='left' else p['target'],'path':c['path'],'line':c['line'],'resource':''},'previous':''},now,g,ts,store)
            comments.append({**deepcopy(c),'finding':fid})
        v['co_batches'][p['id']]={**record(p,actor,now),'comments':comments,'changed_files':files};return {'batch':p['id']}
    if action=='root_cause':
        manager(r);checked(p,'task scope scope_version finding category reason');task(db,p);e=exact(v.get('wf_findings',{}),p['finding'])
        if e['task']!=p['task'] or p['category'] not in ROOT_CAUSES:raise BoardError('根因关联无效')
        bounded(p['reason'],'根因核定依据');v['co_causes'].setdefault(p['finding'],[]).append(record(p,actor,now));return
    if action=='improvement':
        manager(r);checked(p,'id finding targets hypothesis result runs evidence');uid(p['id']);exact(v.get('wf_findings',{}),p['finding']);sequence(p['targets'],'改进关联',16)
        if not p['targets']:raise BoardError('需改进任务、用例或资产关联')
        for ref in p['targets']:
            reference(v,g,ts,ref,actor,r)
            if ref['kind'] not in ('task','case','asset'):raise BoardError('改进只关联任务、用例、资产')
        bounded(p['hypothesis'],'改进假设');bounded(p['result'],'实际效果或尚未验证');identifiers(p['runs'],'运行');evidence(p['evidence']) if p['evidence'] else None
        for rid in p['runs']:exact(v['runs'],rid)
        v['co_improvements'].setdefault(p['id'],[]).append(record(p,actor,now));return
    if action=='wip_policy':
        manager(r);checked(p,'module limit mode reason');bounded(p['reason'],'WIP依据');integer(p['limit'],'在制上限',1)
        if p['limit']>1000 or p['mode'] not in ('warn','enforce') or p['module'] not in g.get('module_heads',{}):raise BoardError('模块/WIP配置无效')
        v['co_wip'][p['module']]=record(p,actor,now);return
    if action=='condition_gate':
        manager(r);checked(p,'task scope scope_version id kind input_anchor stages repo checks app_id pr not_before ttl reason');t=task(db,p);uid(p['id']);input_anchor(p['input_anchor']);identifiers(p['stages'],'门禁阶段');identifiers(p['checks'],'检查名');integer(p['pr'],'PR序号');integer(p['app_id'],'GitHub App ID');integer(p['ttl'],'观察有效秒',1);bounded(p['reason'],'门禁依据')
        if p['id'] in v['co_gates']:raise BoardError('门禁不可覆盖；新范围新建版本',409)
        if p['kind'] not in ('github_checks','github_pr','human','timer') or not p['stages'] or not set(p['stages'])<={'claim','submit','accept','merge','native'} or p['ttl']>86400:raise BoardError('条件门类型/阶段/时效无效')
        if type(p['not_before']) not in (int,float) or not 0<=p['not_before']<=4102444800:raise BoardError('时间条件无效')
        if p['kind'].startswith('github'):
            if not p['input_anchor'].startswith('git:'):raise BoardError('GitHub门需精确提交')
            reader(store,db,p['repo'])
            if p['kind']=='github_checks' and (not p['checks'] or not p['app_id']) or p['kind']=='github_pr' and not p['pr']:raise BoardError('需固定检查名/App来源或PR')
        elif p['repo'] or p['checks'] or p['pr'] or p['app_id']:raise BoardError('本地条件不填写GitHub字段')
        v['co_gates'][p['id']]=record(p,actor,now);return {'gate':p['id']}
    if action=='gate_confirm':
        manager(r);checked(p,'id gate_hash reason');e=exact(v['co_gates'],p['id']);bounded(p['reason'],'授权确认依据')
        if e['kind']!='human' or p['gate_hash']!=digest({k:x for k,x in e.items() if k!='confirmation'}) or not current(e,ts[e['task']]):raise BoardError('人工条件已变化',409)
        e['confirmation']={**record(p,actor,now),'evidence_class':'authorized_actor_statement'};return
    if action=='gate_retire':
        manager(r);checked(p,'id gate_hash reason');e=exact(v['co_gates'],p['id']);bounded(p['reason'],'条件撤销/替代依据')
        if p['gate_hash']!=digest(e) or e.get('retired'):raise BoardError('条件已变化或已停用',409)
        e['retired']=record(p,actor,now);return
    if action=='observer_authorize':
        manager(r);checked(p,'actor kinds targets enabled reason');boolean(p['enabled']);identifiers(p['kinds'],'观察种类');identifiers(p['targets'],'批准对象');bounded(p['reason'],'观察授权依据')
        if g['members'].get(p['actor'],{}).get('role')!='runner' or not set(p['kinds'])<={'condition','resource'}:raise BoardError('需项目runner和明确观察种类',409)
        for target in p['targets']:
            if target in v['co_gates']:continue
            resource(g,target,actor,r)
        v['co_observers'][p['actor']]={**deepcopy(p),'authorized_by':actor['id'],'at':now};return
    if action in ('condition_observe','resource_observe'):
        if r!='runner':raise BoardError('仅明确授权的项目观察器回传',403)
        e=exact(v['co_observers'],actor['id']);kind='condition' if action=='condition_observe' else 'resource'
        if not e['enabled'] or kind not in e['kinds'] or p.get('id') not in e['targets']:raise BoardError('观察对象未授权',403)
        bounded(p.get('summary'),'实际观察',4000)
        if action=='condition_observe':
            checked(p,'id gate_hash status commit checks pr summary evidence');gate=exact(v['co_gates'],p['id']);evidence(p['evidence'])
            if not current(gate,ts[gate['task']]) or p['gate_hash']!=digest(gate) or gate['kind'] not in ('github_checks','github_pr') or p['commit']!=gate['input_anchor'][4:]:raise BoardError('条件对象、范围或提交已变化',409)
            if p['status'] not in ('passed','failed','pending','blocked') or type(p['checks']) is not dict:raise BoardError('条件观察无效')
            if set(p['checks'])!=set(gate['checks']) or any(s not in ('success','failure','pending') for s in p['checks'].values()):raise BoardError('检查集合不匹配',409)
            if p['pr']!=gate['pr']:raise BoardError('PR不匹配',409)
            if p['status']=='passed' and gate['kind']=='github_checks' and any(s!='success' for s in p['checks'].values()):raise BoardError('失败检查不能回传通过',409)
            v['co_observations'][p['id']]={**record(p,actor,now),'authorization':digest(e),'evidence_class':'approved_observer_attestation'}
        else:
            checked(p,'id entry_version entry_hash status observed_sha256 ttl summary evidence');entry=exact(g.get('resource_entries',{}),p['id']);evidence(p['evidence']);integer(p['ttl'],'核验有效秒',1)
            if p['entry_hash']!=digest(entry) or p['entry_version']!=entry['entry_version']:raise BoardError('入口版本已变化',409)
            if p['status'] not in ('verified','reachable','mismatch','missing','blocked') or p['ttl']>604800:raise BoardError('资源观察无效')
            if p['observed_sha256'] and not re.fullmatch('[0-9a-f]{64}',str(p['observed_sha256'])):raise BoardError('观察摘要无效')
            if p['status']=='verified' and (entry['integrity']['kind']=='none' or p['observed_sha256']!=entry['integrity']['sha256']):raise BoardError('真实摘要不匹配',409)
            v['co_resource_checks'].setdefault(p['id'],[]).append({**record(p,actor,now),'visibility':entry['visibility'],'authorization':digest(e),'evidence_class':'approved_local_probe'})
        return
    if action=='consumer_ack':
        checked(p,'consumer cursor state');uid(p['consumer']);d=cursor_decode(p['cursor']);end=heads(db)
        if any(d[k]>end[k] for k in TABLES) or p['state'] not in ('delivered','read','processed'):raise BoardError('消费游标越界或状态无效')
        records=v['co_consumers'].setdefault(actor['id'],{}).setdefault(p['consumer'],{})
        old=cursor_decode(records.get(p['state'],''))
        if any(d[k]<old[k] for k in TABLES):raise BoardError('消费游标不能后退',409)
        if p['state']!='delivered':
            prerequisite=cursor_decode(records.get('delivered',''))
            if any(d[k]>prerequisite[k] for k in TABLES):raise BoardError('先确认送达再读/处理',409)
        records[p['state']]=p['cursor'];return
    raise BoardError('未知协调动作',404)

def sanitize(v,g,actor,r):
    # Legacy checkpoints can contain proof fields; preserve journal bytes, hide proofs.
    for point in v.get('co_checkpoints',{}).values():point.pop('attempt_lease',None)
    from .resources import visible
    allowed={rid for rid,e in g.get('resource_entries',{}).items() if visible(e,r,actor.get('global_admin',False))}
    def can_ref(ref):return ref.get('kind')!='resource' or ref.get('id') in allowed
    v['co_intakes']={key:e for key,e in v.get('co_intakes',{}).items() if all(can_ref(ref) for ref in e['sources'])}
    v['product_changes']={key:e for key,e in v.get('product_changes',{}).items() if e['id'] in v['co_intakes']}
    v['co_links']={key:e for key,e in v.get('co_links',{}).items() if can_ref(e['from']) and can_ref(e['to']) and all(ref.get('kind')!='intake' or ref.get('id') in v['co_intakes'] for ref in (e['from'],e['to']))}
    v['co_resource_checks']={rid:[row for row in rows if visible({'visibility':row.get('visibility','operator')},r,actor.get('global_admin',False))] for rid,rows in v.get('co_resource_checks',{}).items() if rid in allowed}
    v['co_resource_checks']={rid:rows for rid,rows in v['co_resource_checks'].items() if rows}
    v['co_consumers']={actor['id']:v.get('co_consumers',{}).get(actor['id'],{})}
    if r not in ('owner','se','reviewer'):
        v['co_observers']={actor['id']:v.get('co_observers',{}).get(actor['id'])} if actor['id'] in v.get('co_observers',{}) else {}
        for e in v['co_observers'].values():e['targets']=[target for target in e['targets'] if target in allowed or target in v.get('co_gates',{})]
    return v

def feed(store,actor,query):
    from .operations import load
    from .governance import load as gov,role
    get=lambda k,d='':query.get(k,[d])[0];cursor=cursor_decode(get('cursor'))
    try:limit=int(get('limit','50'))
    except ValueError:raise BoardError('分页参数无效')
    if not 1<=limit<=100:raise BoardError('分页超限')
    with store.connection() as db:
        db.execute('BEGIN');end=heads(db);g=gov(db);r=role(db,actor)
        task_filter=get('task')
        from .finishing import related_tasks,event_tasks
        from .governance import tasks
        relevant=related_tasks(tasks(db),g,task_filter) if task_filter else None
        event_state=load(db) if task_filter else None
        if any(cursor[k]>end[k] for k in TABLES):raise BoardError('游标不属于当前项目历史',409)
        rows=[];scanned=0;safe_state=None
        for table in TABLES:
            for row in db.execute('SELECT * FROM '+table+' WHERE seq>? AND seq<=? ORDER BY seq LIMIT 200',(cursor[table],end[table])):
                if len(rows)>=limit or scanned>=200:break
                cursor[table]=row['seq'];scanned+=1
                payload=json.loads(row['payload']);action=payload.get('action',row['kind'] if table=='events' else '')
                p=payload.get('payload',{})
                if action=='consumer_ack' or action=='thread_read':continue
                if action in ('resource_observe','resource_register','resource_update','resource_retire'):
                    try:resource(g,p.get('id'),actor,r)
                    except BoardError:continue
                if action in ('intake_open','intake_decide','intake_convert','source_link'):
                    if safe_state is None:safe_state=sanitize(prepare(load(db)),g,actor,r)
                    if action=='source_link' and p.get('id') not in safe_state['co_links']:continue
                    if action!='source_link' and p.get('id') not in safe_state['co_intakes']:continue
                if action.startswith('draft_') or action=='template_instantiate':
                    from .convergence import prepare as cv_prepare,sanitize as cv_sanitize
                    cv_safe=cv_sanitize(cv_prepare(prepare(load(db))),g,actor,r)
                    ref=p.get('ref') or (p.get('id','')+'@'+p.get('version',''))
                    if ref not in cv_safe['cv_drafts']:continue
                if action in ('observer_authorize',) and r not in ('owner','se','reviewer') and p.get('actor')!=actor['id']:continue
                # Only safe metadata is projected; event state and private
                # payloads never leave the journal through this endpoint.
                tid=row['task_id'] if table=='events' else p.get('task','')
                scope={}
                if relevant is not None:
                    linked=event_tasks(event_state,action,p,tid)
                    if linked and not relevant&linked:continue
                    scope={'relevance':'task' if task_filter in linked else 'related_task' if linked else 'project_boundary'}
                rows.append({'id':table+':'+str(row['seq']),'chain':table,'seq':row['seq'],'hash':row['hash'],'action':action,'actor':row['actor'],'task':tid,'object':p.get('id',p.get('thread',p.get('finding',''))),'at':row['created_at'] if table=='events' else payload.get('at'),**scope})
            if len(rows)>=limit or scanned>=200:break
        return {'items':rows,'cursor':cursor_encode(cursor),'head':cursor_encode(end),'has_more':any(cursor[k]<end[k] for k in TABLES),'scanned':scanned,**({'task_filter':task_filter,'includes_related_tasks':True,'includes_project_boundaries':True} if task_filter else {})}

def analytics(db,v,ts,g,now):
    from .governance import ACTIVE
    metrics={};daily={};returns=0;submits=0;histories={}
    for row in db.execute('SELECT task_id,kind,created_at,payload FROM events ORDER BY seq'):
        e=json.loads(row['payload']);at=row['created_at'];action=row['kind']
        if isinstance(at,str):
            from datetime import datetime
            try:at=datetime.fromisoformat(at.replace('Z','+00:00')).timestamp()
            except ValueError:continue
        if not isinstance(at,(int,float)):continue
        h=histories.setdefault(row['task_id'],{});h.setdefault(action,[]).append(at)
        day=time.strftime('%Y-%m-%d',time.gmtime(at));d=daily.setdefault(day,{'submits':0,'accepted':0,'returns':0})
        if action=='submit':submits+=1;d['submits']+=1
        if action=='accept':d['accepted']+=1
        if action=='request_changes':returns+=1;d['returns']+=1
    intervals={k:[] for k in ('claim_to_submit','review_queue','accept_to_merge','merge_to_native')}
    for tid,h in histories.items():
        metrics[tid]={}
        for label,a,b in [('claim_to_submit','claim','submit'),('review_queue','submit','accept'),('accept_to_merge','accept','merge'),('merge_to_native','merge','native')]:
            # Pair each end with its latest prior start, preserving later rounds.
            values=[end-max(x for x in h.get(a,[]) if x<=end) for end in h.get(b,[]) if any(x<=end for x in h.get(a,[]))]
            metrics[tid][label]=values;intervals[label]+=values
    causes={k:sum(rows[-1]['category']==k for rows in v['co_causes'].values() if rows) for k in sorted(ROOT_CAUSES)}
    wip=[]
    for module,p in v['co_wip'].items():
        count=sum(t['status'] in ACTIVE and t['spec'].get('work',{}).get('planning',{}).get('module','').split('@')[0]==module for t in ts.values())
        wip.append({**p,'active':count,'over_limit':count>p['limit']})
    first_returns=sum(bool(h.get('request_changes') and h.get('submit') and h['request_changes'][0]<next((x for x in h.get('accept',[]) if x>=h['submit'][0]),float('inf'))) for h in histories.values())
    findings=v.get('wf_findings',{});reopened=sum(e.get('status')=='open' and bool(e.get('resolution')) for e in findings.values())
    automation={};coverage=[]
    for gate in v['co_gates'].values():automation[gate['id']]={'passed':not gate.get('retired') and current(gate,ts[gate['task']]) and gate_ok(v,gate,gate['input_anchor'],now),'gate_hash':digest(gate)}
    for plan in v.get('wf_plans',{}).values():
        if v.get('wf_plan_heads',{}).get(plan['task'])!=plan['id']:continue
        for item in plan['items']:
            claim=v.get('wf_claims',{}).get(plan['id']+':'+item['id'])
            runs=[v['runs'][rid] for rid in (claim or {}).get('runs',[]) if rid in v['runs']]
            coverage.append({'task':plan['task'],'criterion':item['id'],'current_scope':current(plan,ts[plan['task']]),'input_anchor':(claim or {}).get('input_anchor'),'runs':[run['id'] for run in runs],'cases':sorted({case for run in runs for case in run.get('cases',[])}),'findings':[e['id'] for e in findings.values() if e['task']==plan['task'] and e['criterion']==item['id']]})
    return {'unit':'elapsed_seconds','tasks':metrics,'daily':daily,'intervals':{k:{'samples':len(values),'p50':statistics.median(values) if values else None,'p80':sorted(values)[max(0,__import__('math').ceil(.8*len(values))-1)] if values else None} for k,values in intervals.items()},'submissions':submits,'send_backs':returns,'first_submission_return_rate':first_returns/sum(bool(h.get('submit')) for h in histories.values()) if submits else None,'current_reopened_findings':reopened,'root_causes':causes,'wip':wip,'conditions':automation,'coverage':coverage,'note':'任务历时与审核队列不是申报工时或DORA生产指标；缺失历史保持未知。资源队列未进入日历预测。'}

def snapshot(store,actor,task_id=None):
    from .operations import load
    from .governance import load as gov,tasks,role
    with store.connection() as db:
        db.execute('BEGIN');v=prepare(load(db));g=gov(db);ts=tasks(db);g['_cv_tasks']=ts;r=role(db,actor);now=time.time()
        if getattr(store,'registry',None):g['consumption']=store.registry.consumption()
        if task_id and task_id not in ts:raise BoardError('本项目任务不存在',404)
        data={k:deepcopy(v['co_'+k]) for k in KEYS}
        for point in data['checkpoints'].values():point.pop('attempt_lease',None)
        data['analytics']=analytics(db,v,ts,g,now);data['cursor']=cursor_encode(heads(db));data['revision']=v['revision'];data['schema']=1
        for gate in data['gates'].values():
            gate['gate_hash']=digest(gate);gate['satisfied']=not gate.get('retired') and current(gate,ts[gate['task']]) and gate_ok(v,v['co_gates'][gate['id']],gate['input_anchor'],now)
        for rid,records in data['resource_checks'].items():
            entry=g['resource_entries'][rid]
            for obs in records:
                auth=v['co_observers'].get(obs['actor'])
                obs['current']=obs['entry_hash']==digest(entry) and bool(auth and auth['enabled'] and rid in auth['targets'] and obs['authorization']==digest(auth)) and 0<=now-obs['at']<=obs['ttl']
        for p in data['plans'].values():p['context_current']=p['context']==plan_context(v,ts[p['task']],g)
        safe=sanitize({k:deepcopy(v.get(k,{})) for k in ('co_intakes','co_links','co_resource_checks','co_observers','co_consumers','co_gates')},g,actor,r)
        for key in ('resource_checks','consumers','observers','intakes','links'):
            allowed=safe['co_'+key]
            data[key]={k:[row for row in val if any(row['at']==safe_row['at'] for safe_row in allowed[k])] for k,val in data[key].items() if k in allowed} if key=='resource_checks' else {k:val for k,val in data[key].items() if k in allowed}
            if key in ('consumers','observers'):data[key]=deepcopy(allowed)
        if task_id:
            for k in ('plans','checkpoints','batches','gates'):data[k]={key:e for key,e in data[k].items() if e['task']==task_id}
            data['intakes']={key:e for key,e in data['intakes'].items() if task_id in e['tasks'] or {'kind':'task','id':task_id} in e['sources']}
            t=ts[task_id];points=list(data['checkpoints'].values())
            for point in points:point.pop('attempt_lease',None)
            by_attempt={}
            for point in points:
                aid=point.get('attempt_id')
                if aid and (aid not in by_attempt or point['at']>by_attempt[aid]['at']):by_attempt[aid]=point
            selection=v.get('cv_selections',{}).get(task_id,{})
            mine=[p for p in points if p['actor']==actor['id']]
            if t['owner']==actor['id'] or r in ('owner','se','reviewer') or not mine:mine=[p for p in points if p['actor']==t['owner'] or selection.get('attempt') and p.get('attempt_id')==selection['attempt']]
            latest=max(mine,key=lambda e:e['at'],default=None)
            data['resume']={'checkpoint':latest,'checkpoint_current':bool(latest and current(latest,t)),'since':latest['cursor'] if latest else cursor_encode({k:0 for k in TABLES}),'recheck':['核对当前任务范围、实施计划、接口及资产版本','核对未决线程、条件门及评审发现','核对真实进程和工作区；离线不代表资源已释放'],'plan_required':plan_required(v,t,g)}
            submission=(t.get('latest_submission') or {}).get('implementation_commit')
            data['resume']['attempt_checkpoints']=by_attempt
            for b in data['batches'].values():b['anchor_current']=b['target']==submission if submission else None
        return data
