"""Versioned project planning. All mutations share the governance transaction.

Approval fingerprints include the evidence-producing task revisions, so reopening
research or replacing a contract invalidates readiness without rewriting history.
Module containment is deliberately separate from execution prerequisites.
"""
from copy import deepcopy
import re
import time

from .store import BoardError, fields, text, identifiers, evidence, digest

DONE = {'accepted', 'merged', 'native_accepted', 'baseline_merged'}
PLANNING = {'research', 'collection', 'documentation'}


def prepare(v):
    for key in ('modules', 'module_heads', 'planning_decisions', 'milestone_plans', 'milestone_heads'):
        v.setdefault(key, {})
    v.setdefault('planning_policy', {'mode': 'legacy', 'reason': '升级前项目，待负责人显式启用规划门禁'})


def ref_of(p):
    for key in ('id', 'version'):
        if not isinstance(p.get(key), str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,79}', p[key]):
            raise BoardError('规划ID/版本需1～80位字母数字或 . _ / -')
    return p['id'] + '@' + p['version']


def charter_blockers(v):
    k = v.get('knowledge', {})
    out = ['项目上下文未填写：' + key for key in ('background', 'goals', 'non_goals', 'constraints') if not k.get(key)]
    if not k.get('materials') and not k.get('history_notes','').strip():out.append('需历史材料或无历史材料说明')
    if not k.get('entries') and not k.get('resource_notes','').strip():out.append('需资源入口或资源准备说明')
    return out


def task_refs(p, all_tasks, key):
    identifiers(p[key], key)
    if not set(p[key]) <= set(all_tasks):raise BoardError(key + '包含不存在的本项目任务', 409)


def task_state(all_tasks, refs):
    return {r: {'revision': all_tasks[r]['revision'], 'scope': all_tasks[r]['scope_hash'], 'status': all_tasks[r]['status']} for r in refs if r in all_tasks}


def module_check(v, all_tasks, ref, visiting=None):
    m = v['modules'].get(ref)
    if not m:return {'ready': False, 'blockers': ['模块版本不存在：' + ref], 'scope': ''}
    visiting = set(visiting or ())
    if ref in visiting:return {'ready': False, 'blockers': ['模块规划依赖成环'], 'scope': ''}
    visiting.add(ref)
    out = charter_blockers(v)
    if m['stage'] != 'design':out.append('先形成design方案版本再评审')
    if m['unknowns']:out.append('模块仍有待澄清项')
    decisions = {r: v['planning_decisions'].get(r) for r in m['decisions']}
    covered = set()
    for d in decisions.values():
        if d:covered.update(d['research_tasks'])
    for tid in m['planning_tasks']:
        t = all_tasks.get(tid)
        if not t or t['status'] not in DONE:out.append('规划前置未验收：' + tid)
        if tid not in covered:out.append('规划前置尚无已确认结论：' + tid)
    for r, d in decisions.items():
        if not d:out.append('规划决策不存在：' + r)
        elif d['research_scope'] != task_state(all_tasks, d['research_tasks']):out.append('研究结论来源已变化：' + r)
    contracts = {r: v['contracts'].get(r) for r in m['interfaces']}
    for r, c in contracts.items():
        if not c or c['status'] != 'frozen':out.append('模块接口未冻结：' + r)
        elif m['id'] not in c['producers'] + c['consumers']:out.append('接口未登记该模块为生产/消费方：' + r)
    if not m['interfaces'] and not m['no_interface_reason'].strip():out.append('需声明公共接口或说明无共享接口的依据')
    boundaries = {}
    for other_ref in v['module_heads'].values():
        other = v['modules'][other_ref]
        if other['id'] == m['id']:continue
        products = sorted((set(m['outputs']) & set(other['inputs'])) | (set(m['inputs']) & set(other['outputs'])))
        if not products:continue
        common = set(m['interfaces']) & set(other['interfaces'])
        frozen = [r for r in sorted(common) if v['contracts'].get(r,{}).get('status')=='frozen' and {m['id'],other['id']} <= set(v['contracts'][r]['producers']+v['contracts'][r]['consumers'])]
        boundaries[other_ref] = {'products': products, 'interfaces': frozen}
        if not frozen:out.append('跨模块产物边界缺少双方冻结接口：'+other_ref)
    deps = {r: module_check(v, all_tasks, r, visiting) for r in m['depends_on']}
    for r, check in deps.items():
        if not check['ready']:out.append('规划依赖模块未就绪：' + r)
    scope = digest({'plan': {k: val for k, val in m.items() if k != 'reviews'}, 'knowledge': v.get('knowledge', {}),
                    'research': task_state(all_tasks, m['planning_tasks']), 'decisions': decisions, 'contracts': contracts,
                    'boundaries': boundaries, 'dependencies': {r: {'scope': c['scope'], 'ready': c['ready']} for r, c in deps.items()}})
    last = m['reviews'][-1] if m['reviews'] else None
    approved = bool(last and last['result'] == 'approve' and last['scope'] == scope)
    return {'ready': not out and approved, 'blockers': sorted(set(out)), 'scope': scope, 'review_current': approved}


