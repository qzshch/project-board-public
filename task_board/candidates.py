"""Candidate collection is not acceptance or a platform test attestation."""
from .store import BoardError,fields,text,identifiers

def references(v,t,p):
    if 'verification' in p:
        q=p['verification'];fields(q,{'method','summary','reason','status'},{'method','summary','reason'})
        if q['method'] not in ('inspection','manual','automated','not_applicable'):raise BoardError('验证方式无效')
        for k in ('summary','reason'):text(q[k],k,8000)
        if q.get('status','unknown') not in ('passed','failed','not_run','not_applicable','unknown'):raise BoardError('本机验证状态无效')
    ids=p.get('test_runs',[]);identifiers(ids,'验证运行')
    anchor='git:'+p['implementation_commit'] if p.get('implementation_commit') else 'sha256:'+p.get('artifact',{}).get('sha256','')
    for rid in ids:
        run=v['runs'].get(rid)
        if not run:raise BoardError('本项目运行不存在',404)
        artifact=p.get('artifact',{})
        match=bool(artifact and any(a['sha256']==artifact.get('sha256') and artifact.get('ref') in (a['path'],a['location']) for a in run.get('artifacts',[])))
        if run['scopes'].get(t['spec']['id'])!=t['scope_hash'] or run.get('scope_versions',{}).get(t['spec']['id'])!=t['scope_version'] or (run['input_anchor']!=anchor and not match):raise BoardError('候选引用的运行不属于当前范围和输入',409)

def readiness(store,db,t):
    from .operations import load
    from .governance import load as gov
    from .workflow import blockers,submission_anchor
    from .assurance import validation
    from .coordination import enforce as co_enforce
    from .convergence import enforce as cv_enforce
    from .dependencies import review,anchors
    v=load(db);g=gov(db);sub=t.get('latest_submission');reasons=[]
    if sub:
        reasons+=blockers(v,t,'accept',submission_anchor(t))
        for check in (lambda:validation(db,t,sub,g,registry=getattr(store,'registry',None)),lambda:co_enforce(db,t,'accept',{},getattr(store,'registry',None)),lambda:cv_enforce(store,db,t,'accept',{}, {'id':t['owner'],'role':'agent'})):
            try:check()
            except BoardError as error:reasons.append(str(error))
        reasons+=review(db,t,getattr(store,'registry',None))
    return {'candidate_received':bool(sub),'ready_for_acceptance':bool(sub) and not reasons,'blockers':list(dict.fromkeys(reasons)),
            'verification_origin':'platform_run_reference' if (sub or {}).get('test_runs') else 'worker_statement',
            'dependency_lock_state':'recorded' if anchors(db,t['spec']['id']) is not None else 'unknown_legacy',
            'meaning':'候选已登记不等于验收；当前准备度不授予审核权限，也不代替SE读取原件'}
