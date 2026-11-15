"""Project-local governance, serialized with task writes in the same SQLite DB.

The document is a replayable projection of append-only snapshots. Legacy task
events remain byte-for-byte unchanged. This is API isolation, not OS sandboxing.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import PurePosixPath
import re
import time

from .store import BoardError, canonical, digest, fields, text, integer, identifiers, evidence

CATEGORIES = {'research','collection','generation','infrastructure','frontend','backend','library','documentation','test','integration','release'}
ROLES = {'owner','se','worker','researcher','collector','generator','developer','documenter','tester','agent','viewer','runner','tracker','restorer'}
MANAGERS = {'owner','se','reviewer'}
DONE = {'accepted','merged','native_accepted','baseline_merged'}
ACTIVE = {'active','submitted','changes_requested','partial_accepted','partial_merged','partial_native'}

def can_work(actual,required):
    """A recruited worker covers execution specialties, never management/tools."""
    return actual in MANAGERS or actual==required or required=='agent' or (actual=='worker' and required in {'researcher','collector','generator','developer','documenter','tester','worker'})

def work_spec(value):
    fields(value, {'category','role','inputs_known','inputs','outputs','contracts','assets','asset_locks','resources','couplings','baseline','acceptance','planning'},
           {'category','role','inputs_known','inputs','outputs','contracts','assets','resources','couplings','baseline','acceptance'})
    if value['category'] not in CATEGORIES or value['role'] not in ROLES:
        raise BoardError('未知任务分类或执行角色')
    if value['role'] in ('runner','viewer','tracker','restorer'):raise BoardError('只读者、同步器和执行器不领取开发任务')
    if type(value['inputs_known']) is not bool:
        raise BoardError('inputs_known需布尔值；未知输入不能自动领取')
    for k in ('inputs','outputs','contracts','assets','resources','couplings'):
        identifiers(value[k], k)
    from .assurance import NONCODE
    if not re.fullmatch('[0-9a-f]{40}', str(value['baseline'])) and not (value['category'] in NONCODE and re.fullmatch('artifact:sha256:[0-9a-f]{64}',str(value['baseline']))):
        raise BoardError('基线需完整Git提交')
    text(value['acceptance'], '验收条件', 8000)
    if 'planning' in value:
        p=value['planning'];fields(p,{'module','purpose','question','no_interface_reason'},{'module','purpose','question','no_interface_reason'})
        text(p['module'],'固定模块版本',220)
        if p['purpose'] not in ('planning','execution'):raise BoardError('任务用途需planning/execution')
        for k in ('question','no_interface_reason'):
            if not isinstance(p[k],str) or len(p[k])>8000:raise BoardError(k+'需有界字符串')
    locks=value.get('asset_locks',{})
    if type(locks) is not dict or not set(locks)<=set(value['assets']):raise BoardError('资产锁必须对应本任务引用')
    for lock in locks.values():
        fields(lock,{'release','sha256','shared'},{'release','sha256','shared'})
        text(lock['release'],'固定资产版本',240)
        if type(lock['shared']) is not bool or not re.fullmatch('[0-9a-f]{64}',str(lock['sha256'])):raise BoardError('资产锁需固定版本、SHA和共享类型')
    return deepcopy(value)

def pin_assets(db,spec,registry=None,previous=None):
    """Freeze per-task bytes, not merely the project's movable alias.

    Ordinary scope changes retain existing locks. A reviewed scope may select
    the current approved consumption explicitly; a provider update cannot float
    either a project alias or an already dispatched task.
    """
    w=spec.get('work')
    if not w:return
    gov=load(db);consumption=registry.consumption() if registry else {};old=(previous or {}).get('work',{}).get('asset_locks',{});requested=w.get('asset_locks',{});pinned={}
    for ref in w['assets']:
        item=gov['assets'].get(ref)
        current=({'release':ref,'sha256':item['sha256'],'shared':False} if item else
                 {'release':consumption[ref]['release'],'sha256':consumption[ref]['sha256'],'shared':True} if ref in consumption else None)
        chosen=requested.get(ref) or old.get(ref) or current
        if chosen is not None:
            if chosen!=current and chosen!=old.get(ref):raise BoardError('资产锁只能选择当前已批准消费或保留原任务固定版本',409)
            pinned[ref]=deepcopy(chosen)
    w['asset_locks']=pinned

def empty():
    return dict(knowledge={}, members={}, milestones={}, decisions=[], packages={}, contracts={}, changes={}, assets={}, consumption={}, handoff=None,resource_entries={})


def handoff_scope(db,value):
    scope={'tasks':tasks(db),'contracts':value['contracts']}
    resources={k:e for k,e in value.get('resource_entries',{}).items() if e['visibility']!='operator'}
    if resources:scope['resource_entries']=resources
    return digest(scope)


def knowledge_spec(p):
    """Validate before allocating a project directory as well as on updates."""
    fields(p,{'background','goals','non_goals','constraints','materials','entries','history_notes','resource_notes'}, {'background','goals','non_goals','constraints','materials','entries'})
    for key in ('background','goals','non_goals','constraints'):text(p[key],key,12000)
    for key in ('history_notes','resource_notes'):
        if key in p and (not isinstance(p[key],str) or len(p[key])>12000):raise BoardError(key+'需有界字符串')
    result=deepcopy(p)
    for key in ('materials','entries'):
        if type(p[key]) is not list or len(p[key])>128:raise BoardError('材料/入口需有界列表')
        for item in result[key]:
            fields(item,{'title','location','version','sha256'}, {'title','location','version','sha256'} if key=='materials' else {'title','location'})
            if key=='entries':
                item.setdefault('version','unversioned');item.setdefault('sha256','')
            for key2 in ('title','location','version'):text(item[key2],key2,1000)
            if not (key=='entries' and item['sha256']=='') and not re.fullmatch('[0-9a-f]{64}',str(item['sha256'])):raise BoardError('固定材料需完整SHA256；动态入口可不填摘要')
    return result

def setup(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS governance_events(seq INTEGER PRIMARY KEY,actor TEXT NOT NULL,
        request_id TEXT NOT NULL,request_hash TEXT NOT NULL,payload TEXT NOT NULL,
        prev_hash TEXT NOT NULL,hash TEXT NOT NULL, UNIQUE(actor,request_id));
      CREATE TRIGGER IF NOT EXISTS governance_no_update BEFORE UPDATE ON governance_events
        BEGIN SELECT RAISE(ABORT,'append only'); END;
      CREATE TRIGGER IF NOT EXISTS governance_no_delete BEFORE DELETE ON governance_events
        BEGIN SELECT RAISE(ABORT,'append only'); END;
    ''')

def load(db):
    row = db.execute('SELECT seq,payload,hash FROM governance_events ORDER BY seq DESC LIMIT 1').fetchone()
    return ({'revision': row['seq'], 'head': row['hash'], **json.loads(row['payload'])['state']}
            if row else {'revision':0,'head':'0'*64,**empty()})

def role(db, actor):
    # A handoff explicitly overrides old management privileges, even for a
    # credential whose original low-level authentication role was reviewer.
    return load(db)['members'].get(actor['id'], {}).get('role', actor['role'])

def effective(db, actor):
    r = role(db,actor)
    return {**actor, 'project_role':r, 'role':'reviewer' if r in MANAGERS else 'agent'}

def tasks(db):
    return {r['id']: json.loads(r['state']) for r in db.execute('SELECT id,state FROM tasks')}

def overlaps(a,b):
    # Windows checkout paths are case-insensitive. Treat file/directory prefixes
    # equally; Foo/ and foo/x must never be advertised as independent writers.
    a,b = a.rstrip('/').casefold(),b.rstrip('/').casefold()
    return a==b or a.startswith(b+'/') or b.startswith(a+'/') or not a or not b

def impact(all_tasks, contract, governance=None):
    modules=(governance or {}).get('modules',{})
    module_refs={r for r,m in modules.items() if contract in m['interfaces']}
    while True:
        more={r for r,m in modules.items() if set(m['depends_on']) & module_refs}
        if more <= module_refs:break
        module_refs |= more
    direct = {k for k,t in all_tasks.items() if contract in t['spec'].get('work',{}).get('contracts',[])}
    direct |= {k for k,t in all_tasks.items() if t['spec'].get('work',{}).get('planning',{}).get('module') in module_refs}
    affected=set(direct)
    while True:
        produced={ref for k in affected for ref in all_tasks[k]['spec'].get('work',{}).get('outputs',[])}
        coupled={ref for k in affected for ref in all_tasks[k]['spec'].get('work',{}).get('couplings',[])}
        paths=[p for k in affected for p in all_tasks[k]['spec']['allowed_paths']]
        more={k for k,t in all_tasks.items() if set(t['spec']['depends_on']) & affected
              or set(t['spec'].get('work',{}).get('inputs',[])) & produced
              or set(t['spec'].get('work',{}).get('couplings',[])) & coupled
              or any(overlaps(a,b) for a in paths for b in t['spec']['allowed_paths'])}
        if more <= affected:break
        affected |= more
    return {'direct':sorted(direct),'transitive':sorted(affected-direct),
            'owners':sorted({all_tasks[k]['owner'] for k in affected if all_tasks[k]['owner']} | {modules[r]['owner'] for r in module_refs}),
            **({'module_scopes':{r:digest(modules[r]) for r in sorted(module_refs)}} if module_refs else {}),
            'scopes':{k:all_tasks[k]['scope_hash'] for k in sorted(affected)}}

def blockers(db, task, actor=None, registry=None, context=None, dependency_cache=None):
    # The authorized snapshot already holds these rows in one read transaction.
    # Reuse it for every queue item rather than decoding the whole project N
    # times. Admission calls still read fresh rows under the write transaction.
    spec=task['spec'];work=spec.get('work');out=[]
    all_tasks,gov=context[:2] if context is not None else (tasks(db),load(db))
    from .operations import load as operations_load
    from .assurance import effective
    ops=context[2] if context is not None and len(context)>2 else operations_load(db)
    gov={**gov,'_cv_tasks':all_tasks}
    if registry:gov['consumption']=registry.consumption()
    level=effective(ops,task,gov)
    from .planning import task_blockers
    planning_context={**gov,'planning_policy':{'mode':'enforced'}} if level['enabled'] and level['level']!='light' else gov
    planning_reasons=task_blockers(planning_context,all_tasks,spec) if not (level['enabled'] and level['assessed'] and level['level']=='light') else []
    if level['enabled']:
        if not level['assessed']:planning_reasons.append('当前任务范围尚未由SE评估风险')
        if level['level']=='light':
            from .planning import charter_blockers
            planning_reasons.extend(charter_blockers(gov))
    if not work:return ['legacy/unknown：需SE核定原子任务输入与耦合']+planning_reasons
    from .workflow import current as workflow_current
    for rollback in ops.get('wf_rollbacks',{}).values():
        if rollback['status']!='applied':continue
        for tid in [spec['id'],*spec['depends_on']]:
            candidate=all_tasks.get(tid)
            if candidate and tid in rollback['affected_tasks'] and workflow_current(rollback['task_scopes'][tid],candidate):out.append('成果已回退，需核定新范围：'+tid)
    out.extend(planning_reasons)
    if not work['inputs_known']:out.append('输入未知')
    if not spec['allowed_paths']:out.append('写范围未知')
    if actor and not can_work(role(db,actor),work['role']):
        out.append('执行角色不匹配')
    from .dependencies import resolve as dependency_resolve
    out.extend(dependency_resolve(db,task,registry,(all_tasks,gov,ops),context[3] if context is not None and len(context)>3 else dependency_cache)[0])
    for ref in work['contracts']:
        contract=gov['contracts'].get(ref)
        if not contract or contract['status']!='frozen':out.append('接口未冻结：'+ref)
    for ref in work['assets']:
        lock=work.get('asset_locks',{}).get(ref)
        if not lock:
            out.append('资产未固定：'+ref);continue
        if lock['shared'] and registry:
            try:
                release=registry.get(lock['release'],registry.project)
                if release['sha256']!=lock['sha256']:out.append('资产固定哈希不一致：'+ref)
            except BoardError:out.append('共享资产已撤回或未授权：'+ref)
        elif not lock['shared']:
            item=gov['assets'].get(lock['release'])
            if not item or item['sha256']!=lock['sha256']:out.append('私有资产未固定：'+ref)
        else:out.append('共享资产注册表不可用：'+ref)
    for other in all_tasks.values():
        if other['spec']['id']==spec['id'] or other['status'] not in ACTIVE:continue
        ow=other['spec'].get('work',{})
        if any(overlaps(a,b) for a in spec['allowed_paths'] for b in other['spec']['allowed_paths']):out.append('写路径冲突：'+other['spec']['id'])
        if set(work['resources']) & set(ow.get('resources',[])):out.append('排他资源冲突：'+other['spec']['id'])
        if set(work['couplings']) & set(ow.get('couplings',[])):out.append('共享修改需串行：'+other['spec']['id'])
    from .coordination import admission
    out.extend(admission(ops,task,gov,all_tasks))
    for attempt in ops.get('cv_attempts',{}).values():
        if attempt['task']!=spec['id'] and attempt['status'] in ('running','needs_recovery'):
            ws=ops.get('cv_workspaces',{}).get(attempt['workspace'],{})
            if any(overlaps(a,b) for a in spec['allowed_paths'] for b in ws.get('paths',[])) or set(work['resources'])&set(ws.get('resources',[])):out.append('旧尝试的工作区/资源尚未核对释放：'+attempt['task'])
        if attempt['task']==spec['id'] and attempt['status'] in ('running','needs_recovery') and (attempt['scope']!=task['scope_hash'] or attempt['scope_version']!=task['scope_version']):out.append('旧范围尝试仍需SE核对资源：'+attempt['id'])
    return sorted(set(out))

class Governance:
    def __init__(self, store):self.store=store

    def snapshot(self, query='', actor=None, operator=False):
        with self.store.connection() as db:
            db.execute('BEGIN')
            value=load(db);all_tasks=tasks(db)
            from .operations import load as operations_load
            ops=operations_load(db)
            value.pop('removed_assets',None)
            from .planning import snapshot as planning_snapshot
            planning_snapshot(value,all_tasks)
            for c in value['changes'].values():c['impact_hash']=digest(c['impact'])
            if getattr(self.store,'registry',None):value['consumption']=self.store.registry.consumption()
            queue=[];dependency_cache={}
            for t in all_tasks.values():
                if t['status']=='planned':queue.append({'id':t['spec']['id'],'blockers':blockers(db,t,registry=getattr(self.store,'registry',None),context=(all_tasks,value,ops,dependency_cache))})
            graph=[]
            for tid,t in all_tasks.items():
                from .dependencies import resolve as dependency_resolve,requirement,anchors as dependency_anchors
                dep_reasons,dep_facts=dependency_resolve(db,t,getattr(self.store,'registry',None),(all_tasks,value,ops),dependency_cache) if t['spec'].get('work') and t['status'] not in DONE else ([],{})
                locked=dependency_anchors(db,tid)
                if locked is not None:
                    for d in t['spec']['depends_on']:
                        if d in dep_facts and locked.get(d)!=dep_facts[d]:
                            dep_reasons.append('依赖 '+d+'：领取后的消费锚点已改变')
                            del dep_facts[d]
                for d in t['spec']['depends_on']:
                    try:req=requirement(t,all_tasks[d])
                    except (BoardError,KeyError):req={'kind':'unknown','stage':'unknown'}
                    graph.append({'from':d,'to':tid,'type':'hard','result_kind':req['kind'],'required_stage':req['stage'],'ready':d in dep_facts if t['status'] not in DONE else None,'blockers':[x for x in dep_reasons if ' '+d+'：' in x]})
                graph += [{'from':p,'to':tid,'type':'containment'} for p in t['spec'].get('parents',[]) if p in all_tasks]
                w=t['spec'].get('work',{})
                for typ,key in [('product','inputs'),('coupling','couplings'),('contract','contracts'),('asset','assets'),('exclusive','resources')]:
                    graph += [{'from':ref,'to':tid,'type':typ} for ref in w.get(key,[])]
                graph += [{'from':tid,'to':ref,'type':'produces'} for ref in w.get('outputs',[])]
            value.update(graph=graph,queue=queue,nodes=[{'id':k,'title':v['spec']['title'],'kind':v['spec']['kind'],'category':v['spec'].get('work',{}).get('category','unknown'),'status':v['status'],'planning':v['spec'].get('work',{}).get('planning')} for k,v in all_tasks.items()])
            from .finishing import conditions
            condition_nodes,condition_edges=conditions(ops,all_tasks)
            value['condition_nodes']=condition_nodes;value['graph']+=condition_edges;value['nodes']+=condition_nodes
            from .resources import filtered,audience
            resource_role,resource_operator=audience(actor,value,operator)
            value['resource_entries']=filtered(value,resource_role,resource_operator)
            if query:
                # Search only this already-authorized project; no global index.
                value={'revision':value['revision'],'matches':[{'kind':k,'id':str(i),'value':row} for k,rows in value.items() if isinstance(rows,dict) for i,row in rows.items() if query.casefold() in canonical(row).casefold()]}
            return value

    def apply(self, actor, request):
        fields(request, {'request_id','expected_revision','action','payload'}, {'request_id','expected_revision','action','payload'})
        rid=text(request['request_id'],'请求ID',100);integer(request['expected_revision'],'治理版本')
        action=text(request['action'],'治理动作',80);payload=request['payload']
        if type(payload) is not dict:raise BoardError('payload需对象')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT * FROM governance_events WHERE actor=? AND request_id=?',(actor['id'],rid)).fetchone()
            if old:
                if old['request_hash']!=digest(request):raise BoardError('请求ID内容不一致',409)
                return {'revision':old['seq'],'hash':old['hash'],'replayed':True}
            value=load(db);revision=value.pop('revision');previous=value.pop('head')
            if revision!=request['expected_revision']:raise BoardError('治理资料已变化；重读后决定',409)
            r=value['members'].get(actor['id'],{}).get('role',actor['role'])
            operator_resource=actor.get('global_admin') and action in ('resource_register','resource_update','resource_retire')
            if action not in ('handoff_accept','contract_confirm') and r not in MANAGERS and not operator_resource:raise BoardError('需本项目owner/SE',403)
            self._mutate(db,value,actor,r,action,payload)
            event={'action':action,'payload':payload,'state':value,'at':time.time()}
            hashed=digest({'seq':revision+1,'actor':actor['id'],'request_id':rid,'event':event,'previous':previous})
            db.execute('INSERT INTO governance_events VALUES(?,?,?,?,?,?,?)',(revision+1,actor['id'],rid,digest(request),canonical(event),previous,hashed));db.commit()
            return {'revision':revision+1,'hash':hashed}

    def _mutate(self,db,v,actor,r,action,p):
        if action in ('resource_register','resource_update','resource_retire'):
            from .resources import mutate
            mutate(db,v,actor,r,action,p,getattr(self.store,'registry',None))
        elif action in ('planning_enable','planning_decision','module_plan','module_review','milestone_plan','milestone_review'):
            from .planning import mutate
            mutate(v,tasks(db),actor,action,p)
        elif action=='worker_access':
            fields(p,{'enabled','reason'},{'enabled','reason'})
            if type(p['enabled']) is not bool:raise BoardError('enabled需布尔值')
            text(p['reason'],'招募决定依据',2000)
            v['worker_access']={**deepcopy(p),'actor':actor['id'],'at':time.time()}
        elif action=='worker_join':
            fields(p,{'actor','policy_head'},{'actor','policy_head'})
            if not v.get('worker_access',{}).get('enabled') or p['actor']!=actor['id'] or not re.fullmatch(r'worker-[a-z0-9-]{2,40}',p['actor']):raise BoardError('未授权的Worker登记',403)
            if p['actor'] in v['members']:raise BoardError('不能覆盖已有职责',409)
            v['members'][p['actor']]={'role':'worker','scope':'本项目公开执行任务池；按任务范围、依赖、冲突与验收门禁执行','actor_kind':'agent'}
        elif action=='knowledge':
            v['knowledge']=knowledge_spec(p)
        elif action=='member':
            fields(p,{'actor','role','scope','actor_kind'}, {'actor','role','scope'})
            if p.get('actor_kind','unknown') not in ('human','agent','unknown'):raise BoardError('执行者类型需human/agent/unknown')
            if p['role'] not in ROLES or p['actor']=='root':raise BoardError('角色无效或保留身份')
            if p['role']=='owner' and any(k!=p['actor'] and m['role']=='owner' for k,m in v['members'].items()):raise BoardError('已有owner；必须接受交接后移交',409)
            if p['role'] in ('owner','se') and r not in ('owner','reviewer'):raise BoardError('仅owner可授予管理职责',403)
            if not db.execute('SELECT 1 FROM actors WHERE id=?',(p['actor'],)).fetchone():raise BoardError('先签发本项目身份',409)
            current=v['members'].get(p['actor'],{})
            if current.get('role') in ('owner','se') and r not in ('owner','reviewer'):
                raise BoardError('继承SE不能自行更改其他管理职责',403)
            if current.get('role')=='owner' and p['role']!='owner':raise BoardError('owner降权需正式交接',409)
            v['members'][p['actor']]={'role':p['role'],'scope':text(p['scope'],'职责',8000),'actor_kind':p.get('actor_kind',current.get('actor_kind','unknown'))}
        elif action=='decision':
            fields(p,{'summary','reason','evidence'}, {'summary','reason','evidence'})
            text(p['summary'],'决策');text(p['reason'],'依据');evidence(p['evidence'])
            v['decisions'].append({**p,'actor':actor['id'],'at':time.time()})
        elif action=='milestone':
            if v.get('planning_policy',{}).get('mode')=='enforced':raise BoardError('规划门禁项目使用milestone_plan与milestone_review',409)
            fields(p,{'id','goal','acceptance','status','evidence'}, {'id','goal','acceptance','status','evidence'})
            text(p['id'],'里程碑ID',80);text(p['goal'],'目标');text(p['acceptance'],'验收')
            if p['status'] not in ('planned','active','passed','blocked'):raise BoardError('里程碑状态无效')
            if p['status']=='passed':evidence(p['evidence'])
            elif p['evidence']!=[]:evidence(p['evidence'])
            v['milestones'][p['id']]=deepcopy(p)
        elif action=='package':
            fields(p,{'id','tasks','source','unknown'}, {'id','tasks','source','unknown'})
            text(p['id'],'任务包ID');identifiers(p['tasks'],'原子任务');text(p['source'],'历史来源');text(p['unknown'],'未知边界')
            if not set(p['tasks'])<=set(tasks(db)):raise BoardError('包包含不存在的本项目任务',409)
            v['packages'][p['id']]=deepcopy(p)
        elif action=='handoff_propose':
            fields(p,{'to','risks','materials','reason'}, {'to','risks','materials','reason'})
            if r not in ('owner','reviewer'):raise BoardError('仅owner移交',403)
            if v['members'].get(p['to'],{}).get('role')!='se':raise BoardError('继承者必须是本项目SE',409)
            text(p['risks'],'未决风险');text(p['reason'],'交接原因');identifiers(p['materials'],'必读版本')
            v['handoff']={**p,'from':actor['id'],'accepted':False,'scope':handoff_scope(db,v), 'active':[k for k,t in tasks(db).items() if t['status'] in ACTIVE]}
        elif action=='handoff_accept':
            fields(p,{'scope','summary'}, {'scope','summary'});h=v['handoff']
            if not h or h['accepted'] or h['to']!=actor['id'] or h['scope']!=p['scope']:raise BoardError('交接对象或版本不一致',409)
            if h['scope']!=handoff_scope(db,v):raise BoardError('活跃范围、契约或资源入口已变化；重新交接',409)
            text(p['summary'],'接受说明');v['members'][h['from']]={'role':'viewer','scope':'已移交，管理权限撤销'}
            v['members'][h['to']]['role']='owner';h.update(accepted=True,summary=p['summary'])
        elif action=='contract_freeze':
            self._contract(v,p)
        elif action=='contract_propose':
            fields(p,{'id','contract','replacement','migration','tests'}, {'id','contract','replacement','migration','tests'})
            text(p['id'],'提案ID');text(p['migration'],'迁移计划',8000);text(p['tests'],'测试清单',8000)
            if p['id'] in v['changes'] or p['contract'] not in v['contracts'] or p['replacement'] not in v['contracts']:raise BoardError('需存在的新旧冻结版本与唯一提案',409)
            report=impact(tasks(db),p['contract'],v);owner=v['contracts'][p['contract']]['owner']
            se=sorted(k for k,m in v['members'].items() if m['role'] in ('owner','se')) or ['root']
            v['changes'][p['id']]={**p,'impact':report,'required':sorted(set([owner]+se+report['owners'])),'confirmations':[],'executed':False}
        elif action=='contract_confirm':
            fields(p,{'id','impact_hash','summary'}, {'id','impact_hash','summary'});c=v['changes'].get(p['id'])
            if not c or actor['id'] not in c['required']:raise BoardError('非此变更确认人',403)
            if p['impact_hash']!=digest(c['impact']) or impact(tasks(db),c['contract'],v)!=c['impact']:raise BoardError('影响范围变化；重新提案',409)
            text(p['summary'],'确认依据')
            c['confirmations']=sorted(set(c['confirmations']+[actor['id']]))
        elif action=='contract_execute':
            fields(p,{'id'}, {'id'});c=v['changes'].get(p['id'])
            if not c or not set(c['required'])<=set(c['confirmations']):raise BoardError('变更缺少影响确认',409)
            if impact(tasks(db),c['contract'],v)!=c['impact']:raise BoardError('影响范围变化；不能切换',409)
            v['contracts'][c['contract']]['status']='retired';c['executed']=True
        elif action=='asset_remove':
            fields(p,{'refs','reason'},{'refs','reason'});identifiers(p['refs'],'资产版本');text(p['reason'],'清理依据')
            v.setdefault('removed_assets',[])
            for ref in p['refs']:
                if ref not in v['assets']:raise BoardError('私有资产版本不存在',404)
                del v['assets'][ref];v['removed_assets'].append(ref)
        elif action=='asset':
            fields(p,{'id','version','kind','source','license','sensitivity','sha256','location','owner','shareable','evidence'}, {'id','version','kind','source','license','sensitivity','sha256','location','owner','shareable','evidence'})
            for key in ('id','version','kind','source','license','sensitivity','location','owner'):text(p[key],key,2000)
            if not re.fullmatch('[0-9a-f]{64}',str(p['sha256'])) or type(p['shareable']) is not bool:raise BoardError('资产需SHA与显式共享资格')
            evidence(p['evidence']);ref=p['id']+'@'+p['version']
            if ref in v['assets'] or ref in v.get('removed_assets',[]):raise BoardError('资产版本不可覆盖或重用',409)
            v['assets'][ref]={**p,'status':'private'}
        else:raise BoardError('未知治理动作',404)

    @staticmethod
    def _contract(v,p):
        keys={'id','version','owner','signature','units','errors','transaction','idempotency','source','producers','consumers','compatibility','evidence'}
        fields(p,keys,keys)
        for k in keys-{'producers','consumers','evidence'}:text(p[k],k,8000)
        identifiers(p['producers'],'生产者');identifiers(p['consumers'],'消费者');evidence(p['evidence'])
        if p['owner']!='root' and v['members'].get(p['owner'],{}).get('role') not in ('owner','se'):raise BoardError('接口owner需本项目负责人/SE',409)
        ref=p['id']+'@'+p['version']
        if ref in v['contracts']:raise BoardError('冻结版本不可修改，先提影响提案',409)
        v['contracts'][ref]={**p,'status':'frozen'}

    def verify(self):
        previous='0'*64
        with self.store.connection() as db:rows=list(db.execute('SELECT * FROM governance_events ORDER BY seq'))
        for seq,row in enumerate(rows,1):
            expected=digest({'seq':seq,'actor':row['actor'],'request_id':row['request_id'],'event':json.loads(row['payload']),'previous':previous})
            if row['seq']!=seq or row['prev_hash']!=previous or expected!=row['hash']:raise BoardError('治理审计链损坏',409)
            previous=expected
        return {'passed':True,'events':len(rows),'head':previous}
