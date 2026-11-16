"""Scope-bound collaboration and delivery checks over the operations journal.

Comments never rewrite task scope or release exclusion locks. Human/Agent
statements and actual machine observations remain distinct evidence classes.
"""
from copy import deepcopy
import re,time,uuid
from .store import BoardError,fields,text,integer,identifiers,evidence,digest
from .operations import manager,task_at

KEYS=('threads','reads','plans','plan_heads','claims','verdicts','findings','checks','rollbacks','executors','defaults')
ACTIONS={'thread_open','thread_reply','thread_decide','thread_ack','thread_resolve','thread_read','thread_wait',
         'criteria_defaults','criteria_plan','criteria_claim','criteria_review','review_open','review_disposition','review_resolve','git_check',
         'rollback_plan','rollback_confirm','rollback_approve','rollback_cancel','rollback_claim','rollback_heartbeat','rollback_finish','rollback_recover','rollback_apply','rollback_executor'}
ACTIONS |= {'criteria_claim_batch','criteria_review_batch','git_check_batch'}
ACTIONS.add('thread_supersede')

def commutes(action,p,actor,old,new):
    """Compare the actual read set, not unrelated runner heartbeats.

    Requests retain their original ID/body/revision. A competing decision on the
    same object still conflicts; state transitions and scope checks run again
    under the same write transaction. This is not a client-side blind rebase.
    """
    # Succession reads both threads; a stale replacement must never commute.
    if action=='thread_supersede':return False
    if action in ('thread_open','thread_wait'):
        if action=='thread_wait' and type(p.get('thread')) is not str:return False
        if action=='thread_wait' and old.get('wf_threads',{}).get(p.get('thread'))!=new.get('wf_threads',{}).get(p.get('thread')):return False
        return not p.get('pause') or {k:s for k,s in old.get('sessions',{}).items() if s['actor']==actor['id'] and s['end'] is None}=={k:s for k,s in new.get('sessions',{}).items() if s['actor']==actor['id'] and s['end'] is None}
    if action=='review_open':
        return not p.get('criterion') or type(p.get('task')) is str and old.get('wf_plan_heads',{}).get(p['task'])==new.get('wf_plan_heads',{}).get(p['task'])
    if action in ('rollback_plan','git_check'):return True
    if action in ('thread_reply','thread_read'):
        return isinstance(p.get('thread'),str) and p['thread'] in old.get('wf_threads',{}) and p['thread'] in new.get('wf_threads',{})
    if action.startswith('thread_'):
        return isinstance(p.get('thread'),str) and old.get('wf_threads',{}).get(p['thread'])==new.get('wf_threads',{}).get(p['thread'])
    if action in ('criteria_claim','criteria_review'):
        if type(p.get('plan')) is not str or type(p.get('criterion')) is not str:return False
        key=p['plan']+':'+p['criterion'];tid=p.get('task')
        return type(tid) is str and all(old.get(k,{}).get(key)==new.get(k,{}).get(key) for k in ('wf_claims','wf_verdicts')) and old.get('wf_plan_heads',{}).get(tid)==new.get('wf_plan_heads',{}).get(tid)
    if action=='criteria_plan':
        tid=p.get('task')
        return type(tid) is str and old.get('wf_plan_heads',{}).get(tid)==new.get('wf_plan_heads',{}).get(tid) and old.get('wf_defaults',{})==new.get('wf_defaults',{})
    if action in ('review_disposition','review_resolve'):
        return type(p.get('finding')) is str and old.get('wf_findings',{}).get(p['finding'])==new.get('wf_findings',{}).get(p['finding'])
    # Each rollback transition checks the frozen manifest, context, status,
    # actor and lease; it never overwrites another transition unconditionally.
    if action.startswith('rollback_') and action!='rollback_executor':return True
    return False

def prepare(v):
    for key in KEYS:v.setdefault('wf_'+key,{})
    return v

def uid(value,label='ID'):
    text(value,label,100)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}',value):raise BoardError(label+'需字母数字及 . _ -')
    if value.endswith('.') or value.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[x+str(i) for x in ('COM','LPT') for i in range(1,10)]}:raise BoardError(label+'不能使用Windows保留名称')
    return value

def task(db,p):
    t=task_at(db,p)
    if p.get('scope_version')!=t['scope_version']:raise BoardError('任务范围代次已变化',409)
    return t

