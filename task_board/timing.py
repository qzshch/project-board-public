"""Declared work sessions, waiting, revisions and conservative local estimates."""
from copy import deepcopy
from datetime import datetime
import math
import statistics
import uuid
import hashlib
import json
from .store import BoardError,fields,text,integer
from .operations import manager,task_at

PHASES={'research','design','implementation','testing','review','integration','release','asset','governance'}
DONE={'accepted','merged','native_accepted','baseline_merged'}


def number(value,name,maximum=1000000):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=maximum:raise BoardError(name+'需有界非负数')
    return value


def mutate(v,db,actor,r,action,p,now,g,tasks):
    if action=='time_correct':
        manager(r);fields(p,{'session','seconds','reason'},{'session','seconds','reason'})
        s=v['sessions'].get(p['session'])
        if not s or s['end'] is None:raise BoardError('只能校正已结束的作业时段',409)
        number(p['seconds'],'校正秒数',s['end']-s['start']);text(p['reason'],'校正依据')
        s['corrections'].append({'seconds':p['seconds'],'reason':p['reason'],'actor':actor['id'],'at':now});return
    if action=='time_close':
        manager(r);fields(p,{'session','reason'},{'session','reason'})
        s=v['sessions'].get(p['session'])
        if not s or s['end'] is not None:raise BoardError('时段未开启',409)
        text(p['reason'],'关闭依据');s.update(end=now,closed_by=actor['id'],close_reason=p['reason']);return
    task=task_at(db,p)
    if r not in ('owner','se','reviewer') and task['owner']!=actor['id']:
        if action!='time_change':raise BoardError('仅负责人可核定整个任务的时间完整性或估算',403)
        from .finishing import participant
        participant(v,task,p,actor)
    if action=='estimate':
        keys={'task','scope','low','likely','high','due','size','uncertainty','context','reason'};fields(p,keys,keys)
        for k in ('low','likely','high'):number(p[k],k)
        if not 0<p['low']<=p['likely']<=p['high']:raise BoardError('估算分钟数需0<low<=likely<=high')
        if p['size'] not in ('small','medium','large') or p['uncertainty'] not in ('low','medium','high'):raise BoardError('规模/不确定性无效')
        text(p['context'],'执行者/工具/环境/复用背景',2000);text(p['reason'],'估算或重估依据')
        if p['due']:
            try:
                due=datetime.fromisoformat(p['due'].replace('Z','+00:00'))
                if due.tzinfo is None:raise ValueError()
            except (ValueError,AttributeError):raise BoardError('计划时间需带时区的ISO时间；不设期限用空字符串')
        elif type(p['due']) is not str:raise BoardError('due需字符串')
        v['estimates'].setdefault(p['task'],[]).append({**deepcopy(p),'scope_version':task['scope_version'],'actor':actor['id'],'at':now})
    elif action=='time_complete':
        fields(p,{'task','scope','summary'},{'task','scope','summary'});text(p['summary'],'记录完整性说明')
        from .retrospective import approved_times
        recorded={**v['sessions'],**approved_times(db)}
        if any(s['task']==p['task'] and s['end'] is None for s in recorded.values()):raise BoardError('仍有未关闭时段',409)
        if not any(s['task']==p['task'] and s['scope']==p['scope'] and s['scope_version']==task['scope_version'] for s in recorded.values()):raise BoardError('没有当前范围的时间记录',409)
        v['time_complete'][p['task']]={**deepcopy(p),'scope_version':task['scope_version'],'actor':actor['id'],'at':now}
    else:
        fields(p,{'task','scope','mode','phase','reason','rework','attempt_id','attempt_lease'},{'task','scope','mode','phase','reason','rework'})
        if p.get('attempt_id'):
            from .finishing import participant
            participant(v,task,p,actor)
        p={k:val for k,val in p.items() if k!='attempt_lease'}
        if p['mode'] not in ('work','wait','pause','stop') or p['phase'] not in PHASES or type(p['rework']) is not bool:raise BoardError('时间状态/阶段/返修标记无效')
        if p['mode']=='work':
            from .workflow import stopped
            if stopped(v,task):raise BoardError('SE明确停止当前范围，不能自行恢复作业',409)
        text(p['reason'],'作业或等待原因')
        for s in v['sessions'].values():
            if s['actor']==actor['id'] and s['end'] is None:s['end']=now
        v['time_complete'].pop(p['task'],None)
        if p['mode']!='stop':
            sid=uuid.uuid4().hex;v['sessions'][sid]={**deepcopy(p),'scope_version':task['scope_version'],'actor':actor['id'],'actor_kind':g['members'].get(actor['id'],{}).get('actor_kind','unknown'),'start':now,'end':None,'corrections':[]};return {'session':sid}


