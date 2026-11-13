"""Versioned cases, scope-bound plans and leased runs from trusted runners."""
from copy import deepcopy
import re
import uuid
from .store import BoardError,fields,text,integer,identifiers,evidence,digest
from .operations import manager,task_at
from .planning import ref_of

FINAL={'passed','failed','blocked','cancelled','timeout'}


def anchor(value):
    if not isinstance(value,str) or not re.fullmatch(r'(git:[0-9a-f]{40}|sha256:[0-9a-f]{64})',value):raise BoardError('输入锚点需git:40位或sha256:64位摘要')
    return value


def refs(value,name):
    identifiers(value,name)
    for item in value:text(item,name,180)


def suggestions(v,task):
    w=task['spec'].get('work',{});targets={'task:'+task['spec']['id'],'module:'+w.get('planning',{}).get('module','')}
    targets |= {'contract:'+r for r in w.get('contracts',[])}
    return sorted(ref for ref in v['case_heads'].values() if v['case_status'][ref]['status']=='active' and (set(v['cases'][ref]['targets']) & targets or (v['cases'][ref]['priority']=='critical' and not v['cases'][ref]['targets'])))


def validate_delivery(v,task,p,strict=False):
    plan=v['test_plans'].get(task['spec']['id'])
    if not plan or plan['scope']!=task['scope_hash'] or plan['scope_version']!=task['scope_version']:raise BoardError('缺少当前范围测试计划',409)
    if any(v['case_status'][c]['status']=='withdrawn' for c in plan['cases']):raise BoardError('计划用例已撤回，需重新核定验证',409)
    chosen=p.get('test_runs',[]);refs(chosen,'测试运行ID')
    expected='git:'+p['implementation_commit'] if p.get('implementation_commit') else 'sha256:'+p.get('artifact',{}).get('sha256','')
    covered=set()
    for rid in chosen:
        run=v['runs'].get(rid)
        artifact=p.get('artifact',{})
        bytes_match=bool(artifact and any(a['sha256']==artifact.get('sha256') and artifact.get('ref') in (a['path'],a['location']) for a in (run or {}).get('artifacts',[])))
        if not run or run['status']!='passed' or (run['input_anchor']!=expected and not bytes_match) or run['scopes'].get(task['spec']['id'])!=task['scope_hash'] or run['scope_versions'].get(task['spec']['id'])!=task['scope_version']:raise BoardError('运行未通过或输入/任务范围不匹配',409)
        if strict and not run.get('suite') and run.get('reporter')==task.get('owner'):raise BoardError('严格任务的手工验证需独立测试者',409)
        covered |= {r['case'] for r in run['results'] if r['status']=='passed'}
    if not plan['cases'] or not set(plan['cases'])<=covered:raise BoardError('当前计划用例未全部实际通过',409)