def task_blockers(v, all_tasks, spec):
    prepare(v)
    w = spec.get('work', {}); binding = w.get('planning')
    if not binding and v['planning_policy']['mode'] != 'enforced':return []
    out = charter_blockers(v)
    if not w:return out + ['规划门禁要求原子任务及模块绑定']
    if not binding:return out + ['任务尚未绑定模块规划版本']
    m = v['modules'].get(binding['module'])
    if not m:return out + ['任务模块版本不存在']
    if binding['purpose'] == 'planning':
        if w['category'] not in PLANNING:out.append('规划任务仅允许调研、采集或文档工作')
        if not binding['question'].strip():out.append('规划任务需写明待解决问题')
    else:
        check = module_check(v, all_tasks, binding['module'])
        out += check['blockers']
        if not check['review_current']:out.append('模块当前范围尚未通过规划评审')
        if v['module_heads'].get(m['id']) != binding['module']:out.append('模块已有新规划版本，需SE显式迁移任务范围')
        if not set(m['interfaces']) <= set(w['contracts']):out.append('任务遗漏模块冻结接口')
    if not w['contracts'] and not binding['no_interface_reason'].strip():out.append('任务需说明无共享接口的依据')
    for ref in w['contracts']:
        c = v['contracts'].get(ref)
        if c and not {m['id'], spec['id']} & set(c['producers'] + c['consumers']):out.append('接口未覆盖该任务/模块：' + ref)
    return sorted(set(out))


def milestone_check(v, all_tasks, ref):
    m = v['milestone_plans'][ref];out = charter_blockers(v)
    modules = {r: module_check(v, all_tasks, r) for r in m['modules']}
    for r, c in modules.items():
        if not c['ready']:out.append('关联模块尚未就绪：' + r)
    for tid in m['tasks']:
        if all_tasks[tid]['status'] not in DONE:out.append('阶段交付未验收：' + tid)
        if all_tasks[tid]['spec'].get('work',{}).get('planning',{}).get('module') not in m['modules']:out.append('阶段任务已迁出关联模块：'+tid)
    scope = digest({'plan': {k: val for k, val in m.items() if k != 'reviews'},
                    'tasks': task_state(all_tasks, m['tasks']), 'modules': modules})
    review = m['reviews'][-1] if m['reviews'] else None
    return {'scope': scope, 'blockers': out, 'passed': bool(not out and review and review['result'] == 'pass' and review['scope'] == scope)}