def own(t,actor,r):
    if t['owner']!=actor['id']:raise BoardError('仅当前任务执行者操作',403)

def input_anchor(value):
    if type(value) is not str or not re.fullmatch(r'(git:[0-9a-f]{40}|sha256:[0-9a-f]{64})',value):raise BoardError('需固定Git或产物输入锚点')
    return value

def independent(t,actor,v,g):
    from .assurance import effective
    if effective(v,t,g)['level']=='strict' and actor['id']==t['owner']:raise BoardError('严格任务需不同审核身份；身份区别不证明模型独立',403)

def current(row,t):return row.get('scope')==t['scope_hash'] and row.get('scope_version')==t['scope_version']

def stopped(v,t):
    return [e['id'] for e in v.get('wf_threads',{}).values() if e['task']==t['spec']['id'] and e['status']!='resolved' and (e.get('decision') or {}).get('decision')=='stop' and current(e['decision'],t)]

def wait_choice(v,db,t,thread,p,actor,r,now,g,ts):
    from .finishing import participant
    if thread['author']!=actor['id']:raise BoardError('等待选择属于留言者本人',403)
    participant(v,t,p,actor)
    if not current(thread,t):raise BoardError('旧范围留言不能改变当前作业状态',409)
    if p['pause'] and thread['status']=='resolved':raise BoardError('已解决留言不再进入等待',409)
    if not p['pause'] and stopped(v,t):raise BoardError('SE已明确停止此范围；自主等待不能覆盖停止决定',409)
    from .timing import mutate as timing
    if p['pause']:
        timing(v,db,actor,r,'time_change',{'task':t['spec']['id'],'scope':t['scope_hash'],'mode':'wait','phase':'implementation','reason':'评论阻塞 '+thread['id']+'：'+thread['affected_step'],'rework':False,**{k:p[k] for k in ('attempt_id','attempt_lease') if k in p}},now,g,ts)
    else:
        waiting=[s for s in v['sessions'].values() if s['actor']==actor['id'] and s['task']==t['spec']['id'] and s['end'] is None and s['reason'].startswith('评论阻塞 '+thread['id']+'：')]
        if waiting:timing(v,db,actor,r,'time_change',{'task':t['spec']['id'],'scope':t['scope_hash'],'mode':'work','phase':'implementation','reason':'留言者自主继续：'+thread['id'],'rework':False,**{k:p[k] for k in ('attempt_id','attempt_lease') if k in p}},now,g,ts)
    thread['pause']=p['pause']

def plan_for(v,t):
    plan=v.get('wf_plans',{}).get(v.get('wf_plan_heads',{}).get(t['spec']['id']))
    return plan if plan and current(plan,t) else None

def run_refs(v,t,refs,anchor):
    identifiers(refs,'验证运行')
    for rid in refs:
        run=v['runs'].get(rid)
        if not run or run['status']!='passed' or run['input_anchor']!=anchor or run['scopes'].get(t['spec']['id'])!=t['scope_hash'] or run.get('scope_versions',{}).get(t['spec']['id'])!=t['scope_version']:
            raise BoardError('验证运行须通过且匹配当前范围、代次和精确输入',409)

def decision_ref(db,ref,tid):
    if not ref:raise BoardError('正式变更须关联实际范围或接口变更事件',409)
    row=db.execute('SELECT task_id,kind FROM events WHERE id=?',(ref,)).fetchone()
    if row and row['task_id']==tid and row['kind']=='scope':return
    # Governance receipts use sequence/hash; both must identify the actual event.
    for row in db.execute('SELECT seq,hash,payload FROM governance_events'):
        if ref==str(row['seq'])+':'+row['hash'] and __import__('json').loads(row['payload'])['action']=='contract_execute':return
    raise BoardError('未找到本任务范围事件或本项目已执行接口变更',409)

def criteria(rows,t):
    if type(rows) is not list or not 1<=len(rows)<=64:raise BoardError('需1至64条验收标准')
    ids=set();deliverables={x['id'] for x in t['spec']['deliverables']}
    for c in rows:
        fields(c,{'id','deliverable','expected','method'},{'id','deliverable','expected','method'});uid(c['id'],'标准ID')
        if c['id'] in ids:raise BoardError('标准ID重复')
        ids.add(c['id']);text(c['expected'],'可判定预期',4000)
        if c['deliverable'] not in deliverables or c['method'] not in ('inspection','manual','automated'):raise BoardError('交付项或验证方式无效')
    if {c['deliverable'] for c in rows}!=deliverables:raise BoardError('验收标准必须覆盖全部交付项',409)

