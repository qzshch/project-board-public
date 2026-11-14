"""Risk tiers are scope-bound manager decisions, not worker self-exemptions."""
from copy import deepcopy
from .store import BoardError,fields,text,identifiers,evidence
from .operations import manager,task_at

LEVELS={'light':0,'standard':1,'strict':2}
FLAGS={'public_interface','cross_module','persistent_data','permission','production','shared_asset','unknown_impact'}
STRICT={'persistent_data','permission','production','shared_asset','unknown_impact'}
NONCODE={'research','collection','generation','documentation'}


def effective(v,task,g):
    w=task['spec'].get('work',{});a=v['assessments'].get(task['spec']['id'])
    current=bool(a and a['scope']==task['scope_hash'] and a['scope_version']==task['scope_version'])
    flags=set(a['flags']) if current else set()
    if w.get('contracts') or w.get('couplings'):flags.add('cross_module')
    m=g.get('modules',{}).get(w.get('planning',{}).get('module'),{})
    if m.get('interfaces'):flags.add('cross_module')
    minimum='strict' if flags & STRICT else 'standard' if flags else 'light'
    from .convergence import reuse_effective
    reuse=reuse_effective(v,task,g)
    chosen=a['level'] if current else reuse['level'] if reuse and reuse['valid'] else v['policy']['profile']
    level=max((chosen,minimum),key=LEVELS.get)
    return {'enabled':v['policy']['enabled'] or bool(reuse),'level':level,'minimum':minimum,'flags':sorted(flags),'assessed':bool(reuse['valid']) if reuse else current,
            'reason':reuse['reason'] if reuse else a['reason'] if current else '使用项目默认；派发前需核定当前任务风险','policy_reason':v['policy']['reason'],**({'rule':reuse['rule']} if reuse else {})}


def mutate(v,db,actor,r,action,p,now,g,tasks):
    manager(r)
    if action=='policy':
        fields(p,{'profile','reason'},{'profile','reason'})
        if p['profile'] not in LEVELS:raise BoardError('治理档位需light/standard/strict')
        text(p['reason'],'策略依据');v['policy']={'enabled':True,**deepcopy(p),'actor':actor['id'],'at':now}
    elif action=='assess_package':
        fields(p,{'package','scopes','level','flags','reason'},{'package','scopes','level','flags','reason'})
        text(p['package'],'任务包ID',180);package=g['packages'].get(p['package'])
        if not package or p['scopes']!={t:tasks[t]['scope_hash'] for t in package['tasks']}:raise BoardError('任务包不存在或范围变化',409)
        for tid in package['tasks']:mutate(v,db,actor,r,'assess',{'task':tid,'scope':p['scopes'][tid],'level':p['level'],'flags':p['flags'],'reason':p['reason']},now,g,tasks)
    else:
        fields(p,{'task','scope','level','flags','reason'},{'task','scope','level','flags','reason'})
        task_at(db,p);identifiers(p['flags'],'风险')
        if not set(p['flags'])<=FLAGS or p['level'] not in LEVELS:raise BoardError('风险/档位无效')
        text(p['reason'],'裁剪/评估依据',8000)
        candidate={**deepcopy(p),'scope_version':tasks[p['task']]['scope_version'],'actor':actor['id'],'at':now};trial={**v,'assessments':{**v['assessments'],p['task']:candidate}}
        if LEVELS[p['level']]<LEVELS[effective(trial,tasks[p['task']],g)['minimum']]:raise BoardError('已知影响不能降到最低风险要求以下',409)
        v['assessments'][p['task']]=candidate


def admission(db,task,g):
    from .operations import load
    from .governance import tasks
    g={**g,'_cv_tasks':tasks(db)}
    v=load(db);e=effective(v,task,g)
    return e,(['当前任务范围尚未由SE评估风险'] if e['enabled'] and not e['assessed'] else [])


def validation(db,task,p,g,actor=None,registry=None):
    from .operations import load
    from .quality import validate_delivery
    from .governance import tasks
    g={**g,'_cv_tasks':tasks(db)};v=load(db);e=effective(v,task,g)
    if registry:
        g['consumption']=registry.consumption();e=effective(v,task,g)
    if not e['enabled']:return None
    if not e['assessed']:raise BoardError('当前范围缺少风险评估',409)
    if e['level']=='light':
        verification=p.get('verification')
        fields(verification,{'method','summary','reason'},{'method','summary','reason'})
        if verification['method'] not in ('inspection','manual','automated','not_applicable'):raise BoardError('验证方式无效')
        text(verification['summary'],'实际检查结果');text(verification['reason'],'验证选择依据')
        if verification['method']=='automated':validate_delivery(v,task,p)
    else:
        from .governance import tasks
        from .planning import task_blockers
        reasons=task_blockers({**g,'planning_policy':{'mode':'enforced'}},tasks(db),task['spec'])
        if reasons:raise BoardError('；'.join(reasons),409)
        validate_delivery(v,task,p,strict=e['level']=='strict')
        if actor and e['level']=='strict' and task.get('owner')==actor['id']:raise BoardError('严格任务须独立审核者核验',409)
    return e


def delivery_evidence(value,level):
    if level=='light' and value==[]:return []
    return evidence(value)