def report(v,tasks,now,db):
    by_task={};phases={};waiting={};by_kind={'human':0,'agent':0,'unknown':0};work=wait=pause=rework=0
    for sid,s in v['sessions'].items():
        seconds=s['corrections'][-1]['seconds'] if s['corrections'] else max(0,(s['end'] or now)-s['start'])
        t=by_task.setdefault(s['task'],{'work_seconds':0,'wait_seconds':0,'pause_seconds':0,'rework_seconds':0,'open':False,'actors':set()})
        t[s['mode']+'_seconds']+=seconds;t['actors'].add(s['actor']);t['open'] |= s['end'] is None
        if s['mode']=='work':
            work+=seconds;phases[s['phase']]=phases.get(s['phase'],0)+seconds
            by_kind[s['actor_kind']]+=seconds
            if s['rework']:rework+=seconds;t['rework_seconds']+=seconds
        elif s['mode']=='wait':wait+=seconds;waiting[s['reason']]=waiting.get(s['reason'],0)+seconds
        else:pause+=seconds
    observed={row['task_id']:dict(row) for row in db.execute("SELECT task_id,MIN(created_at) first,MAX(created_at) last FROM events GROUP BY task_id")}
    estimates={k:rows[-1] for k,rows in v['estimates'].items() if rows}
    samples=[];comparisons=[]
    for tid,task in tasks.items():
        t=by_task.get(tid);estimate=estimates.get(tid);complete=v['time_complete'].get(tid)
        revised=max((s['corrections'][-1]['at'] for s in v['sessions'].values() if s['task']==tid and s.get('retrospective') and s['scope']==task['scope_hash'] and s['scope_version']==task['scope_version']),default=0)
        covered=bool(t and complete and complete['scope']==task['scope_hash'] and complete['scope_version']==task['scope_version'] and not t['open'] and complete.get('at',0)>=revised)
        row={'task':tid,'observed_first':observed.get(tid,{}).get('first'),'observed_last':observed.get(tid,{}).get('last'),
             'work_seconds':round(t['work_seconds'],2) if t else None,'wait_seconds':round(t['wait_seconds'],2) if t else None,
             'time_complete':covered,'estimate_current':bool(estimate and estimate['scope']==task['scope_hash'] and estimate['scope_version']==task['scope_version']),
             'estimated_minutes':estimate['likely'] if estimate else None,'due':estimate['due'] if estimate else None}
        if row['observed_first']:
            begin=datetime.fromisoformat(row['observed_first']).timestamp();end=datetime.fromisoformat(row['observed_last']).timestamp() if task['status'] in DONE else now
            row['observed_elapsed_seconds']=max(0,round(end-begin,2))
        else:row['observed_elapsed_seconds']=None
        row['estimate_error_ratio']=(row['work_seconds']/60-estimate['likely'])/estimate['likely'] if covered and estimate and row['estimate_current'] else None
        row['current_work_seconds']=round(sum((s['corrections'][-1]['seconds'] if s['corrections'] else (s['end'] or now)-s['start']) for s in v['sessions'].values() if s['task']==tid and s['scope_version']==task['scope_version'] and s['scope']==task['scope_hash'] and s['mode']=='work'),2) if t else None
        row['estimate_error_ratio']=(row['current_work_seconds']/60-estimate['likely'])/estimate['likely'] if covered and estimate and row['estimate_current'] else None
        row['overdue']=bool(estimate and estimate['due'] and task['status'] not in DONE and datetime.fromisoformat(estimate['due'].replace('Z','+00:00')).timestamp()<now)
        if t:row['actors']=sorted(t['actors']);row['rework_seconds']=round(t['rework_seconds'],2);row['open']=t['open']
        comparisons.append(row)
        if covered and task['status'] in DONE and row['estimate_current']:
            minutes=sum((s['corrections'][-1]['seconds'] if s['corrections'] else s['end']-s['start'])/60 for s in v['sessions'].values() if s['task']==tid and s['scope']==task['scope_hash'] and s['scope_version']==task['scope_version'] and s['mode']=='work')
            samples.append({'task':tid,'category':task['spec'].get('work',{}).get('category','unknown'),'minutes':minutes,'estimate':estimate})
    forecasts={}
    benchmark_groups={}
    for s in samples:
        key=(s['category'],s['estimate']['size'],s['estimate']['uncertainty'],s['estimate']['context']);benchmark_groups.setdefault(key,[]).append(s['minutes'])
    groups=[dict(category=k[0],size=k[1],uncertainty=k[2],context=k[3],samples=len(values),p50_minutes=statistics.median(values),p80_minutes=sorted(values)[math.ceil(.8*len(values))-1]) for k,values in benchmark_groups.items() if len(values)>=5]
    for tid,e in estimates.items():
        if tid not in tasks:continue
        category=tasks[tid]['spec'].get('work',{}).get('category','unknown')
        matched=[s['minutes'] for s in samples if s['task']!=tid and s['category']==category and all(s['estimate'][k]==e[k] for k in ('size','uncertainty','context'))]
        forecasts[tid]={'samples':len(matched),'p50_minutes':statistics.median(matched) if len(matched)>=5 else None,'p80_minutes':sorted(matched)[math.ceil(.8*len(matched))-1] if len(matched)>=5 else None,'confidence':'reference' if len(matched)>=5 else 'insufficient_samples','source':'local'}
        if len(matched)<5:
            candidates=[(alias,b,row) for alias,b in v['benchmarks'].items() if b.get('available') for row in b['groups'] if row['category']==category and all(row[k]==e[k] for k in ('size','uncertainty','context'))]
            if candidates:
                alias,b,row=max(candidates,key=lambda x:x[2]['samples']);forecasts[tid]={k:row[k] for k in ('samples','p50_minutes','p80_minutes')};forecasts[tid].update(confidence='shared_reference',source=b['release'],local_samples=len(matched))
    memo={};visiting=set()
    def path(tid):
        if tid in memo:return memo[tid]
        if tid in visiting:return {'minutes':None,'path':[]}
        visiting.add(tid);t=tasks[tid]
        if t['status'] in DONE:result={'minutes':0,'path':[]}
        else:
            parents=[path(d) for d in t['spec']['depends_on'] if d in tasks];e=estimates.get(tid)
            if not e or e['scope']!=t['scope_hash'] or e['scope_version']!=t['scope_version'] or any(p['minutes'] is None for p in parents):result={'minutes':None,'path':[]}
            else:
                longest=max(parents,key=lambda p:p['minutes'],default={'minutes':0,'path':[]});result={'minutes':longest['minutes']+e['likely'],'path':longest['path']+[tid]}
        visiting.remove(tid);memo[tid]=result;return result
    paths=[path(k) for k in tasks];known=[p for p in paths if p['minutes'] is not None]
    opportunities=[]
    if waiting:
        top=max(waiting,key=waiting.get);opportunities.append({'kind':'waiting','seconds':waiting[top],'observation':'最大等待原因：'+top,'suggestion':'先核实原因，再评估缩短审核排队或解除资源等待；不直接减少必要验证'})
    if rework:opportunities.append({'kind':'rework','seconds':rework,'observation':'已有明确返修投入','suggestion':'复盘输入、接口和验收理解，补针对性反例；不以一次通过率替代质量'})
    if phases.get('governance'):opportunities.append({'kind':'governance','seconds':phases['governance'],'observation':'已记录治理协调成本','suggestion':'评估低风险流程合并、批量评估和共用运行证据的收益'})
    runtimes={}
    for run in v['runs'].values():
        if not run.get('suite'):continue
        item=runtimes.setdefault(run['suite'],{'runs':0,'seconds':0,'failures':0,'queue_seconds':0});item['runs']+=1;item['seconds']+=sum(r['seconds'] for r in run['results']);item['failures']+=run['status'] in ('failed','timeout','blocked');item['queue_seconds']+=max(0,run.get('started',run.get('finished',now))-run['created'])
    historical_work=sum(s['corrections'][-1]['seconds'] for s in v['sessions'].values() if s.get('retrospective') and s['mode']=='work')
    return {'as_of':now,'calendar':'elapsed_utc','work_seconds':round(work,2),'historical_work_seconds':round(historical_work,2),'wait_seconds':round(wait,2),'pause_seconds':round(pause,2),'rework_seconds':round(rework,2),
            'phases_seconds':phases,'actor_kind_seconds':by_kind,'waiting_seconds':waiting,'tasks':comparisons,'forecasts':forecasts,
            'wait_ratio':wait/(work+wait) if work+wait else None,'rework_ratio':rework/work if work else None,
            'governance_ratio':phases.get('governance',0)/work if work else None,
            'opportunities':opportunities,'automation_runtime':runtimes,'benchmark':{'schema':1,'unit':'minutes','groups':groups},
            'critical_path':{**max(known,key=lambda p:p['minutes'],default={'minutes':None,'path':[]}),'unknown_tasks':sum(p['minutes'] is None for p in paths),'includes_resource_queues':False},
            'note':'作业时间来自显式申报；返修是作业子集。历史未记录投入为未知；相似样本仅本项目，跨项目须审核发布匿名基准资产。'}


