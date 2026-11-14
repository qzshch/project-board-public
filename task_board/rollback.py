"""Frozen, confirmed compensating changes; never rewind an audit database."""
from copy import deepcopy
import json,uuid
from .store import BoardError,fields,text,identifiers,digest,canonical,evidence
from .operations import manager
from .workflow import uid,reader,ancestry,current,run_refs

def context(plan,tasks,g):
    return {'tasks':{id:{'revision':tasks[id]['revision'],'scope':tasks[id]['scope_hash'],'scope_version':tasks[id]['scope_version']} for id in plan['affected_tasks']},
            'modules':{id:g.get('module_heads',{}).get(id) for id in plan.get('module_ids',[])},
            'contracts':{ref:g['contracts'].get(ref,{}).get('status') for id in plan['affected_tasks'] for ref in tasks[id]['spec'].get('work',{}).get('contracts',[])}}

def impact(seeds,tasks,g):
    selected=set(seeds)
    while True:
        products={x for id in selected for x in tasks[id]['spec'].get('work',{}).get('outputs',[])}
        more={id for id,t in tasks.items() if set(t['spec']['depends_on'])&selected or set(t['spec'].get('work',{}).get('inputs',[]))&products}
        if more<=selected:return sorted(selected)
        selected|=more

def fresh(plan,tasks,g,store,db):
    if context(plan,tasks,g)!=plan['context']:raise BoardError('回退影响范围或任务记录已变化，请取消后重新预览',409)
    if plan['commits']:
        rd,repo=reader(store,db,plan['repo'])
        if repo['refs'].get(plan['target_ref'])!=plan['base']:raise BoardError('目标分支已变化，回退方案过期',409)

def append_governance(db,g,actor,action,p,store,request_id):
    from .governance import Governance
    seq=g.pop('revision');previous=g.pop('head');Governance(store)._mutate(db,g,actor,'reviewer',action,p)
    import time
    event={'action':action,'payload':deepcopy(p),'state':g,'at':time.time()};request={'request_id':request_id,'action':action,'payload':p,'expected_revision':seq}
    h=digest({'seq':seq+1,'actor':actor['id'],'request_id':request_id,'event':event,'previous':previous})
    db.execute('INSERT INTO governance_events VALUES(?,?,?,?,?,?,?)',(seq+1,actor['id'],request_id,digest(request),canonical(event),previous,h))
    return {'revision':seq+1,'hash':h}

