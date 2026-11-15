"""Task-local, revocable authority. Never changes a member's project role."""
from copy import deepcopy
import json,time
from .store import BoardError,fields,text,integer,digest
from .operations import manager,task_at
from .workflow import current,submission_anchor

ACTIONS={'delegation_grant','delegation_revoke'}
ALLOWED={'criteria_review','review_resolve','run_request','manual_run','accept','merge','native','request_changes'}
FINAL={'accept','merge','native','request_changes'}
def anchor(t):return submission_anchor(t) if t.get('latest_submission') else 'git:'+t['spec'].get('work',{}).get('baseline','')
def prepare(v):v.setdefault('dg_grants',{})
def context(v,t):return digest({'scope':t['scope_hash'],'version':t['scope_version'],'anchor':anchor(t),'criteria':v.get('wf_plan_heads',{}).get(t['spec']['id']),'test_plan':v.get('test_plans',{}).get(t['spec']['id'])})
def mutate(v,db,actor,r,action,p,now,g,ts):
    manager(r);prepare(v)
    if action=='delegation_revoke':
        fields(p,{'id','reason'},{'id','reason'});text(p['reason'],'撤销理由');row=v['dg_grants'].get(p['id'])
        if not row:raise BoardError('授权不存在',404)
        row['revoked']={'actor':actor['id'],'at':now,'reason':p['reason']};return
    keys={'id','task','scope','scope_version','input_anchor','grantee','actions','expires','reason'};fields(p,keys,keys)
    text(p['id'],'授权ID',100);text(p['reason'],'授权依据',4000);t=task_at(db,p)
    if p['id'] in v['dg_grants']:raise BoardError('授权ID已存在',409)
    if not current(p,t) or p['input_anchor']!=anchor(t):raise BoardError('授权需当前任务范围与成果锚点',409)
    if type(p['expires']) not in (int,float) or not now<p['expires']<=now+30*86400:raise BoardError('期限需未来30天内')
    if type(p['actions']) is not list or not p['actions'] or len(set(p['actions']))!=len(p['actions']) or not set(p['actions'])<=ALLOWED:raise BoardError('动作不在有界委派清单')
    from .governance import role
    row=db.execute('SELECT * FROM actors WHERE id=?',(text(p['grantee'],'受托者',100),)).fetchone()
    if not row or row['role']!='agent' or role(db,dict(row)) not in ('worker','agent','tester','researcher'):raise BoardError('受托者需本项目有效Worker身份',403)
    validate(v,db,t,p,p['grantee'],g)
    v['dg_grants'][p['id']]={**deepcopy(p),'context':context(v,t),'issuer':actor['id'],'created':now,'revoked':None};return {'delegation':p['id']}

def validate(v,db,t,grant,grantee,g):
    if t['owner']==grantee or db.execute("SELECT 1 FROM events WHERE task_id=? AND actor=? AND kind='submit' LIMIT 1",(t['spec']['id'],grantee)).fetchone():raise BoardError('实现者不能受托审核自己的任务',403)
    from .assurance import effective
    if effective(v,t,g)['level']=='strict' and set(grant['actions']) & FINAL:raise BoardError('严格任务最终验收/基线处置保留给SE或人类',403)

def authorize(db,actor,ref,action,ids):
    from .operations import load
    from .governance import load as gov,tasks,role
    if type(ref) is not str:raise BoardError('委派ID需字符串')
    v=load(db);grant=v.get('dg_grants',{}).get(ref)
    if not grant or grant['grantee']!=actor['id']:raise BoardError('没有本人的任务授权',403)
    if grant['revoked'] or grant['expires']<=time.time() or action not in grant['actions'] or ids!=[grant['task']]:raise BoardError('授权已失效或动作/任务越界',403)
    if role(db,actor) not in ('worker','agent','tester','researcher'):raise BoardError('当前身份不能使用Worker委派',403)
    g=gov(db);ts=tasks(db);t=ts[grant['task']]
    if not current(grant,t) or grant['input_anchor']!=anchor(t) or grant['context']!=context(v,t):raise BoardError('范围、成果或验证计划改变，授权已失效',409)
    validate(v,db,t,grant,actor['id'],g);return grant

def listing(store,actor):
    from .operations import load
    from .governance import role,MANAGERS,tasks
    with store.connection() as db:
        db.execute('BEGIN');v=load(db);ts=tasks(db);r=role(db,actor);rows=[]
        for grant in v.get('dg_grants',{}).values():
            if r not in MANAGERS and grant['grantee']!=actor['id']:continue
            t=ts[grant['task']];valid=not grant['revoked'] and grant['expires']>time.time() and current(grant,t) and grant['input_anchor']==anchor(t) and grant['context']==context(v,t)
            rows.append({**grant,'current':valid})
        eligible=[];grantees=[]
        if r in MANAGERS:
            from .assurance import effective
            from .governance import load as gov
            g=gov(db)
            eligible=[{'task':tid,'title':t['spec']['title'],'scope':t['scope_hash'],'scope_version':t['scope_version'],'input_anchor':anchor(t),'level':effective(v,t,g)['level']} for tid,t in ts.items() if t['spec'].get('work')]
            grantees=[x['id'] for x in db.execute("SELECT id,role FROM actors WHERE role='agent'") if role(db,dict(x)) in ('worker','agent','tester','researcher')]
        return {'grants':rows,'eligible':eligible,'grantees':grantees,'preparation':'研究、草案、材料与候选整理沿用普通Worker流程；发布范围和接口决定仍由SE确认','identity_is_not_model_independence':True}