def import_benchmark(v,p,registry,actor,r,now):
    manager(r);fields(p,{'asset','document','reason'},{'asset','document','reason'});text(p['asset'],'固定消费引用',180);text(p['reason'],'采用依据')
    document=text(p['document'],'基准文档',100000)
    # Hash the exact supplied UTF-8 document, including its trailing newline.
    sha=hashlib.sha256(p['document'].encode('utf8')).hexdigest();consumption=registry.consumption().get(p['asset'])
    if not consumption or consumption['sha256']!=sha:raise BoardError('基准必须匹配本项目明确批准的固定共享消费SHA',409)
    registry.get(consumption['release'],registry.project)
    try:data=json.loads(document)
    except ValueError:raise BoardError('基准需JSON')
    fields(data,{'schema','unit','groups'},{'schema','unit','groups'})
    if type(data['schema']) is not int or data['schema']!=1 or data['unit']!='minutes' or type(data['groups']) is not list or not 1<=len(data['groups'])<=128:raise BoardError('基准格式或样本组无效')
    from .governance import CATEGORIES
    for row in data['groups']:
        fields(row,{'category','size','uncertainty','context','samples','p50_minutes','p80_minutes'},{'category','size','uncertainty','context','samples','p50_minutes','p80_minutes'})
        if type(row['category']) is not str or row['category'] not in CATEGORIES or row['size'] not in ('small','medium','large') or row['uncertainty'] not in ('low','medium','high'):raise BoardError('基准分类无效')
        text(row['context'],'已审核脱敏的执行背景',2000);integer(row['samples'],'样本数',5);number(row['p50_minutes'],'P50');number(row['p80_minutes'],'P80')
        if row['p50_minutes']>row['p80_minutes']:raise BoardError('P80不能低于P50')
    v['benchmarks'][p['asset']]={'release':consumption['release'],'sha256':sha,'groups':data['groups'],'reason':p['reason'],'actor':actor['id'],'at':now};return {'imported_groups':len(data['groups'])}
