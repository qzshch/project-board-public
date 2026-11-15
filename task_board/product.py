"""Incremental product definitions. A task result is not a product verdict.

Records live in the existing project journal; legacy intake IDs remain stable.
Only explicit adoption opts old records into these stricter product semantics.
"""
from copy import deepcopy
from .store import BoardError, fields, text, integer, digest, evidence
from .operations import manager
from .coordination import prepare, exact, reference, record, sequence

ACTIONS={'product_open','product_adopt','product_edit','product_confirm','product_schedule',
         'product_change','product_change_decide','product_link','product_verify','product_dispose',
         'defect_retest','defect_reopen','finding_promote','session_register'}
DEFINITION={'title','body','audience','outcome','scope','non_goals','questions','priority','origin','owner','criteria',
            'actual','expected','environment','observed_version','steps','severity'}

def commutes(action,p,actor,old,new):
    """Unrelated runner heartbeats must not invalidate an open product form.

    Mutation still checks the live object version, task scopes and permissions.
    This permits no rebase when the product object itself has changed.
    """
    key=p.get('id')
    if type(key) is not str:return False
    if action in ('product_open','session_register'):
        table='session_registry' if action=='session_register' else 'co_intakes'
        return key not in new.get(table,{})
    if action=='finding_promote':return type(p.get('finding')) is str and old.get('wf_findings',{}).get(p['finding'])==new.get('wf_findings',{}).get(p['finding'])
    before=old.get('co_intakes',{}).get(key);after=new.get('co_intakes',{}).get(key)
    if not after or before!=after or p.get('expected_version')!=after['version']:return False
    if action=='product_change_decide':return type(p.get('change')) is str and old.get('product_changes',{}).get(p['change'])==new.get('product_changes',{}).get(p['change'])
    return True

def checked(p,required,optional=''):
    fields(p,set((required+' '+optional).split()),set(required.split()))

def definition(p,kind):
    if type(p) is not dict or set(p)-DEFINITION:raise BoardError('产品定义字段无效')
    out=deepcopy(p)
    for key,value in out.items():
        if key=='criteria':
            sequence(value,'验收标准',64);seen=set()
            for c in value:
                checked(c,'id expected');text(c['id'],'标准ID',80);text(c['expected'],'预期结果',4000)
                if c['id'] in seen:raise BoardError('标准ID重复')
                seen.add(c['id'])
        else:
            if type(value) is not str or len(value)>8000:raise BoardError(key+'需有界文本')
    text(out.get('title'),'标题',200);text(out.get('body'),'问题',8000)
    if out.get('priority','P2') not in ('P0','P1','P2','P3'):raise BoardError('优先级无效')
    if out.get('severity','unknown') not in ('critical','major','minor','trivial','unknown'):raise BoardError('严重度无效')
    if out.get('origin','process') not in ('initial','process','retrospective','post_project'):raise BoardError('提出阶段无效')
    if kind=='defect' and out.get('criteria'):raise BoardError('缺陷使用预期/复测，不复制需求验收项')
    return out

def get(v,p):
    integer(p.get('expected_version'),'产品记录版本',1)
    e=exact(v['co_intakes'],p.get('id'))
    if e.get('product_model_version')!=1:raise BoardError('先显式采用产品模型，历史结论保留',409)
    if p.get('expected_version')!=e['version']:raise BoardError('对象已有新版本；重读差异后决定',409)
    return e

def current_definition(e):return e['definitions'][str(e['definition_version'])]

def changed_criteria(old,new):
    a={c['id']:c for c in old.get('criteria',[])};b={c['id']:c for c in new.get('criteria',[])}
    shared=any(old.get(k)!=new.get(k) for k in ('body','audience','outcome','scope','non_goals'))
    return sorted(set(a)|set(b)) if shared else sorted(k for k in set(a)|set(b) if a.get(k)!=b.get(k))

