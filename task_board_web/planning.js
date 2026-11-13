'use strict';
// Primary: planning readiness and the next review action. Secondary: module
// boundaries and milestone evidence. Tertiary: immutable history. Reuse surface,
// ink/secondary/muted, type-14/16/20 and space-12/16/24/32 tokens; no new palette.
function renderPlanning(box,d){
  const names={draft:'待澄清',research:'调研中',design:'方案待确认'};
  const health=d.planning_health,lead=section('从项目框架逐步展开');
  lead.append(el('p','项目目标 → 模块边界 → 调研与决策 → 接口冻结 → 原子任务 → 阶段验证','secondary'));
  lead.append(el('p',d.planning_policy.mode==='enforced'?'规划门禁已启用':'历史兼容模式 · 启用前请核定当前任务，历史验收不会自动补成规划评审。','badge'));
  if(health.charter_blockers.length)lead.append(el('p',health.charter_blockers.join('；'),'detail-text'));
  lead.append(el('p',`未绑定模块的任务 ${health.unbound_tasks.length} 项。未知项可以先保留，执行前必须确认方案与接口。`,'muted'));box.append(lead);
  const modules=section('模块与规划版本');
  if(!Object.keys(d.module_heads).length)modules.append(el('p','尚无项目框架。先在“管理资料”登记模块草稿，再派发调研；明确边界后新增规划版本并评审。','empty'));
  for(const ref of Object.values(d.module_heads)){
    const m=d.modules[ref],c=d.module_readiness[ref],card=section(m.title);card.classList.add('planning-card');card.dataset.module=ref;
    card.append(el('p',`${ref} · ${c.ready?'可派发':names[m.stage]} · 负责人 ${m.owner}`,'badge'));
    cards(card,[['阶段目标',m.goal],['达成路径',m.path],['职责与范围',m.scope],['不包含',m.non_goals],['验收',m.acceptance],['风险',m.risks]]);
    card.append(el('p',`父模块：${m.parent||'顶层'}\n输入：${m.inputs.join('、')||'无'}\n输出：${m.outputs.join('、')||'无'}\n规划前置任务：${m.planning_tasks.join('、')||'无'}\n规划依赖模块：${m.depends_on.join('、')||'无'}\n公共接口：${m.interfaces.join('、')||m.no_interface_reason||'待核定'}\n未知项：${m.unknowns.join('；')||'无'}`,'detail-text'));
    card.append(el('p',c.blockers.join('；')|| (c.review_current?'当前规划评审有效':'等待SE评审当前范围'),'secondary'));
    if(app.role==='reviewer'){
      const revise=el('button','新增规划版本');revise.onclick=()=>editWorkspace('module_plan',{...m,version:'',stage:'design'});
      const review=el('button','评审当前范围');review.onclick=()=>editWorkspace('module_review',{ref,scope:c.scope,result:'approve'});card.append(revise,review);
    }
    modules.append(card);
  }box.append(modules);
  const milestones=section('里程碑 · 阶段验证');
  if(!Object.keys(d.milestone_heads).length)milestones.append(el('p','阶段目标需关联模块版本和交付任务，并写明检验方法、阈值、环境及负责人。','muted'));
  for(const ref of Object.values(d.milestone_heads)){
    const m=d.milestone_plans[ref],c=d.milestone_readiness[ref],card=section(`${ref} · ${c.passed?'阶段验收通过':'待阶段验证'}`);card.dataset.milestone=ref;
    cards(card,[['阶段目标',m.goal],['达成路径',m.path],['进入条件',m.entry],['检验方法',m.method],['通过阈值',m.threshold],['验证环境',m.environment],['验收标准',m.acceptance],['风险与处置',m.risks]]);
    card.append(el('p',`模块：${m.modules.join('、')}\n任务：${m.tasks.join('、')}\n验收负责人：${m.reviewer} · 计划：${m.due}`,'detail-text'),el('p',c.blockers.join('；')||(c.passed?'阶段检验已通过，当前范围与证据有效。':'交付条件满足；仍需阶段实际检验及证据。'),'secondary'));
    if(app.role==='reviewer'&&app.actor===m.reviewer){const b=el('button','记录阶段检验结果');b.onclick=()=>editWorkspace('milestone_review',{ref,scope:c.scope,result:'pass'});card.append(b);}
    listLines(card,'阶段检验记录',m.reviews,r=>`${r.result} · ${r.actor}\n${r.summary}\n证据 ${r.evidence.length} 项`);milestones.append(card);
  }box.append(milestones);
  listLines(box,'研究结论与决策',Object.values(d.planning_decisions),r=>`${r.id} · ${r.question}\n结论：${r.conclusion}\n来源任务：${r.research_tasks.join('、')} · ${r.actor}`);
  if(Object.keys(d.modules).length){
    const graph=section('模块规划依赖与任务展开'),nodes=[],edges=[];
    // Include every referenced immutable version, not just current heads.
    for(const [ref,m]of Object.entries(d.modules)){nodes.push({id:'module:'+ref,title:m.title+' · '+ref,kind:'family',category:'模块',status:d.module_readiness[ref].ready?'可派发':names[m.stage]});if(m.parent&&d.module_heads[m.parent])edges.push({from:'module:'+d.module_heads[m.parent],to:'module:'+ref,type:'containment'});for(const dep of m.depends_on)edges.push({from:'module:'+dep,to:'module:'+ref,type:'hard'});for(const tid of m.planning_tasks)edges.push({from:tid,to:'module:'+ref,type:'hard'});}
    for(const n of d.nodes){const p=n.planning;if(!p)continue;nodes.push(n);if(!edges.some(e=>e.from===n.id&&e.to==='module:'+p.module))edges.push({from:'module:'+p.module,to:n.id,type:'containment'});}
    // Task lists can be filtered/paginated; graph nodes come from the complete
    // authorized snapshot, so a research predecessor never silently disappears.
    for(const n of d.nodes)if(!nodes.some(x=>x.id===n.id)&&edges.some(e=>e.from===n.id||e.to===n.id))nodes.push(n);
    graph.append(el('p','实线表示规划所需前置；虚线表示模块包含/任务展开，不代表执行阻塞。','muted'));
    drawGraph(graph,{nodes,graph:edges},true);box.append(graph);
  }
  relationDetails(box,'全部模块版本',Object.entries(d.modules),([ref,m])=>`${ref} · ${m.goal} · ${m.reviews.length} 次评审`);
}
