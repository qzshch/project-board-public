"""Typed, project-local prerequisite consumption over existing task events.

Knowledge/artifacts require reviewed results. Code also requires an actual
merge reachable from the consumer's fixed baseline, in an unambiguous project
mirror. Claim anchors live in the append-only event, preserving old projections.
"""
import json,re
from copy import deepcopy
from .store import BoardError,fields

KINDS={'code','knowledge','artifact'}
STAGES={'accepted':0,'merged':1,'native_accepted':2}

def validate(value,depends):
    if type(value) is not dict or not set(value)<=set(depends):raise BoardError('依赖要求必须对应本任务硬依赖')
    for dep,p in value.items():
        fields(p,{'kind','stage','repo'})
        if not p:raise BoardError('显式依赖要求不能为空')
        if 'kind' in p and (type(p['kind']) is not str or p['kind'] not in KINDS):raise BoardError('成果类型需code/knowledge/artifact')
        if 'stage' in p and (type(p['stage']) is not str or p['stage'] not in STAGES):raise BoardError('依赖阶段需accepted/merged/native_accepted')
        if 'repo' in p:
            from .git_tracking import repo_id
            repo_id(p['repo'])
    return deepcopy(value)

def requirement(consumer,producer):
    category=producer['spec'].get('work',{}).get('category')
    inferred='knowledge' if category in ('research','documentation') else 'artifact' if category in ('collection','generation') else 'code' if category in ('infrastructure','frontend','backend','library','test','integration','release') else 'unknown'
    p=consumer['spec'].get('dependency_requirements',{}).get(producer['spec']['id'],{})
    kind=p.get('kind',inferred);stage=p.get('stage','merged' if kind=='code' else 'accepted')
    if inferred=='code' and kind!='code':raise BoardError('不能把代码依赖降为知识或普通产物')
    if kind=='code' and stage=='accepted':raise BoardError('代码依赖至少要求合入')
    return {'kind':kind,'stage':stage,**({'repo':p['repo']} if p.get('repo') else {})}

def anchors(db,tid):
    row=db.execute("SELECT payload FROM events WHERE task_id=? AND kind IN ('claim','assign') AND seq>coalesce((SELECT max(seq) FROM events WHERE task_id=? AND kind='scope'),0) ORDER BY seq DESC LIMIT 1",(tid,tid)).fetchone()
    return json.loads(row['payload']).get('dependency_locks') if row else None

def resolve(db,t,registry,context=None,cache=None):
    from .governance import tasks,load as gov,DONE
    from .operations import load
    from .workflow import plan_for,reader,submission_anchor
    ts,g,v=context[:3] if context else (tasks(db),gov(db),load(db))
    cache={} if cache is None else cache;reasons=[];facts={}
    for dep in t['spec']['depends_on']:
        up=ts.get(dep)
        if not up:reasons.append('硬依赖不存在：'+dep);continue
        try:
            req=requirement(t,up);kind=req['kind'];stage=req['stage']
            if kind=='unknown':raise BoardError('成果类型未知，需SE核定')
            allowed=DONE if stage=='accepted' else {'merged','native_accepted','baseline_merged'} if stage=='merged' else {'native_accepted'}
            if up['status'] not in allowed:raise BoardError('尚未达到'+stage)
            sub=up.get('latest_submission')
            if not sub or not sub.get('accepted'):raise BoardError('缺少当前范围已审核的成果锚点')
            anchor=submission_anchor(up)
            if not anchor:raise BoardError('成果版本未知')
            fact={**req,'scope':up['scope_hash'],'scope_version':up['scope_version'],'submission':sub['id'],'input_anchor':anchor}
            if kind=='code' or stage!='accepted':
                merged=up.get('last_merge') or {}
                if merged.get('submission')!=sub['id'] or not re.fullmatch('[0-9a-f]{40}',str(merged.get('commit',''))):raise BoardError('缺少本次成果的合入锚点')
                fact['merge_commit']=merged['commit']
                if stage=='native_accepted' and (up.get('native') or {}).get('commit')!=merged['commit']:raise BoardError('运行验收与合入基线不一致')
            if kind=='code':
                if not registry:raise BoardError('需项目只读Git接入以核验消费基线')
                store=registry.hub.store(registry.project)
                from .git_tracking import load as git_load
                if 'repos' not in cache:cache['repos']=git_load(db)['repos']
                repos=cache['repos'];cp=plan_for(v,t);pp=plan_for(v,up);cr=(cp or {}).get('repo','');pr=(pp or {}).get('repo','')
                if cr and pr and cr!=pr:raise BoardError('不同仓库的成果请用已固定资产消费，不混用祖先关系')
                names=[rid for rid,r in repos.items() if r['enabled']];repo=req.get('repo') or cr or pr or (names[0] if len(names)==1 else '')
                if not repo:raise BoardError('代码依赖需明确且唯一的只读仓库')
                if (cr and cr!=repo) or (pr and pr!=repo):raise BoardError('依赖仓库与已批准验证计划不符')
                baseline=t['spec'].get('work',{}).get('baseline','');implementation=sub.get('implementation_commit','');key=(repo,implementation,fact['merge_commit'],baseline)
                if key not in cache:
                    try:
                        rd,_=reader(store,db,repo)
                        # Verify all three actual commit objects in one batch.
                        # Keep cache local to this transaction/read snapshot.
                        rd.commits(list(dict.fromkeys((implementation,fact['merge_commit'],baseline))))
                        if rd.git(['rev-list','--max-count=1',implementation,'--not',fact['merge_commit']]).strip() or rd.git(['rev-list','--max-count=1',fact['merge_commit'],'--not',baseline]).strip():raise BoardError('下游固定基线未包含已审核合入成果')
                        cache[key]=None
                    except BoardError as error:cache[key]=str(error)
                if cache[key]:raise BoardError(cache[key])
                fact['repo']=repo;fact['consumer_baseline']=baseline
            # A dependency with unresolved review/rollback cannot be consumed.
            from .workflow import blockers
            pending=blockers(v,up,'accept',anchor)
            if pending:raise BoardError('前置成果仍有未决审核或回退：'+'；'.join(pending))
            facts[dep]=fact
        except BoardError as error:reasons.append('依赖 '+dep+'：'+str(error))
    return list(dict.fromkeys(reasons)),facts

def claim(db,t,registry,cache=None):
    reasons,facts=resolve(db,t,registry,cache=cache)
    if reasons:raise BoardError('；'.join(reasons),409)
    old=anchors(db,t['spec']['id'])
    if old is not None and old!=facts:raise BoardError('已领取的依赖成果改变，需SE追加范围后重新领取',409)
    return facts

def review(db,t,registry,context=None,cache=None):
    reasons,facts=resolve(db,t,registry,context,cache);old=anchors(db,t['spec']['id'])
    if old is not None:
        for dep in t['spec']['depends_on']:
            if dep in facts and old.get(dep)!=facts[dep]:reasons.append('领取后的消费锚点已改变：'+dep)
    return list(dict.fromkeys(reasons))