def reader(store,db,rid):
    from .git_tracking import Tracking,load
    from .git_reader import Reader
    from .git_tracking import repo_id
    repo_id(rid);state=load(db);repo=state['repos'].get(rid)
    if not repo or not repo['enabled']:raise BoardError('项目仓库不存在或已停用',404)
    return Reader(Tracking(store).mirror(rid,repo),state['policy']),repo

def ancestry(rd,a,b):
    rd.commit(a);rd.commit(b)
    # Exit-1 from merge-base is a normal false answer; rev-list has no such
    # ambiguity and stays inside the reader's capped, audited process boundary.
    return not rd.git(['rev-list','--max-count=1',a,'--not',b]).strip()

def git_check(store,db,p,t,v,actor,now):
    fields(p,{'task','scope','scope_version','repo','baseline','implementation','target','phase','reason'},
           {'task','scope','scope_version','repo','baseline','implementation','target','phase','reason'})
    from .git_reader import sha
    from .governance import overlaps
    for key in ('baseline','implementation','target'):sha(p[key])
    if p['phase'] not in ('submit','merge','native'):raise BoardError('Git核验阶段无效')
    text(p['reason'],'核验依据',4000);baseline=t['spec'].get('work',{}).get('baseline')
    if baseline!=p['baseline']:raise BoardError('基线必须是本任务固定基线',409)
    rd,repo=reader(store,db,p['repo']);files=rd.files(p['baseline'],p['implementation'])
    paths=sorted({f[k] for f in files for k in ('path','old_path') if f.get(k)})
    if not ancestry(rd,p['baseline'],p['implementation']) or not ancestry(rd,p['implementation'],p['target']):raise BoardError('基线、实现、目标不在声明的祖先链',409)
    for path in paths:
        rd.allowed(path)
        if not any(path==a.rstrip('/') or path.startswith(a.rstrip('/')+'/') for a in t['spec']['allowed_paths']):raise BoardError('实际Git写路径越出任务范围：'+path,409)
    anchor='git:'+p['target'];matching=[r['id'] for r in v['runs'].values() if r['status']=='passed' and r['input_anchor']==anchor and r['scopes'].get(t['spec']['id'])==t['scope_hash'] and r.get('scope_versions',{}).get(t['spec']['id'])==t['scope_version']]
    return {**deepcopy(p),'id':uuid.uuid4().hex,'files':paths,'diff_sha256':digest(files),'exact_input_runs':matching,'actor':actor['id'],'at':now,'observation':'服务端只读Git核验；祖先关系不替代精确目标测试'}

