"""Curated assets must trace to accepted work and actual validated bytes."""
from copy import deepcopy
import re
from .store import BoardError,fields,text,identifiers,evidence,digest,canonical
from .operations import manager
from .planning import ref_of

KINDS={'skill','methodology','infrastructure','test_case','test_data','test_tool','private'}


def mutate(v,db,actor,r,action,p,now,g,tasks):
    if action=='asset_feedback':
        fields(p,{'asset','task','scope','outcome','integration_minutes','estimated_saved_minutes','issues'},{'asset','task','scope','outcome','integration_minutes','estimated_saved_minutes','issues'})
        from .operations import task_at
        task=task_at(db,p)
        if task['status']=='planned':raise BoardError('消费反馈需已开始执行的实际任务',409)
        if r not in ('owner','se','reviewer','tester') and task['owner']!=actor['id']:raise BoardError('只能反馈本人的消费任务',403)
        w=task['spec'].get('work',{})
        if p['asset'] not in w.get('assets',[]) or p['asset'] not in w.get('asset_locks',{}):raise BoardError('反馈必须对应任务实际固定消费',409)
        if p['outcome'] not in ('succeeded','failed'):raise BoardError('消费结果无效')
        from .timing import number
        number(p['integration_minutes'],'实测接入分钟')
        if p['estimated_saved_minutes'] is not None:number(p['estimated_saved_minutes'],'预估节省分钟')
        text(p['issues'],'反馈及维护问题',8000)
        v['usage'].append({**deepcopy(p),'lock':w['asset_locks'][p['asset']],'actor':actor['id'],'at':now});return
    if action=='candidate':
        keys={'id','version','title','kind','source_tasks','source_scopes','problem','applicability','exclusions','dependencies','owner'};fields(p,keys,keys);ref=ref_of(p)
        if ref in v['candidates']:raise BoardError('候选版本不可覆盖',409)
        if p['kind'] not in KINDS:raise BoardError('资产类型无效')
        identifiers(p['source_tasks'],'来源任务');identifiers(p['dependencies'],'依赖')
        if not p['source_tasks'] or not set(p['source_tasks'])<=set(tasks):raise BoardError('需本项目来源任务',409)
        if p['source_scopes']!={t:tasks[t]['scope_hash'] for t in p['source_tasks']}:raise BoardError('资产来源范围已变化',409)
        if r not in ('owner','se','reviewer') and any(tasks[t]['owner']!=actor['id'] for t in p['source_tasks']):raise BoardError('只能提议本人交付的候选资产',403)
        if p['owner']!='root' and p['owner'] not in g['members']:raise BoardError('维护者需本项目成员',409)
        for k in ('title','problem','applicability','exclusions','owner'):text(p[k],k,8000)
        v['candidates'][ref]={**deepcopy(p),'source_versions':{t:tasks[t]['scope_version'] for t in p['source_tasks']},'stage':'candidate','history':[{'action':'candidate','actor':actor['id'],'at':now}],'validation_runs':[]};v['candidate_heads'][p['id']]=ref;return {'candidate':ref}
    manager(r);text(p.get('ref'),'候选版本',180);c=v['candidates'].get(p['ref'])
    if not c:raise BoardError('候选版本不存在',404)
    if action=='candidate_retire':
        fields(p,{'ref','reason'},{'ref','reason'});text(p['reason'],'弃用依据');c['stage']='retired'
    elif action=='candidate_refine':
        keys={'ref','input_anchor','artifact_path','sha256','license','sensitivity','location','shareable','summary'};fields(p,keys,keys)
        if c['stage']!='candidate':raise BoardError('仅候选阶段可提炼；修改已验证内容需新版本',409)
        from .quality import anchor
        anchor(p['input_anchor'])
        if not re.fullmatch('[0-9a-f]{64}',str(p['sha256'])) or type(p['shareable']) is not bool or p['sensitivity'] not in ('public','private','secret'):raise BoardError('资产需SHA、明确敏感性与共享资格')
        for k in ('artifact_path','license','location','summary'):text(p[k],k,4000)
        c.update({k:deepcopy(p[k]) for k in keys-{'ref'}},stage='refined')
    elif action=='candidate_validate':
        fields(p,{'ref','runs','summary'},{'ref','runs','summary'});identifiers(p['runs'],'验证运行');text(p['summary'],'实际复用验证结论',8000)
        if c['stage']!='refined' or not p['runs']:raise BoardError('先提炼并提供实际验证运行',409)
        if any(tasks[t]['scope_hash']!=s or tasks[t]['scope_version']!=c['source_versions'][t] or tasks[t]['status'] not in ('accepted','merged','native_accepted','baseline_merged') for t,s in c['source_scopes'].items()):raise BoardError('来源范围需保持一致并已验收',409)
        found=False
        for rid in p['runs']:
            run=v['runs'].get(rid)
            if not run or run['status']!='passed' or run['input_anchor']!=c['input_anchor']:raise BoardError('验证未通过或输入不匹配',409)
            if any(v['case_status'][r['case']]['status']=='withdrawn' for r in run['results']):raise BoardError('验证用例已撤回',409)
            if c['shareable'] and not run.get('suite'):raise BoardError('可共享版本的字节与用例须经批准执行器实际核验',409)
            if not set(c['source_tasks'])<=set(run['scopes']) or any(run['scopes'][t]!=s or run['scope_versions'][t]!=c['source_versions'][t] for t,s in c['source_scopes'].items()):raise BoardError('运行未覆盖候选来源范围',409)
            found |= any(a['path']==c['artifact_path'] and a['sha256']==c['sha256'] and a['location']==c['location'] for a in run['artifacts'])
        if not found:raise BoardError('运行未核验提炼产物的真实SHA',409)
        c.update(stage='validated',validation_runs=deepcopy(p['runs']))
    elif action=='candidate_promote':
        fields(p,{'ref','summary','evidence'},{'ref','summary','evidence'});text(p['summary'],'登记依据');evidence(p['evidence'])
        if c['stage']!='validated':raise BoardError('需先验证提炼资产',409)
        if any(tasks[t]['scope_hash']!=s or tasks[t]['scope_version']!=c['source_versions'][t] or tasks[t]['status'] not in ('accepted','merged','native_accepted','baseline_merged') for t,s in c['source_scopes'].items()):raise BoardError('来源已返修或变更，重新核验',409)
        asset={k:c[k] for k in ('id','version','kind','license','sensitivity','sha256','location','owner','shareable')}
        asset.update(source='candidate:'+p['ref'],evidence=p['evidence'])
        from .governance import Governance,load
        value=load(db);revision=value.pop('revision');previous=value.pop('head')
        Governance(None)._mutate(db,value,actor,r,'asset',asset)
        request={'request_id':'candidate-'+p['ref'],'expected_revision':revision,'action':'asset','payload':asset}
        event={'action':'asset','payload':asset,'state':value,'at':now}
        h=digest({'seq':revision+1,'actor':actor['id'],'request_id':request['request_id'],'event':event,'previous':previous})
        db.execute('INSERT INTO governance_events VALUES(?,?,?,?,?,?,?)',(revision+1,actor['id'],request['request_id'],digest(request),canonical(event),previous,h));c.update(stage='promoted',asset=p['ref'])
    else:raise BoardError('未知候选动作',404)
    c['history'].append({'action':action,'payload':deepcopy(p),'actor':actor['id'],'at':now})


def publication_guard(db,ref):
    from .operations import load
    v=load(db)
    if not v['policy']['enabled']:return
    candidates=[c for c in v['candidates'].values() if c.get('asset')==ref and c['stage']=='promoted']
    if not candidates:raise BoardError('启用治理后，共享资产需经过提炼与实际验证',409)
    from .governance import tasks
    all_tasks=tasks(db)
    for candidate in candidates:
        if any(all_tasks[t]['scope_version']!=candidate['source_versions'][t] or all_tasks[t]['scope_hash']!=scope or all_tasks[t]['status'] not in ('accepted','merged','native_accepted','baseline_merged') for t,scope in candidate['source_scopes'].items()):raise BoardError('候选来源已变化，发布前重新核验',409)
        if any(v['case_status'][r['case']]['status']=='withdrawn' for rid in candidate['validation_runs'] for r in v['runs'][rid]['results']):raise BoardError('资产验证用例已撤回',409)