def mutate(v,db,actor,r,action,p,now,g,tasks):
    if action=='case':
        if r not in ('owner','se','reviewer','tester'):raise BoardError('需负责人或测试角色编写用例',403)
        keys={'id','version','title','kind','priority','targets','preconditions','inputs','steps','expected','environment','resources'};fields(p,keys,keys)
        ref=ref_of(p)
        if ref in v['cases']:raise BoardError('用例版本不可覆盖',409)
        if p['kind'] not in ('manual','automated') or p['priority'] not in ('normal','critical'):raise BoardError('用例类型/优先级无效')
        for k in ('title','preconditions','inputs','steps','expected','environment'):text(p[k],k,8000)
        for k in ('targets','resources'):refs(p[k],k)
        for target in p['targets']:
            typ,_,key=target.partition(':')
            if typ not in ('task','module','contract'):raise BoardError('覆盖关系需task:/module:/contract:')
            if (typ=='task' and key not in tasks) or (typ=='module' and key not in g.get('modules',{})) or (typ=='contract' and key not in g['contracts']):raise BoardError('覆盖对象不是本项目已知版本',409)
        v['cases'][ref]={**deepcopy(p),'author':actor['id'],'at':now};v['case_heads'][p['id']]=ref;v['case_status'][ref]={'status':'active','reason':'新用例版本'};return {'case':ref}
    if action=='case_retire':
        manager(r);fields(p,{'ref','mode','reason'},{'ref','mode','reason'});text(p['ref'],'用例版本',180);text(p['reason'],'处置依据')
        if p['ref'] not in v['cases'] or p['mode'] not in ('deprecated','withdrawn'):raise BoardError('用例版本或处置无效')
        v['case_status'][p['ref']]={'status':p['mode'],'reason':p['reason'],'actor':actor['id'],'at':now};return
    if action=='suite':
        manager(r);keys={'id','version','commands','environment','resources','timeout_seconds','artifact_paths'};fields(p,keys,keys);ref=ref_of(p)
        if ref in v['suites']:raise BoardError('套件版本不可覆盖',409)
        integer(p['timeout_seconds'],'超时秒数',1)
        if p['timeout_seconds']>900:raise BoardError('套件最多900秒')
        text(p['environment'],'执行环境',1000);refs(p['resources'],'资源');refs(p['artifact_paths'],'产物路径')
        from pathlib import PurePosixPath
        for path in p['artifact_paths']:
            if PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts or ':' in path or '\\' in path:raise BoardError('产物需安全的相对路径')
        if type(p['commands']) is not list or not 1<=len(p['commands'])<=64:raise BoardError('需1～64个逐用例命令')
        seen=set()
        for command in p['commands']:
            fields(command,{'case','argv'},{'case','argv'});case=v['cases'].get(command['case'])
            if not case or case['kind']!='automated' or command['case'] in seen:raise BoardError('套件需互不重复的本项目自动用例',409)
            seen.add(command['case'])
            if type(command['argv']) is not list or not 1<=len(command['argv'])<=32:raise BoardError('argv需1～32个独立参数')
            for arg in command['argv']:text(arg,'命令参数',2000)
            if not set(case['resources'])<=set(p['resources']):raise BoardError('套件遗漏用例排他资源',409)
        suite={**deepcopy(p),'approved_by':actor['id'],'at':now};v['suites'][ref]=suite
        return {'suite':ref,'manifest_hash':digest(suite)}
    if action=='test_plan':
        manager(r);fields(p,{'task','scope','cases','reason'},{'task','scope','cases','reason'});t=task_at(db,p);refs(p['cases'],'用例');text(p['reason'],'选择依据')
        if not p['cases'] or not set(p['cases'])<=set(v['cases']):raise BoardError('计划需已登记的用例版本',409)
        if any(v['case_status'][c]['status']!='active' for c in p['cases']):raise BoardError('新计划不能选择弃用/撤回用例',409)
        from .assurance import effective
        required=[c for c in suggestions(v,t) if v['cases'][c]['priority']=='critical']
        if effective(v,t,g)['level']=='strict' and not set(required)<=set(p['cases']):raise BoardError('严格任务不能遗漏已登记关键用例',409)
        v['test_plans'][p['task']]={**deepcopy(p),'scope_version':t['scope_version'],'actor':actor['id'],'at':now};return
    if action=='runner':
        manager(r);fields(p,{'actor','environment','enabled','reason'},{'actor','environment','enabled','reason'})
        text(p['actor'],'执行器ID',80)
        if g['members'].get(p['actor'],{}).get('role')!='runner' or type(p['enabled']) is not bool:raise BoardError('先签发本项目runner身份并登记角色',409)
        for k in ('environment','reason'):text(p[k],k,2000)
        v['runners'][p['actor']]=deepcopy(p);return
    if action in ('run_request','manual_run'):
        keys={'tasks','scopes','input_anchor','reason'} | ({'suite'} if action=='run_request' else {'results','evidence','artifacts'})
        fields(p,keys,keys);refs(p['tasks'],'任务');anchor(p['input_anchor']);text(p['reason'],'运行依据')
        if not p['tasks'] or not set(p['tasks'])<=set(tasks):raise BoardError('需本项目任务',409)
        if p['scopes']!={t:tasks[t]['scope_hash'] for t in p['tasks']}:raise BoardError('运行请求的任务范围已变化',409)
        if r not in ('owner','se','reviewer','tester') and any(tasks[t]['owner']!=actor['id'] for t in p['tasks']):raise BoardError('只能验证自己负责的任务',403)
        selected=set()
        for tid in p['tasks']:
            plan=v['test_plans'].get(tid)
            if not plan or plan['scope']!=tasks[tid]['scope_hash'] or plan['scope_version']!=tasks[tid]['scope_version']:raise BoardError('缺少当前范围测试计划',409)
            selected.update(plan['cases'])
        if any(v['case_status'][c]['status']=='withdrawn' for c in selected):raise BoardError('计划用例已撤回',409)
        selected={c for c in selected if v['cases'][c]['kind']==('automated' if action=='run_request' else 'manual')}
        if not selected:raise BoardError('计划没有这种类型的用例',409)
        if action=='run_request':
            text(p['suite'],'套件版本',180)
            s=v['suites'].get(p['suite'])
            if not s or not selected<={c['case'] for c in s['commands']}:raise BoardError('套件未覆盖计划用例',409)
            if not p['input_anchor'].startswith('git:'):raise BoardError('自动执行器需固定Git输入；产物由套件导出并计算SHA')
            run={'suite':p['suite'],'suite_hash':digest(s),'environment':s['environment'],'resources':s['resources'],'cases':sorted(selected),'status':'queued','attempt':0,'attempts':[],'lease':None,'results':[],'artifacts':[]}
        else:
            evidence(p['evidence']);check_results(v,p['results'],selected,manual=True);check_artifacts(p['artifacts'])
            run={'suite':None,'status':'passed' if all(c['status']=='passed' for c in p['results']) else 'failed','cases':sorted(selected),'results':deepcopy(p['results']),'artifacts':deepcopy(p['artifacts']),'evidence':deepcopy(p['evidence']),'reporter':actor['id'],'finished':now,'attempts':[]}
        rid=uuid.uuid4().hex;v['runs'][rid]={**run,'id':rid,'scopes':{t:tasks[t]['scope_hash'] for t in p['tasks']},'scope_versions':{t:tasks[t]['scope_version'] for t in p['tasks']},'input_anchor':p['input_anchor'],'requested_by':actor['id'],'reason':p['reason'],'created':now};return {'run':rid}
    text(p.get('run'),'运行ID',100)
    run=v['runs'].get(p['run'])
    if not run:raise BoardError('运行不存在',404)
    if action=='run_cancel':
        fields(p,{'run','reason'},{'run','reason'});text(p['reason'],'取消原因')
        if r not in ('owner','se','reviewer','tester') and run['requested_by']!=actor['id']:raise BoardError('非本次运行请求者',403)
        if run['status'] in FINAL:raise BoardError('运行已结束',409)
        active=run['status'] in ('running','cancel_requested') and run['lease']['expires']>now
        run.update(status='cancel_requested' if active else 'cancelled',cancel_reason=p['reason'])
        if not active:run['finished']=now
        return
    runner=v['runners'].get(actor['id'])
    if r!='runner' or not runner or not runner['enabled']:raise BoardError('执行器未获本项目授权',403)
    if action=='run_claim':
        fields(p,{'run','suite_hash'},{'run','suite_hash'})
        if run['suite_hash']!=p['suite_hash'] or runner['environment']!=run['environment']:raise BoardError('本地批准摘要/环境不匹配',409)
        if any(v['case_status'][c['case']]['status']=='withdrawn' for c in v['suites'][run['suite']]['commands']):raise BoardError('套件用例已撤回',409)
        if run['status']=='cancel_requested':raise BoardError('运行正在取消',409)
        if not (run['status']=='queued' or (run['status']=='running' and run['lease']['expires']<=now)):raise BoardError('运行不可领取',409)
        for other in v['runs'].values():
            if other['id']!=run['id'] and other['status'] in ('running','cancel_requested') and other['lease']['expires']>now and set(other['resources']) & set(run['resources']):raise BoardError('测试排他资源占用',409)
        from .governance import ACTIVE
        if any(tid not in run['scopes'] and t['status'] in ACTIVE and set(t['spec'].get('work',{}).get('resources',[])) & set(run['resources']) for tid,t in tasks.items()):raise BoardError('测试资源与其他活跃任务冲突',409)
        for tid,scope in run['scopes'].items():
            if tasks[tid]['scope_hash']!=scope or tasks[tid]['scope_version']!=run['scope_versions'][tid]:raise BoardError('运行绑定的任务范围已变化',409)
        if run['lease']:run['attempts'].append({'lease':run['lease'],'outcome':'expired'})
        lease={'id':uuid.uuid4().hex,'actor':actor['id'],'expires':now+30};run.update(status='running',lease=lease,started=now,attempt=run['attempt']+1)
        return {'lease':lease,'suite':deepcopy(v['suites'][run['suite']]),'input_anchor':run['input_anchor']}
    if run['status'] not in ('running','cancel_requested') or not run['lease'] or run['lease']['actor']!=actor['id'] or run['lease']['id']!=p.get('lease') or run['lease']['expires']<=now:raise BoardError('运行租约已过期或归属不符',409)
    if action=='run_heartbeat':
        fields(p,{'run','lease'},{'run','lease'});run['lease']['expires']=now+30;return {'cancel':run['status']=='cancel_requested','expires':run['lease']['expires']}
    keys={'run','lease','status','results','artifacts','evidence','environment','summary'};fields(p,keys,keys)
    if p['status'] not in FINAL:raise BoardError('结束状态无效')
    text(p['environment'],'实际执行环境',4000);text(p['summary'],'执行结果',8000);evidence(p['evidence']);check_artifacts(p['artifacts'])
    check_results(v,p['results'],{c['case'] for c in v['suites'][run['suite']]['commands']},manual=False)
    if p['status']=='passed' and (any(c['status']!='passed' for c in p['results']) or run['status']=='cancel_requested'):raise BoardError('失败/取消不能上报通过',409)
    if p['status']=='passed' and any(tasks[t]['scope_hash']!=s or tasks[t]['scope_version']!=run['scope_versions'][t] for t,s in run['scopes'].items()):raise BoardError('执行期间任务范围已变化，不能顶替新验证',409)
    run.update(status=p['status'],results=deepcopy(p['results']),artifacts=deepcopy(p['artifacts']),evidence=deepcopy(p['evidence']),actual_environment=p['environment'],summary=p['summary'],finished=now)
    run['attempts'].append({'lease':run['lease'],'outcome':p['status'],'finished':now});return {'status':run['status']}