def mutate(v,db,actor,r,action,p,now,g,tasks,store):
    prepare(v)
    from .finishing import BATCH_ACTIONS,batch,participant,public_record
    if action in BATCH_ACTIONS:return batch(v,db,actor,r,action,p,now,g,tasks,store)
    strings={'attempt_id','attempt_lease','id','thread','kind','title','body','affected_step','decision','summary','reference','plan','criterion','claim','result','finding','status','input_anchor','reason','defaults','repo','baseline','implementation','target','phase','manifest_hash','object','target_ref','data_plan','tests','commit','lease','actor','scope','task','previous','disposition'}
    for key in strings & set(p):
        if type(p[key]) is not str or len(p[key])>8000:raise BoardError(key+'需有界字符串')
    for key in {'pause','git_required','blocking','enabled'} & set(p):
        if type(p[key]) is not bool:raise BoardError(key+'需布尔')
    for key in {'scope_version','count'} & set(p):integer(p[key],key)
    if action.startswith('rollback_'):
        from .rollback import mutate as rollback
        return rollback(v,db,actor,r,action,p,now,g,tasks,store)
    if action=='criteria_defaults':
        manager(r);fields(p,{'id','items','reason'},{'id','items','reason'});uid(p['id']);identifiers(p['items'],'项目完成清单');text(p['reason'],'依据',4000)
        if not 1<=len(p['items'])<=32:raise BoardError('项目完成清单需1至32项')
        for item in p['items']:text(item,'完成要求',180)
        if p['id'] in v['wf_defaults']:raise BoardError('清单版本不可覆盖',409)
        v['wf_defaults'][p['id']]={**deepcopy(p),'actor':actor['id'],'at':now};return
    if action in ('thread_reply','thread_decide','thread_ack','thread_resolve','thread_read','thread_wait','thread_supersede'):
        text(p.get('thread'),'线程ID',180)
        thread=v['wf_threads'].get(p.get('thread'))
        if not thread:raise BoardError('评论线程不存在',404)
        t=tasks[thread['task']];tid=t['spec']['id']
        if action=='thread_supersede':
            manager(r);fields(p,{'thread','replacement','summary'},{'thread','replacement','summary'})
            text(p['summary'],'接续依据',4000);uid(p['replacement'],'接续线程ID')
            target=v['wf_threads'].get(p['replacement'])
            if not target or target['id']==thread['id'] or target['task']!=tid:raise BoardError('需同任务的另一现有线程',409)
            if thread['status']=='resolved' or target['status']=='resolved' or not current(target,t):raise BoardError('接续线程须处于当前范围且未解决',409)
            if thread['kind']!='discussion' or target['kind']!='discussion' or thread.get('pause') or any((x.get('decision') or {}).get('decision')=='stop' and current(x['decision'],t) for x in (thread,target)):
                raise BoardError('阻塞、等待或停止决定需按原流程核准，不可用讨论接续解除',409)
            thread.update(status='resolved',superseded_by=target['id'],resolved_by=actor['id'],resolved_at=now,updated=now)
            thread['messages'].append({'id':uuid.uuid4().hex,'actor':actor['id'],'body':p['summary'],'at':now,'kind':'supersede','replacement':target['id']})
            target.setdefault('supersedes',[]).append(thread['id']);target['updated']=now
            return {'thread':thread['id'],'replacement':target['id']}
        if action=='thread_read':
            fields(p,{'thread','count'},{'thread','count'});integer(p['count'],'已读位置')
            if p['count']>len(thread['messages']):raise BoardError('已读位置越界')
            reads=v['wf_reads'].setdefault(actor['id'],{});reads[p['thread']]=max(reads.get(p['thread'],0),p['count']);return
        if action=='thread_wait':
            fields(p,{'thread','pause','summary','attempt_id','attempt_lease'},{'thread','pause','summary'});text(p['summary'],'等待选择依据',4000)
            if type(p['pause']) is not bool:raise BoardError('pause需布尔值')
            wait_choice(v,db,t,thread,p,actor,r,now,g,tasks)
            thread['messages'].append({'id':uuid.uuid4().hex,'actor':actor['id'],'body':p['summary'],'at':now,'kind':'wait' if p['pause'] else 'continue'})
        elif action=='thread_reply':
            fields(p,{'thread','body'},{'thread','body'});text(p['body'],'回复',8000)
            thread['messages'].append({'id':uuid.uuid4().hex,'actor':actor['id'],'body':p['body'],'at':now,'kind':'reply'})
        elif action=='thread_decide':
            manager(r);fields(p,{'thread','decision','summary','reference'},{'thread','decision','summary','reference'})
            if p['decision'] not in ('continue','changes','stop'):raise BoardError('决策需continue/changes/stop')
            text(p['summary'],'决策依据',8000)
            if p['decision']=='changes':decision_ref(db,p['reference'],tid)
            elif p['reference']:text(p['reference'],'参考',200)
            thread['decision']={**deepcopy(p),'scope':t['scope_hash'],'scope_version':t['scope_version'],'actor':actor['id'],'at':now}
            thread['status']='awaiting_worker';thread['messages'].append({'id':uuid.uuid4().hex,'actor':actor['id'],'body':p['summary'],'at':now,'kind':'decision'})
        elif action=='thread_ack':
            fields(p,{'thread','summary','attempt_id','attempt_lease'},{'thread','summary'})
            if t['owner']!=actor['id']:
                if thread['author']!=actor['id'] or p.get('attempt_id')!=thread.get('attempt_id'):raise BoardError('仅此尝试作者或任务负责人确认',403)
                participant(v,t,p,actor)
            text(p['summary'],'确认',4000);decision=thread.get('decision')
            if not decision or not current(decision,t) or decision['decision']=='stop':raise BoardError('需SE对当前范围作出可继续的决定',409)
            thread.update(status='resolved',resolved_by=actor['id'],resolved_at=now)
            thread['messages'].append({'id':uuid.uuid4().hex,'actor':actor['id'],'body':p['summary'],'at':now,'kind':'ack'})
            for session in v['sessions'].values():
                if session['actor']==actor['id'] and session['end'] is None and session['reason'].startswith('评论阻塞 '+thread['id']+'：'):session['end']=now
        else:
            fields(p,{'thread','summary'},{'thread','summary'});text(p['summary'],'解决依据',4000)
            if (thread.get('decision') or {}).get('decision')=='stop' and current(thread['decision'],t):manager(r)
            if thread['kind']!='discussion':manager(r)
            elif actor['id']!=thread['author']:manager(r)
            thread.update(status='resolved',resolved_by=actor['id'],resolved_at=now)
            thread['messages'].append({'id':uuid.uuid4().hex,'actor':actor['id'],'body':p['summary'],'at':now,'kind':'resolve'})
        thread['updated']=now
        if len(thread['messages'])>1000:raise BoardError('线程过长，请新建关联讨论',409)
        return {'thread':thread['id']}
    t=task(db,p);tid=t['spec']['id']
    if action=='thread_open':
        keys={'task','scope','scope_version','id','kind','title','body','to','pause','affected_step'};fields(p,keys|{'attempt_id','attempt_lease'},keys);uid(p['id'])
        if p['id'] in v['wf_threads']:raise BoardError('线程ID不可覆盖',409)
        if p['kind'] not in ('discussion','blocker','deviation') or type(p['pause']) is not bool:raise BoardError('评论类型或暂停标记无效')
        if p['kind']!='discussion':participant(v,t,p,actor)
        if p['pause']:participant(v,t,p,actor)
        for key in ('title','body','affected_step'):text(p[key],key,8000)
        identifiers(p['to'],'接收人')
        if any(id not in g['members'] and id not in ('root','SE') for id in p['to']):raise BoardError('接收人需本项目成员或SE',404)
        v['wf_threads'][p['id']]={**public_record(p),'author':actor['id'],'status':'open','created':now,'updated':now,'messages':[{'id':uuid.uuid4().hex,'actor':actor['id'],'body':p['body'],'kind':'opening','at':now}]}
        if p['pause']:wait_choice(v,db,t,v['wf_threads'][p['id']],p,actor,r,now,g,tasks)
        return {'thread':p['id']}
    if action=='criteria_plan':
        manager(r);keys={'task','scope','scope_version','id','items','defaults','git_required','repo','reason'};fields(p,keys,keys);uid(p['id']);criteria(p['items'],t);text(p['reason'],'计划依据',4000)
        if t['status'] in ('accepted','merged','native_accepted','baseline_merged','partial_accepted','partial_merged','partial_native'):raise BoardError('先重新打开或追加范围，再变更已验收任务的验收计划',409)
        if p['id'] in v['wf_plans'] or type(p['git_required']) is not bool:raise BoardError('计划不可覆盖，Git标记需布尔',409)
        if p['defaults'] and p['defaults'] not in v['wf_defaults']:raise BoardError('项目完成清单版本不存在',409)
        if p['git_required']:
            from .git_tracking import load
            if p['repo'] not in load(db)['repos']:raise BoardError('项目Git绑定不存在',409)
        elif p['repo']:raise BoardError('未启用Git核验时仓库留空')
        default_id=p['defaults'] or max(v['wf_defaults'],key=lambda key:v['wf_defaults'][key]['at'],default='')
        defaults=deepcopy(v['wf_defaults'].get(default_id,{}).get('items',[]));items=deepcopy(p['items'])
        items += [{'id':'DOD-'+str(i+1),'deliverable':t['spec']['deliverables'][0]['id'],'method':'inspection','expected':value} for i,value in enumerate(defaults)]
        criteria(items,t)
        v['wf_plans'][p['id']]={**deepcopy(p),'defaults':default_id,'items':items,'default_items':defaults,'actor':actor['id'],'at':now};v['wf_plan_heads'][tid]=p['id'];return {'plan':p['id']}
    if action=='git_check':
        if r not in ('owner','se','reviewer') :own(t,actor,r)
        check=git_check(store,db,p,t,v,actor,now);v['wf_checks'][check['id']]=check;return {'check':check['id']}
    if action in ('criteria_claim','criteria_review'):
        plan=plan_for(v,t)
        if not plan or p.get('plan')!=plan['id']:raise BoardError('需当前范围验收计划',409)
        selected=next((x for x in plan['items'] if x['id']==p.get('criterion')),None)
        if not selected:raise BoardError('验收项不存在',404)
        key=plan['id']+':'+p['criterion']
        if action=='criteria_claim':
            own(t,actor,r);keys={'task','scope','scope_version','plan','criterion','input_anchor','summary','runs','evidence'};fields(p,keys,keys);input_anchor(p['input_anchor']);text(p['summary'],'实际验证结果',8000)
            if t['status'] in ('accepted','merged','native_accepted','baseline_merged','partial_accepted','partial_merged','partial_native'):raise BoardError('已验收任务不能改写当前声明，先由SE重新打开',409)
            run_refs(v,t,p['runs'],p['input_anchor']);evidence(p['evidence']) if p['evidence'] else None
            if selected['method']=='automated' and not any(v['runs'][rid].get('suite') for rid in p['runs']):raise BoardError('自动验收项需精确输入的实际自动运行，手工声明不能替代',409)
            v['wf_claims'][key]={**deepcopy(p),'id':uuid.uuid4().hex,'actor':actor['id'],'at':now};return {'claim':v['wf_claims'][key]['id']}
        manager(r);independent(t,actor,v,g);keys={'task','scope','scope_version','plan','criterion','claim','result','summary','evidence'};fields(p,keys,keys)
        claim=v['wf_claims'].get(key)
        if not claim or claim['id']!=p['claim']:raise BoardError('执行者声明已变化，重读后评审',409)
        if p['result'] not in ('passed','failed'):raise BoardError('结论需passed/failed')
        text(p['summary'],'审核结果',8000);evidence(p['evidence']) if p['evidence'] else None
        v['wf_verdicts'][key]={**deepcopy(p),'actor':actor['id'],'at':now};return
    if action=='review_open':
        if r not in ('owner','se','reviewer','tester'):raise BoardError('需审核者或测试角色',403)
        keys={'task','scope','scope_version','id','criterion','description','acceptance','blocking','anchor','previous'};fields(p,keys,keys);uid(p['id'])
        if p['id'] in v['wf_findings'] or type(p['blocking']) is not bool:raise BoardError('发现ID不可覆盖，阻塞需布尔',409)
        for key in ('description','acceptance'):text(p[key],key,8000)
        a=p['anchor'];fields(a,{'commit','path','line','resource'},{'commit','path','line','resource'})
        from .git_reader import sha,safe_path
        if a['commit']:sha(a['commit'])
        if a['path']:safe_path(a['path'])
        integer(a['line'],'行号')
        if a['resource']:
            from .resources import pointer
            pointer(a['resource'])
        if p['criterion'] and (not plan_for(v,t) or p['criterion'] not in [i['id'] for i in plan_for(v,t)['items']]):raise BoardError('标准ID不存在',409)
        if p['previous'] and (p['previous'] not in v['wf_findings'] or v['wf_findings'][p['previous']]['task']!=tid):raise BoardError('继承发现需同任务已有发现',409)
        v['wf_findings'][p['id']]={**deepcopy(p),'author':actor['id'],'status':'open','at':now,'history':[]};return {'finding':p['id']}
    if action in ('review_disposition','review_resolve'):
        finding=v['wf_findings'].get(p.get('finding'))
        if not finding or finding['task']!=tid:raise BoardError('发现不存在',404)
        if action=='review_disposition':
            own(t,actor,r);keys={'task','scope','scope_version','finding','status','input_anchor','summary','runs','evidence'};fields(p,keys,keys)
            if p['status'] not in ('fixed','rejected'):raise BoardError('处置需fixed/rejected')
            input_anchor(p['input_anchor']);run_refs(v,t,p['runs'],p['input_anchor']);evidence(p['evidence']) if p['evidence'] else None;text(p['summary'],'处置事实',8000)
            finding['disposition']={**deepcopy(p),'id':uuid.uuid4().hex,'actor':actor['id'],'at':now};finding['status']='awaiting_review'
        else:
            manager(r);independent(t,actor,v,g);keys={'task','scope','scope_version','finding','disposition','result','summary','evidence'};fields(p,keys,keys);text(p['summary'],'复核依据',8000);evidence(p['evidence']) if p['evidence'] else None
            d=finding.get('disposition')
            if not d or d['id']!=p['disposition'] or not current(d,t):raise BoardError('需当前范围的最新处置',409)
            if p['result'] not in ('fixed','dismissed','reopen'):raise BoardError('复核需fixed/dismissed/reopen')
            if p['result']=='fixed' and d['status']!='fixed':raise BoardError('异议不能直接当修复',409)
            finding['status']='open' if p['result']=='reopen' else p['result'];finding['resolution']={**deepcopy(p),'input_anchor':d['input_anchor'],'actor':actor['id'],'at':now}
        finding['history'].append({'action':action,'payload':deepcopy(p),'actor':actor['id'],'at':now});return
    raise BoardError('工作流动作不存在',404)