def mutate(v,db,actor,r,action,p,now,g,tasks,store):
    if action=='rollback_executor':
        manager(r);keys={'actor','kinds','targets','enabled','reason'};fields(p,keys,keys);text(p['actor'],'执行器',100);identifiers(p['kinds'],'回退类型');identifiers(p['targets'],'批准目标');text(p['reason'],'授权依据',4000)
        if type(p['enabled']) is not bool or not set(p['kinds'])<={'code','deploy'} or not p['kinds']:raise BoardError('执行器类型/启用无效')
        if g['members'].get(p['actor'],{}).get('role')!='restorer':raise BoardError('须先授予本项目restorer角色',409)
        v['wf_executors'][p['actor']]={**deepcopy(p),'approved_by':actor['id'],'at':now}
        if not p['enabled']:
            for plan in v['wf_rollbacks'].values():
                if plan['status']=='running' and plan['lease']['actor']==p['actor']:plan.update(cancel_requested=True,cancel_reason='项目执行器授权已停用')
        return
    if action=='rollback_plan':
        manager(r);keys={'id','kind','object','target','tasks','repo','target_ref','base','commits','mainlines','mapping','reason','data_plan','tests'};fields(p,keys,keys);uid(p['id'])
        if p['id'] in v['wf_rollbacks'] or p['kind'] not in ('task','module','code','deploy','asset'):raise BoardError('回退类型无效或ID已存在',409)
        for key in ('object','target','reason','data_plan','tests'):text(p[key],key,8000)
        identifiers(p['tasks'],'影响起点');identifiers(p['commits'],'回退提交')
        if not p['tasks'] or not set(p['tasks'])<=set(tasks):raise BoardError('需明确本项目影响起点任务',409)
        plan={**deepcopy(p),'created_by':actor['id'],'created':now,'status':'proposed','confirmations':{},'module_ids':[]}
        seeds=set(p['tasks'])
        if p['kind']=='task':
            if p['object'] not in tasks or p['object'] not in seeds:raise BoardError('任务回退需包含目标任务',404)
            if p['target']=='current':plan['restore_spec']=deepcopy(tasks[p['object']]['spec'])
            else:
                row=db.execute("SELECT payload FROM events WHERE id=? AND task_id=? AND kind IN ('create','scope')",(p['target'],p['object'])).fetchone()
                if not row:raise BoardError('任务历史范围事件不存在',404)
                plan['restore_spec']=json.loads(row['payload'])['spec']
        elif p['kind']=='module':
            if len(p['id'])>72:raise BoardError('模块回退ID最多72字符，以便生成新版本')
            source=g.get('modules',{}).get(p['target'])
            if not source or source['id']!=p['object']:raise BoardError('模块历史版本不存在',404)
            plan['module_ids']=[p['object']];plan['restore_module']={k:deepcopy(val) for k,val in source.items() if k!='reviews'}
            refs={ref for ref,m in g['modules'].items() if m['id']==p['object']}
            while True:
                more={ref for ref,m in g['modules'].items() if set(m['depends_on'])&refs}
                if more<=refs:break
                refs|=more
            seeds|={id for id,t in tasks.items() if t['spec'].get('work',{}).get('planning',{}).get('module') in refs}
        elif p['kind']=='asset':
            consumer=store.registry.consumption().get(p['object'])
            if not consumer:raise BoardError('本项目消费引用不存在',404)
            release=store.registry.get(p['target'],store.registry.project);plan['asset_sha256']=release['sha256'];plan['previous_asset']=consumer['release']
            seeds|={id for id,t in tasks.items() if p['object'] in t['spec'].get('work',{}).get('assets',[])}
        if p['commits']:
            from .git_reader import sha
            from .governance import overlaps
            if p['kind'] not in ('code','task','module'):raise BoardError('此回退类型不接收代码提交')
            sha(p['base']);rd,repo=reader(store,db,p['repo'])
            if repo['refs'].get(p['target_ref'])!=p['base']:raise BoardError('需当前分支完整提交锚点',409)
            if type(p['mainlines']) is not dict or type(p['mapping']) is not dict or set(p['mapping'])!=set(p['commits']) or not set(p['mainlines'])<=set(p['commits']):raise BoardError('需逐提交映射及明确合并主线')
            paths=set()
            for commit in p['commits']:
                sha(commit);meta=rd.commit(commit)
                if not ancestry(rd,commit,p['base']):raise BoardError('回退提交不属于当前目标分支',409)
                if not meta['parents']:raise BoardError('根提交需专门迁移方案，不自动回退',409)
                main=p['mainlines'].get(commit,1)
                if type(main) is not int or not 1<=main<=len(meta['parents']) or len(meta['parents'])>1 and commit not in p['mainlines']:raise BoardError('合并提交须明确合法mainline',409)
                identifiers(p['mapping'][commit],'提交归属')
                if not p['mapping'][commit] or not set(p['mapping'][commit])<=set(tasks):raise BoardError('提交需映射本项目任务',409)
                seeds|=set(p['mapping'][commit]);changes=rd.files(meta['parents'][main-1],commit)
                for f in changes:
                    for k in ('path','old_path'):
                        if f.get(k):rd.allowed(f[k]);paths.add(f[k])
            plan['paths']=sorted(paths)
            # Conservative write-surface impact includes independent task paths;
            # a declared mapping cannot hide other consumers of shared files.
            seeds|={id for id,t in tasks.items() if any(overlaps(path,a) for path in paths for a in t['spec']['allowed_paths'])}
        elif p['kind']=='code':raise BoardError('代码回退需明确提交清单')
        elif p['repo'] or p['base'] or p['target_ref'] or p['mainlines'] or p['mapping']:raise BoardError('无代码回退时Git字段留空')
        if p['kind']=='deploy' and not any(e['enabled'] and 'deploy' in e['kinds'] and p['object'] in e['targets'] for e in v['wf_executors'].values()):raise BoardError('部署目标尚无获授权项目执行器',409)
        plan['affected_tasks']=impact(seeds,tasks,g);plan['task_scopes']={id:{'scope':tasks[id]['scope_hash'],'scope_version':tasks[id]['scope_version']} for id in plan['affected_tasks']}
        owners={tasks[id]['owner'] for id in plan['affected_tasks'] if tasks[id]['owner']};managers={id for id,m in g['members'].items() if m['role'] in ('owner','se')} or {'root'}
        contract_owners={g['contracts'][ref]['owner'] for id in plan['affected_tasks'] for ref in tasks[id]['spec'].get('work',{}).get('contracts',[]) if ref in g['contracts']}
        plan['required']=sorted(owners|managers|contract_owners);plan['context']=context(plan,tasks,g)
        plan['manifest_hash']=digest({k:val for k,val in plan.items() if k not in ('confirmations','status')});v['wf_rollbacks'][p['id']]=plan
        return {'rollback':p['id'],'manifest_hash':plan['manifest_hash']}
    plan=v['wf_rollbacks'].get(p.get('id'))
    if not plan:raise BoardError('回退单不存在',404)
    if action=='rollback_confirm':
        fields(p,{'id','manifest_hash','summary'},{'id','manifest_hash','summary'});text(p['summary'],'影响确认',8000)
        if actor['id'] not in plan['required']:raise BoardError('非此影响确认人',403)
        if plan['status']!='proposed' or p['manifest_hash']!=plan['manifest_hash']:raise BoardError('回退已变化',409)
        fresh(plan,tasks,g,store,db);plan['confirmations'][actor['id']]={'summary':p['summary'],'at':now};return
    if action=='rollback_approve':
        manager(r);fields(p,{'id','manifest_hash','summary'},{'id','manifest_hash','summary'});text(p['summary'],'批准依据',8000)
        fresh(plan,tasks,g,store,db)
        if plan['status']!='proposed' or p['manifest_hash']!=plan['manifest_hash'] or not set(plan['required'])<=set(plan['confirmations']):raise BoardError('缺少当前影响确认',409)
        if any(other['id']!=plan['id'] and other['status'] not in ('proposed','failed','cancelled','applied') and set(other['affected_tasks'])&set(plan['affected_tasks']) for other in v['wf_rollbacks'].values()):raise BoardError('影响范围已有回退执行中',409)
        plan.update(status='approved',approved_by=actor['id'],approved_at=now);return
    if action=='rollback_cancel':
        manager(r);fields(p,{'id','summary'},{'id','summary'});text(p['summary'],'取消原因',4000)
        if plan['status']=='running':plan.update(cancel_requested=True,cancel_reason=p['summary']);return
        if plan['kind']=='deploy' and plan['status']=='prepared':raise BoardError('部署已实际切换；需验收或发起新的恢复单，不能以取消掩盖已发生操作',409)
        if plan['status'] not in ('proposed','approved','prepared'):raise BoardError('此状态不能取消',409)
        plan.update(status='cancelled',cancel_reason=p['summary']);return
    if action=='rollback_claim':
        fields(p,{'id','manifest_hash'},{'id','manifest_hash'});executor=v['wf_executors'].get(actor['id']);kind='code' if plan['commits'] else plan['kind'];target=plan['repo'] if plan['commits'] else plan['object']
        if r!='restorer' or not executor or not executor['enabled'] or kind not in executor['kinds'] or target not in executor['targets']:raise BoardError('执行器未获此项目/目标授权',403)
        if plan['status']!='approved' or p['manifest_hash']!=plan['manifest_hash']:raise BoardError('回退未批准或已有执行者；失联需SE核对进程后恢复',409)
        fresh(plan,tasks,g,store,db);plan.update(status='running',lease={'id':uuid.uuid4().hex,'actor':actor['id'],'expires':now+300},cancel_requested=False);return {'lease':plan['lease'],'plan':deepcopy(plan)}
    if action in ('rollback_heartbeat','rollback_finish'):
        lease=plan.get('lease')
        if r!='restorer' or not lease or lease['actor']!=actor['id'] or lease['id']!=p.get('lease') or plan['status']!='running' or lease['expires']<now:raise BoardError('无有效回退执行租约；禁止旧执行者成功回传',409)
        if action=='rollback_heartbeat':
            fields(p,{'id','lease'},{'id','lease'});lease['expires']=now+300;return {'cancel':plan['cancel_requested'],'expires':lease['expires']}
        keys={'id','lease','status','commit','evidence','artifacts','summary'};fields(p,keys,keys);text(p['summary'],'执行结果',8000);evidence(p['evidence'])
        if p['status'] not in ('prepared','failed','cancelled','needs_recovery'):raise BoardError('执行结果无效')
        if plan['cancel_requested'] and p['status']=='prepared':raise BoardError('取消后不得回传成功',409)
        from .git_reader import sha
        if p['commit']:sha(p['commit'])
        if p['status']=='prepared' and plan['commits'] and not p['commit']:raise BoardError('代码回退需真实候选提交')
        if type(p['artifacts']) is not list or len(p['artifacts'])>20:raise BoardError('产物超限')
        from .resources import pointer
        for a in p['artifacts']:
            fields(a,{'path','sha256','location'},{'path','sha256','location'});text(a['path'],'产物名',200);pointer(a['location'])
            if type(a['sha256']) is not str or not __import__('re').fullmatch('[0-9a-f]{64}',a['sha256']):raise BoardError('产物摘要无效')
        plan.update(status=p['status'],result={**deepcopy(p),'actor':actor['id'],'at':now});return
    if action=='rollback_recover':
        manager(r);fields(p,{'id','summary','evidence'},{'id','summary','evidence'});text(p['summary'],'进程和资源处置',8000);evidence(p['evidence'])
        if plan['status']!='needs_recovery' and (plan['status']!='running' or plan['lease']['expires']>=now):raise BoardError('仅过期租约或明确待恢复状态可经SE核对后结束',409)
        plan.update(status='failed',recovery={**deepcopy(p),'actor':actor['id'],'at':now});return
    if action=='rollback_apply':
        manager(r);keys={'id','manifest_hash','summary','runs','commit','evidence'};fields(p,keys,keys);text(p['summary'],'回退验收',8000);evidence(p['evidence'])
        if p['manifest_hash']!=plan['manifest_hash']:raise BoardError('回退摘要变化',409)
        if context(plan,tasks,g)!=plan['context']:raise BoardError('任务/模块范围已变，请重新预览回退',409)
        machine=bool(plan['commits']) or plan['kind']=='deploy'
        if plan['status']!=('prepared' if machine else 'approved'):raise BoardError('回退尚未完成必需执行步骤',409)
        if machine:
            if plan['commits']:
                rd,repo=reader(store,db,plan['repo']);candidate=plan['result']['commit'];rd.commit(candidate)
                if repo['refs'].get(plan['target_ref'])!=p['commit'] or not ancestry(rd,candidate,p['commit']):raise BoardError('候选尚未进入声明目标分支',409)
                # Unrelated later changes require tests on the exact final input.
                if not p['runs']:raise BoardError('回退最终提交需实际验证运行',409)
                identifiers(p['runs'],'验证运行')
                for id in plan['affected_tasks']:
                    relevant=[rid for rid in p['runs'] if id in v['runs'].get(rid,{}).get('scopes',{})]
                    if not relevant:raise BoardError('每个受影响任务都需精确最终输入验证',409)
                    run_refs(v,tasks[id],relevant,'git:'+p['commit'])
            elif p['commit']!=plan['result']['commit']:raise BoardError('部署结果提交不一致',409)
        events=[]
        if plan['kind']=='task':
            tid=plan['object'];spec=deepcopy(plan['restore_spec']);payload=store._validate(db,{**actor,'role':'reviewer'},tid,tasks[tid],'scope',{'spec':spec,'reason':'回退 '+plan['id']+'：'+p['summary']});events.append(store._append(db,{**actor,'role':'reviewer'},tid,'scope',payload))
        elif plan['kind']=='module':
            module=deepcopy(plan['restore_module']);module['version']='restore-'+plan['id'];events.append(append_governance(db,g,actor,'module_plan',module,store,'rollback-'+plan['id']))
        elif plan['kind']=='asset':
            consumption=store.registry.consumption().get(plan['object'])
            if not consumption or consumption['release']!=plan['target'] or consumption['sha256']!=plan['asset_sha256']:raise BoardError('先按固定消费流程切换到批准版本，再核验回退',409)
        for tid in plan['affected_tasks']:
            if plan['kind']=='task' and tid==plan['object']:continue
            t=tasks[tid];latest=t.get('latest_submission')
            if latest and latest.get('accepted') and t['status'] in ('accepted','merged','native_accepted','partial_accepted','partial_merged','partial_native'):
                payload={'submission':latest['id'],'reason':'回退 '+plan['id']+' 使当前成果需重新核定','findings':[{'description':'成果或依赖已回退：'+plan['id'],'acceptance':'形成新的受影响范围，核对依赖并重新验证'}]}
                payload=store._validate(db,{**actor,'role':'reviewer'},tid,t,'reopen',payload)
                events.append(store._append(db,{**actor,'role':'reviewer'},tid,'reopen',payload))
            else:events.append(store._append(db,{**actor,'role':'reviewer'},tid,'note',{'summary':'回退 '+plan['id']+' 已应用；当前范围需SE重新核定，原件与证据保留'}))
        plan.update(status='applied',applied={**deepcopy(p),'actor':actor['id'],'at':now,'events':events})
        return {'rollback':plan['id'],'events':events}
    raise BoardError('回退动作不存在',404)
