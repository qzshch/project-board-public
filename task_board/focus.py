"""Current-state projections over existing journals, never another status store."""
from collections import Counter
from .finishing import TERMINAL


def task_view(t):
    """Keep active legacy work visible; structure is not an executable backlog."""
    if t['status'] in TERMINAL:return 'completed'
    if t['spec']['kind']=='atomic' or t['status'] in ('active','submitted','changes_requested'):
        return 'current'
    return 'structure'


def delivery_path(t,assurance,plan):
    return {'steps':['claim','work','submit','se_review'],
            'candidate_first':True,'level':assurance['level'],
            'criteria_plan':plan['id'] if plan else None,
            'instruction':'先提交候选，不等待SE预审。一次提供成果、工作记录、结论、证据、验证和剩余项；同一原件引用位置与SHA，不另写多份状态。验收仍核对当前范围、逐项声明、实际运行和未决发现；严格任务保留原门禁。'}


def groups(items):
    """One task entry, retaining every finding and required action beneath it."""
    result={};notifications=[]
    for e in items:
        if e['kind']=='thread' and e['status']=='resolved':
            notifications.append(e);continue
        key=e.get('task') or e['kind']+':'+e['id']
        row=result.setdefault(key,{'id':key,'task':e.get('task',''),'items':[], 'roles':[]})
        role='worker' if e['kind']=='thread' and e['status']=='awaiting_worker' else 'se' if e['kind'] in ('submission','criterion','finding','implementation','draft','rule','milestone','recovery','intake','condition','template','candidate') else 'collaborators'
        row['items'].append({**e,'next_role':role})
        if role not in row['roles']:row['roles'].append(role)
    return {'action_groups':list(result.values()),'notifications':notifications}


def snapshot(store,actor):
    from .governance import tasks,load as governance_load
    from .operations import load as operations_load
    from .git_tracking import load as git_load
    with store.connection() as db:
        db.execute('BEGIN');ts=tasks(db);g=governance_load(db);o=operations_load(db);git=git_load(db)
        head=db.execute('SELECT seq,hash FROM events ORDER BY seq DESC LIMIT 1').fetchone()
    rows=[{'id':tid,'title':t['spec']['title'],'status':t['status'],'view':task_view(t),'owner':t['owner'],
           'scope_version':t['scope_version'],'scope_hash':t['scope_hash'],
           'candidate':(t.get('latest_submission') or {}).get('id'),
           'implementation':(t.get('latest_submission') or {}).get('implementation_commit'),
           'merge':t.get('last_merge'),'native':t.get('native')} for tid,t in ts.items()]
    return {'schema':1,'project_id':store.registry.project,'authority':'project_journals',
            'heads':{'tasks':dict(head) if head else {'seq':0,'hash':'0'*64},'governance':g['head'],'operations':o['head'],'git':git['head']},
            'counts':dict(Counter(row['view'] for row in rows)),'tasks':rows,
            'repositories':[{k:r.get(k) for k in ('id','repository','synced_at','sync_error','default_branch','refs')} for r in git['repos'].values() if r['enabled']],
            'open_findings':sum(f['status'] not in ('fixed','dismissed') for f in o.get('wf_findings',{}).values()),
            'instruction':'当前范围、候选、验收和合入以本项目实时记录为准。材料、轮次报告和交接文档保留为参考或历史快照，不覆盖实时状态。'}