def blockers(v,t,stage='submit',anchor=None):
    # Receipt collection never certifies correctness. Outstanding decisions,
    # criteria and exact-input observations are enforced at SE approval.
    if stage=='submit':return []
    out=[];tid=t['spec']['id']
    out += ['SE明确停止：'+key for key in stopped(v,t)]
    for e in v.get('wf_threads',{}).values():
        if e['task']==tid and e['kind'] in ('blocker','deviation') and e['status']!='resolved':out.append('评论待解决：'+e['id'])
    for e in v.get('wf_rollbacks',{}).values():
        if tid in e['affected_tasks'] and e['status'] not in ('proposed','cancelled','failed','applied'):out.append('回退正在处理：'+e['id'])
        if tid in e['affected_tasks'] and e['status']=='applied' and current(e['task_scopes'].get(tid,{}),t):out.append('当前成果已回退，需追加范围并重新验证：'+e['id'])
    if stage in ('accept','merge','native'):
        for e in v.get('wf_findings',{}).values():
            if e['task']==tid and e['blocking'] and e['status'] not in ('fixed','dismissed'):out.append('评审发现未关闭：'+e['id'])
            if stage=='accept' and e['task']==tid and e['blocking'] and e['status'] in ('fixed','dismissed') and e.get('resolution',{}).get('input_anchor')!=anchor:out.append('评审处置未核对本次精确输入：'+e['id'])
    plan=plan_for(v,t)
    if not plan:
        if tid in v.get('wf_plan_heads',{}):out.append('结构化验收计划属于旧范围，需SE重新核定')
        return out
    for c in plan['items']:
        key=plan['id']+':'+c['id'];claim=v.get('wf_claims',{}).get(key);verdict=v.get('wf_verdicts',{}).get(key)
        if not claim or claim['input_anchor']!=anchor:out.append('验收项缺少精确输入声明：'+c['id'])
        elif stage=='accept' and (not verdict or verdict['claim']!=claim['id'] or verdict['result']!='passed'):out.append('验收项尚未审核通过：'+c['id'])
    if plan['git_required'] and anchor and anchor.startswith('git:'):
        phase='submit' if stage in ('submit','accept') else stage
        checks=[c for c in v.get('wf_checks',{}).values() if c['task']==tid and current(c,t) and c['repo']==plan['repo'] and c['phase']==phase and 'git:'+c['target']==anchor]
        if not checks:out.append('缺少本阶段精确提交Git核验')
    elif plan['git_required']:out.append('此验收计划要求Git提交输入')
    return out