def mutate(v,db,actor,r,action,p,now,g,ts,store):
    prepare(v);v.setdefault('product_changes',{});v.setdefault('session_registry',{})
    for key in ('id','change','finding','criterion','task','task_scope','milestone','status','duplicate','decision','impact_hash','input_anchor','environment','result','reason','previous','locator','model','runtime','machine','attempt','session','role','kind'):
        if key in p and (type(p[key]) is not str or len(p[key])>8000):raise BoardError(key+'需有界字符串')
    if action=='session_register':
        checked(p,'id session runtime machine role tasks previous status','attempt locator model')
        for key in ('id','runtime','machine','role','status'):text(p[key],key,160)
        if type(p['session']) is not str or len(p['session'])>256 or any(c.isspace() for c in p['session']):raise BoardError('原生Session ID无效；未知用空字符串')
        if p['session'].startswith(('github_pat_','ghp_','sk-')):raise BoardError('凭据不能登记为会话ID')
        if p.get('model'):text(p['model'],'模型路由',160)
        if p['role'] not in ('se','worker','reviewer','researcher') or p['status'] not in ('unknown','active','waiting','completed','interrupted'):raise BoardError('会话角色/状态无效')
        sequence(p['tasks'],'任务',100)
        for tid in p['tasks']:
            t=exact(ts,tid)
            if r not in ('owner','se','reviewer') and t['owner']!=actor['id']:raise BoardError('只能登记自己领取任务的会话',403)
        if not p['tasks']:manager(r)
        if p['previous']:exact(v['session_registry'],p['previous'])
        if p['id'] in v['session_registry']:raise BoardError('会话引用不可覆盖；接续用新ID',409)
        if p.get('attempt'):
            a=exact(v.get('cv_attempts',{}),p['attempt'])
            if a['task'] not in p['tasks']:raise BoardError('尝试不属于关联任务',409)
        if p.get('locator'):
            from .resources import pointer
            pointer(p['locator'])
        v['session_registry'][p['id']]={**record(p,actor,now),'evidence_class':'external_reference_not_control_proof'}
        return {'session_reference':p['id']}
    if action=='finding_promote':
        checked(p,'finding id reason');f=exact(v.get('wf_findings',{}),p['finding']);text(p['reason'],'提升原因',4000)
        for e in v['co_intakes'].values():
            if e.get('promoted_finding')==p['finding']:return {'intake':e['id'],'already_promoted':True}
        p={'id':p['id'],'kind':'defect','definition':{'title':f.get('title',f.get('description','评审发现'))[:200],'body':f.get('body',f.get('description',p['reason'])),'expected':f.get('acceptance','')},'sources':[{'kind':'finding','id':p['finding']}]}
        promoted=f['id'] if 'id' in f else p['sources'][0]['id'];action='product_open'
    else:promoted=None
    if action in ('product_open','product_adopt'):
        if action=='product_open':
            checked(p,'id kind definition sources');text(p['id'],'ID',100)
            if p['kind'] not in ('requirement','defect'):raise BoardError('产品类型无效')
            if p['id'] in v['co_intakes']:raise BoardError('ID不可覆盖',409)
            sequence(p['sources'],'来源',16)
            for ref in p['sources']:reference(v,g,ts,ref,actor,r)
            d=definition(p['definition'],p['kind']);e={**record({'id':p['id'],'kind':'bug' if p['kind']=='defect' else 'requirement','title':d['title'],'body':d['body'],'sources':p['sources']},actor,now),'version':1,'history':[],'tasks':[],'modules':[]}
            v['co_intakes'][e['id']]=e
        else:
            manager(r);checked(p,'id expected_version reason');e=exact(v['co_intakes'],p['id']);text(p['reason'],'采用原因',4000)
            if e.get('product_model_version') or e['version']!=p['expected_version']:raise BoardError('已采用或历史版本已变化',409)
            d={'title':e['title'],'body':e['body']};e['legacy_disposition']={k:deepcopy(e.get(k)) for k in ('status','version','history')};e['version']+=1
        e.update(product_model_version=1,product_kind='defect' if e['kind']=='bug' else 'requirement',status='triage' if e['kind']=='bug' else 'idea',definitions={'1':d},definition_version=1,confirmed=False,commitment=None,mappings=[],verifications={},retests=[],engineering_pending=[],dispositions=[])
        if promoted:e['promoted_finding']=promoted
        e['history'].append(record({'action':action},actor,now));return {'intake':e['id'],'version':e['version']}
    e=get(v,p);text(p.get('reason',''),'决定依据',4000)
    if action=='product_edit':
        checked(p,'id expected_version definition reason')
        if e['confirmed']:raise BoardError('已确认定义不可覆盖，使用变更提案',409)
        if e['actor']!=actor['id']:manager(r)
        d=definition(p['definition'],e['product_kind']);e['definition_version']+=1;e['definitions'][str(e['definition_version'])]=d;e.update(title=d['title'],body=d['body'])
    elif action=='product_confirm':
        manager(r);checked(p,'id expected_version reason');d=current_definition(e)
        if e['product_kind']=='requirement':
            for key in ('audience','outcome','scope','non_goals','owner'):text(d.get(key),key,8000)
            if not d.get('criteria'):raise BoardError('确认需求需稳定ID验收标准',409)
        else:
            for key in ('expected','actual','environment','observed_version','steps'):text(d.get(key),key,8000)
        if e['confirmed']:raise BoardError('已经确认',409)
        e.update(confirmed=True,status='confirmed')
    elif action=='product_schedule':
        manager(r);checked(p,'id expected_version milestone reason')
        if not e['confirmed']:raise BoardError('先确认需求或缺陷',409)
        if p['milestone'] and p['milestone'] not in g.get('milestones',{}) and p['milestone'] not in g.get('milestone_plans',{}):raise BoardError('里程碑不存在',404)
        e['commitment']={'milestone':p['milestone'],'at':now,'actor':actor['id']}
    elif action=='product_change':
        checked(p,'id expected_version change definition reason');text(p['change'],'变更ID',100)
        if not e['confirmed']:raise BoardError('草案直接编辑，无需提案',409)
        if p['change'] in v['product_changes']:raise BoardError('变更ID不可覆盖',409)
        new=definition(p['definition'],e['product_kind']);affected=changed_criteria(current_definition(e),new)
        affected_tasks=sorted({m['task'] for m in e['mappings'] if m['criterion'] in affected or e['product_kind']=='defect'})
        # Include reverse hard dependencies; interfaces and milestone assessment remain explicit unknowns.
        trans=set(affected_tasks)
        while True:
            found={tid for tid,t in ts.items() if any(dep in trans for dep in t['spec'].get('depends_on',[]))}
            if found<=trans:break
            trans|=found
        impact={'criteria':affected,'tasks':affected_tasks,'downstream':sorted(trans-set(affected_tasks)),'task_scopes':{t:ts[t]['scope_hash'] for t in trans},'interfaces':'requires_SE_assessment','assets':'requires_SE_assessment','milestone':e['commitment']}
        v['product_changes'][p['change']]={**record(p,actor,now),'base':e['definition_version'],'proposed':new,'impact':impact,'impact_hash':digest(impact),'status':'proposed'}
    elif action=='product_change_decide':
        manager(r);checked(p,'id expected_version change decision impact_hash migration reason');c=exact(v['product_changes'],p['change'])
        if c['id']!=e['id'] or c['base']!=e['definition_version'] or c['status']!='proposed' or p['impact_hash']!=c['impact_hash']:raise BoardError('变更基线或影响快照已变化',409)
        if any(ts[t]['scope_hash']!=scope for t,scope in c['impact']['task_scopes'].items()):raise BoardError('受影响任务范围已有变化；重新评估',409)
        if p['decision'] not in ('approve','defer','reject'):raise BoardError('变更决定无效')
        text(p['migration'],'影响核定与迁移办法',8000);c.update(status=p['decision'],decision=record(p,actor,now))
        if p['decision']=='approve':
            e['definition_version']+=1;e['definitions'][str(e['definition_version'])]=c['proposed'];e.update(title=c['proposed']['title'],body=c['proposed']['body'],status='confirmed')
            for cid in c['impact']['criteria']:e['verifications'].pop(cid,None)
            e['engineering_pending']=sorted(set(e['engineering_pending'])|set(c['impact']['tasks']))
    elif action=='product_link':
        manager(r);checked(p,'id expected_version criterion task task_scope reason');t=exact(ts,p['task'])
        ids={c['id'] for c in current_definition(e).get('criteria',[])}
        if e['product_kind']=='requirement' and p['criterion'] not in ids:raise BoardError('需求标准不存在',404)
        if p['task_scope']!=t['scope_hash']:raise BoardError('任务范围已变化',409)
        m={'criterion':p['criterion'],'task':p['task'],'task_scope':p['task_scope'],'definition_version':e['definition_version']}
        e['mappings']=[x for x in e['mappings'] if (x['criterion'],x['task'])!=(m['criterion'],m['task'])]+[m]
        e['verifications'].pop(p['criterion'],None)
        e['tasks']=sorted(set(e['tasks'])|{p['task']});e['engineering_pending']=[tid for tid in e['engineering_pending'] if tid!=p['task']]
    elif action=='product_verify':
        manager(r);checked(p,'id expected_version criterion evidence reason')
        if e['product_kind']!='requirement' or not e['confirmed'] or e['engineering_pending']:raise BoardError('当前需求未确认或仍待工程核定',409)
        mappings=[m for m in e['mappings'] if m['criterion']==p['criterion']]
        if not mappings or not any(c['id']==p['criterion'] for c in current_definition(e)['criteria']):raise BoardError('标准缺少任务覆盖',409)
        for m in mappings:
            t=exact(ts,m['task'])
            if m['task_scope']!=t['scope_hash'] or t['status'] not in ('accepted','merged','native_accepted'):raise BoardError('关联任务尚未在当前范围验收',409)
        evidence(p['evidence']);e['verifications'][p['criterion']]={**record(p,actor,now),'definition_version':e['definition_version'],'task_scopes':{m['task']:m['task_scope'] for m in mappings}}
        if all(c['id'] in e['verifications'] for c in current_definition(e)['criteria']):e['status']='achieved'
    elif action=='defect_retest':
        manager(r);checked(p,'id expected_version input_anchor environment runs evidence result reason')
        if e['product_kind']!='defect' or not e['confirmed']:raise BoardError('先确认缺陷和修复范围',409)
        if e['engineering_pending'] or p['environment']!=current_definition(e).get('environment'):raise BoardError('缺陷仍待工程核定或不是约定复测环境',409)
        from .workflow import input_anchor
        input_anchor(p['input_anchor']);text(p['environment'],'复测环境',1000);evidence(p['evidence']);sequence(p['runs'],'运行',64)
        if p['result'] not in ('passed','failed'):raise BoardError('复测结果无效')
        if not e['tasks'] or not p['runs']:raise BoardError('复测需实际修复任务和运行',409)
        covered=set()
        for rid in p['runs']:
            run=exact(v['runs'],rid)
            environments={run.get('actual_environment',run.get('environment'))} if run.get('suite') else {v['cases'][c['case']]['environment'] for c in run.get('results',[])}
            if run.get('input_anchor')!=p['input_anchor'] or environments!={p['environment']} or run.get('status')!=p['result'] or not run.get('results'):raise BoardError('运行版本、环境或结果不匹配',409)
            for tid,scope in run['scopes'].items():
                if ts.get(tid,{}).get('scope_hash')==scope and ts[tid]['scope_version']==run['scope_versions'][tid]:covered.add(tid)
        for tid in e['tasks']:
            t=exact(ts,tid);sub=t.get('latest_submission') or {};target=sub.get('payload',sub).get('implementation_commit')
            if tid not in covered or not target or p['input_anchor']!='git:'+target or t['status'] not in ('accepted','merged','native_accepted'):raise BoardError('复测未覆盖当前已验收修复输入',409)
            from .workflow import independent
            independent(t,actor,v,g)
        e['retests'].append(record(p,actor,now));e['status']='closed' if p['result']=='passed' else 'reopened'
    elif action=='defect_reopen':
        checked(p,'id expected_version reason');
        if e['product_kind']!='defect':raise BoardError('仅缺陷可重开')
        e['status']='reopened'
    elif action=='product_dispose':
        manager(r);checked(p,'id expected_version status duplicate reason')
        if p['status'] not in ('clarifying','investigating','deferred','rejected','duplicate','not_a_bug','wont_fix','archived'):raise BoardError('处置无效；通过需要业务核验/复测')
        if p['status']=='duplicate':
            target=exact(v['co_intakes'],p['duplicate']);seen={e['id']}
            while target:
                if target['id'] in seen:raise BoardError('重复关系成环',409)
                seen.add(target['id']);target=v['co_intakes'].get(target.get('duplicate'))
        elif p['duplicate']:raise BoardError('仅重复处置填写目标')
        if p['status']=='archived' and e['status'] not in ('achieved','closed','rejected','duplicate','not_a_bug','wont_fix'):raise BoardError('尚无明确结果，不能归档',409)
        e.update(status=p['status'],duplicate=p['duplicate']);e['dispositions'].append(record(p,actor,now))
    else:raise BoardError('未知产品动作',404)
    e['version']+=1;e['history'].append(record({'action':action,**p},actor,now));return {'intake':e['id'],'version':e['version']}

