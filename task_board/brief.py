"""Credential-free, project-specific delegation packet generator."""
from .governance import Governance
from .store import BoardError

def build_brief(store, task_id, project, url, actor=None, operator=False):
    task=store.get(task_id);spec=task['spec'];w=spec.get('work')
    if not w:raise BoardError('历史任务包尚未核定原子输入，不能自动派发',409)
    g=Governance(store).snapshot(actor=actor,operator=operator)
    from .operations import Operations
    op=Operations(store).snapshot(actor)
    from .git_tracking import Tracking
    git=Tracking(store).state()
    from .resources import Directory
    resources=Directory(store).listing(actor,operator,brief_task=task_id)
    from .workflow import snapshot as workflow_snapshot
    workflow=workflow_snapshot(store,actor or {'id':'','role':'agent'},task_id)
    from .focus import delivery_path
    snapshots={loc['location'] for e in g.get('resource_entries',{}).values() if e.get('information_role')=='snapshot' for loc in e['locations']}
    pinned=set(g['modules'].get(w.get('planning',{}).get('module'),{}).get('knowledge_refs',[]))
    current_materials=[];historical_materials=[]
    for item in g['knowledge'].get('materials',[]):
        row={**item,'information_role':'snapshot' if item['location'] in snapshots else 'reference'}
        explicit=item['location'] in pinned or any(x==item['location'] or x.startswith(item['location']+'@') for x in w['inputs'])
        (historical_materials if row['information_role']=='snapshot' and not explicit else current_materials).append(row)
    from .coordination import snapshot as coordination_snapshot
    coordination=coordination_snapshot(store,actor or {'id':'','role':'agent'},task_id)
    assets={}
    for ref in w['assets']:
        lock=w.get('asset_locks',{}).get(ref)
        if not lock:assets[ref]={'status':'legacy_pin_unknown','instruction':'SE must verify the historical dispatched version before new work'}
        elif lock['shared']:assets[ref]={**store.registry.get(lock['release'],project,True),'lock':lock}
        else:assets[ref]={**g['assets'][lock['release']],'lock':lock}
    return {'project_id':project,'api_base':url+'/api/projects/'+project,'task_id':task_id,
            'authority':{'current_endpoint':url+'/api/projects/'+project+'/current','instruction':'以实时任务、当前候选、验收及合入记录为准；项目文档与轮次报告是参考，不要求每轮手工同步状态副本。'},
            'delivery_path':delivery_path(task,op['effective'][task_id],workflow['current_plan']),
            'role':w['role'],'scope_version':task['scope_version'],'scope_hash':task['scope_hash'],
            'collaboration':{k:workflow[k] for k in ('threads','current_plan','findings','blockers','rollbacks','delivery_readiness')},
            'continuation':{k:coordination[k] for k in ('resume','plans','batches','gates','intakes','cursor')},
            'context_pack':{'endpoint':url+'/api/projects/'+project+'/convergence/context?task='+__import__('urllib.parse',fromlist=['quote']).quote(task_id,safe=''),'instruction':'按实际引用裁剪材料；摘要保留来源与哈希，变化继续按游标分页读取'},
            'execution_records':{'attempts':[{k:e.get(k) for k in ('id','actor','workspace','status','scope','scope_version','baseline','result')} for e in op.get('cv_attempts',{}).values() if e['task']==task_id],
                                 'sessions':[{k:e.get(k) for k in ('id','attempt','session','tool','model','machine','previous','checkpoint')} for e in op.get('cv_sessions',{}).values() if e['task']==task_id]},
            'baseline':w['baseline'],'read_materials':current_materials,'historical_materials':historical_materials,'project_entries':g['knowledge'].get('entries',[]),
            'git':{'repositories':[{k:r.get(k) for k in ('id','repository','title','synced_at')} for r in git['repos'].values() if r['enabled']],
                   'local_storage_policy':git['policy'],'instruction':'仅审核纳入的源码/说明/测试代码进Git；资料和运行产物留本地/NAS；此接入不执行add/commit/push'},
            'constraints':g['knowledge'].get('constraints','待SE填写'),
            'allowed_paths':spec['allowed_paths'],'inputs':w['inputs'],'outputs':w['outputs'],
            'contracts':{ref:g['contracts'].get(ref) for ref in w['contracts']},
            'planning_policy':g['planning_policy'],
            'assurance':op['effective'][task_id],
            'test_plan':op['test_plans'].get(task_id),
            'estimate':op['estimates'].get(task_id,[]),
            'suggested_cases':op['suggested_cases'].get(task_id,[]),
            'resource_directory':{'endpoint':url+'/api/projects/'+project+'/resources','entries':resources['entries'],'total':resources['total'],'next':resources['next'],
                                  'instruction':'资源位置、版本与登记摘要供接手核对；原件留本地/NAS，读取仍需项目范围文件权限。历史范围运行记录不能替代当前验证。'},
            'planning':w.get('planning'),
            'module_plan':g['modules'].get(w.get('planning',{}).get('module')),
            'module_readiness':g['module_readiness'].get(w.get('planning',{}).get('module')),
            'planning_decisions':{ref:g['planning_decisions'][ref] for ref in g['modules'].get(w.get('planning',{}).get('module'),{}).get('decisions',[])},
            'assets':assets,'asset_locks':w.get('asset_locks',{}),
            'exclusive_resources':w['resources'],'couplings':w['couplings'],'acceptance':w['acceptance'],
            'instruction':'Worker按/help/worker-start自行加入开放的本项目；已有身份复用；禁止取得全局管理密钥。读取任务最新revision后prepare claim并post。只在允许目录实现，公共修改先scope_proposal，由SE走接口影响提案。提交冻结Git40位提交、来源SHA、证据SHA、测试及剩余范围；保存服务回执。返修必须引用open finding ID，重提不会自动关闭，审核通过后关闭。合并/运行验收/归档由SE分别记录。凭据不进Git。API权限不替代OS文件隔离。',
            'receipt_path':'<本项目证据目录>/<task_id>/receipt.json','findings':task['findings']}