def snapshot(store,actor,task_id=None,inbox_only=False):
    from .operations import load
    from .governance import tasks,load as gov,role
    with store.connection() as db:
        db.execute('BEGIN');v=prepare(load(db));ts=tasks(db);g=gov(db);r=role(db,actor)
        if task_id and task_id not in ts:raise BoardError('本项目任务不存在',404)
        from .candidates import readiness
        detail_readiness=readiness(store,db,ts[task_id]) if task_id else None
    if task_id and task_id not in ts:raise BoardError('本项目任务不存在',404)
    is_manager=r in ('owner','se','reviewer');now=time.time();items=[];unread={}
    for e in v['wf_threads'].values():
        relevant=is_manager or e['author']==actor['id'] or ts[e['task']]['owner']==actor['id'] or actor['id'] in e['to']
        count=max(0,len(e['messages'])-v['wf_reads'].get(actor['id'],{}).get(e['id'],0));unread[e['id']]=count
        if relevant and (e['status']!='resolved' or count):items.append({'kind':'thread','id':e['id'],'task':e['task'],'title':e['title'],'status':e['status'],'unread':count,**({'waiting_seconds':round(now-e['updated'],2)} if e['status']!='resolved' else {})})
    for tid,t in ts.items():
        if is_manager and t['status']=='submitted':items.append({'kind':'submission','id':tid,'task':tid,'title':t['spec']['title'],'status':'候选待评审','blockers':detail_readiness['blockers'] if task_id==tid else blockers(v,t,'accept',submission_anchor(t))})
        if is_manager and tid in v['wf_plan_heads'] and not plan_for(v,t):items.append({'kind':'criteria_plan','id':tid,'task':tid,'title':t['spec']['title'],'status':'验收计划需核定新范围'})
    if is_manager:
        for key,claim in v['wf_claims'].items():
            verdict=v['wf_verdicts'].get(key);t=ts[claim['task']];plan=plan_for(v,t)
            if plan and plan['id']==claim['plan'] and (not verdict or verdict['claim']!=claim['id']):items.append({'kind':'criterion','id':key,'task':claim['task'],'title':'验收项 '+claim['criterion'],'status':'待逐项审核'})
    for e in v['wf_findings'].values():
        if e['status'] not in ('fixed','dismissed') and (is_manager or ts[e['task']]['owner']==actor['id']):items.append({'kind':'finding','id':e['id'],'task':e['task'],'title':e['description'],'status':e['status']})
    for e in v['wf_rollbacks'].values():
        if is_manager and e['status'] not in ('cancelled','failed','applied'):items.append({'kind':'rollback','id':e['id'],'task':next(iter(e['affected_tasks']),''),'title':e['reason'],'status':e['status']})
    if task_id:items=[i for i in items if i['task']==task_id]
    if inbox_only:return {'revision':v['revision'],'items':items,'as_of':now}
    result={key:v['wf_'+key] for key in KEYS}
    if task_id:
        for key in ('threads','plans','claims','verdicts','findings','checks'):result[key]={k:e for k,e in result[key].items() if e['task']==task_id}
        result['rollbacks']={k:e for k,e in result['rollbacks'].items() if task_id in e['affected_tasks']}
        result['blockers']=detail_readiness['blockers'] if ts[task_id].get('latest_submission') else blockers(v,ts[task_id],'accept',submission_anchor(ts[task_id]));result['current_plan']=plan_for(v,ts[task_id]);result['delivery_readiness']=detail_readiness
    from .focus import groups
    result.update(revision=v['revision'],inbox=items,unread=unread,actor=actor['id'],project_role=r,schema=1,**groups(items))
    # Read positions belong to the caller, not to every project member.
    result['reads']=v['wf_reads'].get(actor['id'],{})
    return result