def check_results(v,results,selected,manual):
    if type(results) is not list or not 1<=len(results)<=64:raise BoardError('需逐用例结果')
    seen=set()
    for c in results:
        fields(c,{'case','status','exit_code','seconds','summary'},{'case','status','exit_code','seconds','summary'})
        if c['case'] in seen or c['case'] not in selected or v['cases'][c['case']]['kind']!=('manual' if manual else 'automated'):raise BoardError('用例归属/类型不匹配',409)
        seen.add(c['case'])
        if c['status'] not in ('passed','failed','blocked','cancelled','timeout'):raise BoardError('用例结果无效')
        from .timing import number
        number(c['seconds'],'执行秒数',3600);text(c['summary'],'实际结果',8000)
        if manual:
            if c['exit_code'] is not None:raise BoardError('手工检验不伪造退出码')
        elif type(c['exit_code']) is not int or (c['status']=='passed' and c['exit_code']!=0):raise BoardError('通过结果必须有真实零退出码')
    if seen!=selected:raise BoardError('不能省略计划结果；未执行需记录blocked',409)


def check_artifacts(artifacts):
    if type(artifacts) is not list or len(artifacts)>32:raise BoardError('产物列表过大')
    for a in artifacts:
        fields(a,{'path','sha256','location'},{'path','sha256','location'})
        text(a['path'],'产物路径',1000);text(a['location'],'归档位置',2000)
        if not re.fullmatch('[0-9a-f]{64}',str(a['sha256'])):raise BoardError('产物需SHA256')