def mutate(v, all_tasks, actor, action, p):
    prepare(v)
    if action == 'planning_enable':
        fields(p, {'reason'}, {'reason'});text(p['reason'], '启用依据')
        v['planning_policy'] = {'mode': 'enforced', **p}
    elif action == 'planning_decision':
        fields(p, {'id','question','conclusion','research_tasks','evidence'}, {'id','question','conclusion','research_tasks','evidence'})
        for k in ('id','question','conclusion'):text(p[k], k, 8000)
        task_refs(p, all_tasks, 'research_tasks');evidence(p['evidence'])
        if not p['research_tasks']:raise BoardError('研究决策需引用实际研究任务')
        if p['id'] in v['planning_decisions']:raise BoardError('决策不可覆盖，新增决策ID', 409)
        if any(all_tasks[t]['status'] not in DONE or all_tasks[t]['spec'].get('work',{}).get('category') not in PLANNING for t in p['research_tasks']):raise BoardError('研究决策来源需已验收的研究/采集/文档任务',409)
        v['planning_decisions'][p['id']] = {**deepcopy(p), 'research_scope': task_state(all_tasks,p['research_tasks']), 'actor': actor['id']}
    elif action == 'module_plan':
        keys = {'id','version','title','parent','goal','scope','non_goals','owner','path','inputs','outputs','interfaces','no_interface_reason','risks','unknowns','planning_tasks','decisions','depends_on','acceptance','stage','evidence'}
        fields(p, keys, keys);ref = ref_of(p)
        if ref in v['modules']:raise BoardError('模块版本不可覆盖',409)
        for k in ('title','goal','scope','non_goals','owner','path','risks','acceptance'):text(p[k], k, 8000)
        for k in ('parent','no_interface_reason'):
            if not isinstance(p[k],str) or len(p[k])>8000:raise BoardError(k+'需有界字符串')
        for k in ('inputs','outputs','interfaces','unknowns','planning_tasks','decisions','depends_on'):
            identifiers(p[k], k)
            for item in p[k]:text(item,k,180)
        if p['stage'] not in ('draft','research','design'):raise BoardError('规划阶段需draft/research/design；就绪必须评审')
        if p['owner'] != 'root' and p['owner'] not in v['members']:raise BoardError('模块负责人需本项目成员',409)
        task_refs(p, all_tasks, 'planning_tasks')
        if not set(p['decisions']) <= set(v['planning_decisions']):raise BoardError('规划决策不存在',409)
        if not set(p['depends_on']) <= set(v['modules']):raise BoardError('规划依赖模块版本不存在',409)
        if p['evidence'] != []:evidence(p['evidence'])
        parent = p['parent'];seen = {p['id']}
        while parent:
            if parent in seen:raise BoardError('模块包含关系成环',409)
            seen.add(parent)
            if parent not in v['module_heads']:raise BoardError('父模块不存在',409)
            parent = v['modules'][v['module_heads'][parent]]['parent']
        v['modules'][ref] = {**deepcopy(p), 'reviews': []};v['module_heads'][p['id']] = ref
    elif action == 'milestone_plan':
        keys = {'id','version','goal','path','entry','modules','tasks','acceptance','method','threshold','environment','reviewer','due','risks'}
        fields(p, keys, keys);ref = ref_of(p)
        if ref in v['milestone_plans']:raise BoardError('里程碑规划版本不可覆盖',409)
        for k in keys-{'modules','tasks','id','version'}:text(p[k], k, 8000)
        identifiers(p['modules'],'模块版本');task_refs(p,all_tasks,'tasks')
        if not p['modules'] or not p['tasks']:raise BoardError('里程碑需关联模块版本和实际交付任务')
        if not set(p['modules']) <= set(v['modules']):raise BoardError('里程碑模块不存在',409)
        if p['reviewer'] != 'root' and v['members'].get(p['reviewer'],{}).get('role') not in ('owner','se'):raise BoardError('验收负责人需本项目owner/SE',409)
        if any(not all_tasks[t]['spec'].get('work',{}).get('planning') or all_tasks[t]['spec']['work']['planning']['module'] not in p['modules'] for t in p['tasks']):raise BoardError('里程碑任务必须绑定关联模块版本',409)
        v['milestone_plans'][ref] = {**deepcopy(p),'reviews': []};v['milestone_heads'][p['id']] = ref
    elif action in ('module_review','milestone_review'):
        fields(p, {'ref','scope','result','summary','evidence'}, {'ref','scope','result','summary','evidence'})
        collection = v['modules'] if action == 'module_review' else v['milestone_plans']
        if p['ref'] not in collection:raise BoardError('评审版本不存在',404)
        m = collection[p['ref']]
        if action == 'milestone_review' and actor['id'] != m['reviewer']:raise BoardError('仅指定阶段验收负责人可评审',403)
        choices = ('approve','reject') if action == 'module_review' else ('pass','fail')
        if p['result'] not in choices:raise BoardError('评审结论无效')
        check = module_check(v,all_tasks,p['ref']) if action == 'module_review' else milestone_check(v,all_tasks,p['ref'])
        if check['scope'] != p['scope']:raise BoardError('评审范围已变化，请重读',409)
        if p['result'] == choices[0] and check['blockers']:raise BoardError('；'.join(check['blockers']),409)
        text(p['summary'],'评审结论',8000);evidence(p['evidence'])
        m['reviews'].append({**deepcopy(p),'actor':actor['id'],'at':time.time()})
    else:raise BoardError('未知规划动作',404)


def snapshot(v, all_tasks):
    prepare(v)
    v['planning_health'] = {'charter_blockers': charter_blockers(v), 'unbound_tasks': sorted(k for k,t in all_tasks.items() if not t['spec'].get('work',{}).get('planning'))}
    v['module_readiness'] = {r: module_check(v,all_tasks,r) for r in v['modules']}
    v['milestone_readiness'] = {r: milestone_check(v,all_tasks,r) for r in v['milestone_plans']}