def submission_anchor(t):
    s=t.get('latest_submission') or {}
    return 'git:'+s['implementation_commit'] if s.get('implementation_commit') else 'sha256:'+s['artifact']['sha256'] if s.get('artifact') else None

def enforce(db,t,action,p):
    from .operations import load
    v=load(db)
    anchor=('git:'+p['implementation_commit'] if p.get('implementation_commit') else 'sha256:'+p['artifact']['sha256'] if p.get('artifact') else None) if action=='submit' else 'git:'+p['commit'] if action in ('merge','native') else submission_anchor(t)
    reasons=blockers(v,t,action,anchor)
    if action in ('merge','native'):
        reasons=[reason for reason in reasons if not reason.startswith('验收项缺少精确输入声明')]
        reasons+=blockers(v,t,'accept',submission_anchor(t))
        plan=plan_for(v,t)
        if plan and plan['git_required']:
            if not any(c['task']==t['spec']['id'] and current(c,t) and c['phase']==action and c['repo']==plan['repo'] and 'git:'+c['target']==anchor and c['implementation']==(t.get('latest_submission') or {}).get('implementation_commit') for c in v.get('wf_checks',{}).values()):reasons.append('缺少本次实现到合入/运行目标的Git核验')
            if not any(run['status']=='passed' and run['input_anchor']==anchor and run['scopes'].get(t['spec']['id'])==t['scope_hash'] and run.get('scope_versions',{}).get(t['spec']['id'])==t['scope_version'] for run in v['runs'].values()):reasons.append('最终合入/运行提交需精确输入实际运行')
        # Criteria judge the submitted implementation. Merge-target correctness
        # is separately tested; never demand re-claiming criteria on another SHA.
    if reasons:raise BoardError('；'.join(dict.fromkeys(reasons)),409)