def snapshot(store,actor):
    from .operations import load
    from .governance import load as gov, role, tasks
    from .coordination import sanitize
    with store.connection() as db:
        db.execute('BEGIN');g=gov(db);r=role(db,actor);v=sanitize(prepare(load(db)),g,actor,r);ts=tasks(db)
        items=deepcopy(v['co_intakes'])
        for e in items.values():
            if not e.get('product_model_version'):continue
            e['definition']=current_definition(e);e['task_facts']={tid:{'status':ts[tid]['status'],'scope':ts[tid]['scope_hash']} for tid in e['tasks'] if tid in ts}
            facts=list(e['task_facts'].values())
            e['delivery_state']='needs_engineering_reconciliation' if e['engineering_pending'] else 'awaiting_business_verification' if facts and all(t['status'] in ('accepted','merged','native_accepted') for t in facts) else 'in_progress' if any(t['status'] in ('active','submitted','changes_requested') for t in facts) else 'planned' if facts else 'unscheduled'
            e['stale_verifications']=[cid for cid,proof in e['verifications'].items() if any(ts.get(tid,{}).get('scope_hash')!=scope or ts[tid]['status'] not in ('accepted','merged','native_accepted') for tid,scope in proof['task_scopes'].items())]
            if e['stale_verifications'] and e['status']=='achieved':e['status']='verification_stale'
            if e['product_kind']=='defect' and e['status']=='closed' and e['retests']:
                proof=e['retests'][-1]
                for rid in proof['runs']:
                    run=v['runs'].get(rid,{})
                    if any(ts.get(tid,{}).get('scope_hash')!=scope or 'git:'+(ts.get(tid,{}).get('latest_submission') or {}).get('implementation_commit','')!=proof['input_anchor'] for tid,scope in run.get('scopes',{}).items()):e['status']='retest_stale'
        return {'revision':v['revision'],'items':items,'changes':{k:c for k,c in v.get('product_changes',{}).items() if c['id'] in items},'sessions':v.get('session_registry',{})}
