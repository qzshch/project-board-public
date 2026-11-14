"""Bounded integration helpers; original single-item validators stay authoritative."""
from copy import deepcopy
import time
from .store import BoardError,fields,identifiers

BATCH_ACTIONS={'criteria_claim_batch','criteria_review_batch','git_check_batch'}
TERMINAL={'accepted','merged','native_accepted','baseline_merged'}

def participant(v,t,p,actor):
    """Task ownership is unchanged; a participant only acts within its lease."""
    from .convergence import lease_check
    aid=p.get('attempt_id')
    if aid is not None and (type(aid) is not str or len(aid)>160):raise BoardError('attempt_id requires a bounded string')
    if not aid:
        if t['owner']!=actor['id']:raise BoardError('需本人当前有效尝试或任务负责人权限',403)
        return None
    e=v.get('cv_attempts',{}).get(aid)
    if not e or e['task']!=t['spec']['id']:raise BoardError('尝试不属于当前任务',409)
    lease_check(e,{'lease':p.get('attempt_lease')},actor,t,time.time())
    return e

def public_record(p):return {k:deepcopy(val) for k,val in p.items() if k!='attempt_lease'}

def batch(v,db,actor,r,action,p,now,g,ts,store):
    from .workflow import mutate,task
    common={'task','scope','scope_version','plan'}
    if action=='git_check_batch':
        keys={'task','scope','scope_version','repo','baseline','implementation','target','phases','reason'};fields(p,keys,keys);identifiers(p['phases'],'核验阶段')
        if not p['phases'] or not set(p['phases'])<={'submit','merge','native'}:raise BoardError('明确选择有效阶段')
        results=[]
        for phase in p['phases']:results.append(mutate(v,db,actor,r,'git_check',{**{k:val for k,val in p.items() if k!='phases'},'phase':phase},now,g,ts,store))
        return {'checks':results}
    shared={'input_anchor','runs','evidence'} if action=='criteria_claim_batch' else {'evidence'}
    keys=common|shared|{'items'};fields(p,keys,keys);task(db,p)
    if type(p['items']) is not list or not 1<=len(p['items'])<=64:raise BoardError('明确选择1至64条验收项')
    seen=set();results=[]
    for item in p['items']:
        required={'criterion','summary'} if action=='criteria_claim_batch' else {'criterion','claim','result','summary'}
        fields(item,required,required)
        if type(item['criterion']) is not str or item['criterion'] in seen:raise BoardError('验收项重复或无效')
        seen.add(item['criterion'])
        result=mutate(v,db,actor,r,'criteria_claim' if action=='criteria_claim_batch' else 'criteria_review',{**{k:p[k] for k in common|shared},**item},now,g,ts,store)
        results.append({'criterion':item['criterion'],**(result or {})})
    return {'items':results,'atomic':True}

def related_tasks(ts,g,tid):
    if tid not in ts:raise BoardError('本项目任务不存在',404)
    relevant={tid};pending=[tid]
    while pending:
        t=ts[pending.pop()];m=g.get('modules',{}).get(t['spec'].get('work',{}).get('planning',{}).get('module'),{})
        for key in [*t['spec']['depends_on'],*m.get('planning_tasks',[])]:
            if key not in relevant and key in ts:relevant.add(key);pending.append(key)
    return relevant

def event_tasks(v,action,p,tid=''):
    result={tid} if tid else set()
    if type(p.get('task')) is str:result.add(p['task'])
    if type(p.get('tasks')) is list:result.update(x for x in p['tasks'] if type(x) is str)
    for field,maps in [('thread',['wf_threads']),('finding',['wf_findings']),('attempt',['cv_attempts']),('attempt_id',['cv_attempts']),('plan',['co_plans','wf_plans'])]:
        for table in maps:
            value=p.get(field,'');obj=v.get(table,{}).get(value,{}) if type(value) is str else {}
            if obj.get('task'):result.add(obj['task'])
    tables=['co_gates'] if action.startswith(('gate_','condition_')) else ['cv_attempts'] if action.startswith('attempt_') else ['co_intakes'] if action.startswith('intake_') else ['co_batches'] if action=='review_batch' else []
    for table in tables:
        obj=v.get(table,{}).get(p.get('id',''),{})
        if obj.get('task'):result.add(obj['task'])
        result.update(obj.get('tasks',[]))
    if action=='source_link':
        for ref in (p.get('from',{}),p.get('to',{})):
            if ref.get('kind')=='task':result.add(ref.get('id'))
    return result

def conditions(v,ts):
    from .coordination import gate_ok
    from .workflow import current
    nodes=[];edges=[]
    for e in v.get('co_gates',{}).values():
        t=ts.get(e['task'])
        if not t or t['status'] in TERMINAL or e.get('retired') or not current(e,t):continue
        passed=gate_ok(v,e,e['input_anchor'],time.time());key='gate:'+e['id']
        nodes.append({'id':key,'title':e['id']+' · '+{'github_checks':'CI检查','github_pr':'PR合入','human':'授权确认','timer':'时间条件'}[e['kind']],'kind':'condition','category':'condition','status':'已满足' if passed else '未满足 / 已过期','task':e['task'],'stages':e['stages'],'input_anchor':e['input_anchor']})
        edges.append({'from':key,'to':e['task'],'type':'condition'})
    return nodes,edges
