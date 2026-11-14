'use strict';
const ws={panel:new URLSearchParams(location.search).get('panel')||'overview',data:null,shared:null,ops:null,git:null,signature:null,graphFamily:'',graphQuery:'',graphMode:'all',zoom:1};
const categoryNames={research:'研究 / 调研',collection:'素材采集',generation:'资源生成',infrastructure:'框架 / 基建',frontend:'前端开发',backend:'后端开发',library:'公共库',documentation:'记录 / 约束 / 交接文档',test:'测试',integration:'集成',release:'发布'};
const roleNames={owner:'总负责人',se:'继承 SE',researcher:'研究员',collector:'素材采集',generator:'资源生成',developer:'开发',documenter:'文档',tester:'测试',agent:'Agent',viewer:'只读',runner:'测试执行器',tracker:'Git只读同步器',restorer:'回退执行器'};
const panelNames={discovery:'需求与改进',inbox:'SE待办与协作',overview:'项目概览',planning:'框架与规划',policy:'治理策略',time:'时间与效率',quality:'测试与自动化',git:'代码与提交',tasks:'任务与验收',relations:'依赖与并行',contracts:'接口冻结',assets:'项目资产',handoff:'角色与交接'};
function clearWorkspace(){ws.data=null;ws.shared=null;ws.ops=null;ws.git=null;resetGit();resetResources();ws.signature=null;ws.graphFamily='';ws.graphQuery='';ws.zoom=1;$('workspace-body').replaceChildren();$('workspace').hidden=true;$('task-metrics').hidden=true;$('task-board').hidden=true;}
async function refreshWorkspace(generation){
  const [data,shared,ops,git]=await Promise.all([api('/api/governance'),api('/api/shared'),api('/api/operations'),api('/api/git')]);
  if(generation!==app.generation)return;
  const signature=JSON.stringify([app.project,data,shared,['policy','time','quality','assets','inbox','tasks','discovery'].includes(ws.panel)?ops.revision:0,ws.panel==='git'?git.revision:0]);ws.data=data;ws.shared=shared;ws.ops=ops;ws.git=git;$('workspace').hidden=false;if(app.selected&&$('detail').open&&$('task-workflow')&&Number($('task-workflow').dataset.revision)!==ops.revision){$('task-workflow').remove();renderTaskWorkflow($('detail-body'),app.selected);}if(signature!==ws.signature){ws.signature=signature;renderWorkspace();}
}
function listLines(box,title,rows,format){const sectionBox=section(title);if(!rows.length)sectionBox.append(el('p','尚未登记。','muted'));for(const row of rows)sectionBox.append(el('p',format(row),'detail-text'));box.append(sectionBox);}
function relationDetails(box,title,rows,format){const details=el('details',undefined,'relation-details');details.append(el('summary',`${title} · ${rows.length} 项`));listLines(details,title,rows,format);box.append(details);}
function cards(box,items){const grid=el('div',undefined,'workspace-grid');for(const [label,value] of items)grid.append(field(label,value||'待负责人登记'));box.append(grid);}
function renderWorkspace(){
  const d=ws.data;if(!d)return;if(!panelNames[ws.panel])ws.panel='overview';$('task-metrics').hidden=ws.panel!=='tasks';$('task-board').hidden=ws.panel!=='tasks';document.querySelectorAll('[data-panel]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.panel===ws.panel)));const box=$('workspace-body');box.replaceChildren();$('workspace-title').textContent=panelNames[ws.panel];$('workspace-subtitle').textContent=`本项目专属资料 · 治理记录 ${d.revision} · 操作记录 ${ws.ops?.revision||0}`;$('workspace-edit').hidden=app.role!=='reviewer'||['tasks','inbox','discovery'].includes(ws.panel);$('workspace-body').hidden=ws.panel==='tasks';$('workspace-title').closest('.section-head').hidden=ws.panel==='tasks';
  if(ws.panel==='inbox'){renderWorkflowInbox(box);renderCoordinationSummary(box,'inbox');}
  if(ws.panel==='discovery')renderDiscovery(box);
  if(ws.panel==='time'||ws.panel==='quality')renderCoordinationSummary(box,ws.panel);
  if(ws.panel==='assets')renderCoordinationSummary(box,'assets');
  if(ws.panel==='overview'){
    const planning=section('项目规划');planning.append(el('p',ws.ops?.policy.enabled?`项目默认${tierNames[ws.ops.policy.profile]}治理：按当前任务风险决定规划与验证门禁。`:d.planning_policy.mode==='enforced'?'已启用规划门禁：执行任务需绑定通过评审的模块版本。':'历史兼容模式：任务尚未按新规划门禁核定。','secondary'));const go=el('button','打开框架与规划');go.onclick=()=>selectWorkspacePanel('planning');planning.append(go);box.append(planning);
    cards(box,[['项目背景',d.knowledge.background],['目标',d.knowledge.goals],['非目标',d.knowledge.non_goals],['约束',d.knowledge.constraints]]);
    for(const [key,title] of [['materials','必读材料 · 固定版本'],['entries','项目入口']])listLines(box,title,d.knowledge[key]||[],r=>`${r.title} · ${r.version}\n${r.location}\nSHA256 ${r.sha256}`);
    listLines(box,'里程碑与验收',Object.values(d.milestones),r=>`${r.id} · ${r.status} · ${r.goal}\n验收：${r.acceptance}${r.evidence.length?' · 证据 '+r.evidence.length+' 项':''}`);
    listLines(box,'决策与历史变更',d.decisions.slice(-8).reverse(),r=>`${r.summary}\n依据：${r.reason} · ${r.actor}`);
  }
  if(ws.panel==='planning')renderPlanning(box,d);
  if(ws.panel==='git')renderGit(box);
  if(['policy','time','quality'].includes(ws.panel))renderOperations(box);
  if(ws.panel==='relations'){
    const eligible=d.queue.filter(r=>!r.blockers.length);box.append(el('p',`可领取 ${eligible.length} 项；执行时会再次原子检查角色、前置、写路径、资源和固定版本。`,'secondary'));
    drawGraph(box,d);
    relationDetails(box,'前置与冲突',d.queue,r=>`${r.id} · ${r.blockers.length?r.blockers.join('；'):'满足当前并行条件'}`);
    relationDetails(box,'产物 / 接口 / 资源耦合',d.graph.filter(r=>!['hard','containment'].includes(r.type)),r=>`${r.from} → ${r.to} · ${{product:'输入产物',produces:'输出产物',coupling:'共享修改',exclusive:'排他资源',contract:'固定接口',asset:'固定资产'}[r.type]}`);
    relationDetails(box,'任务包与原子任务映射',Object.values(d.packages),r=>`${r.id} → ${r.tasks.join('、')}\n来源：${r.source}\n待核定：${r.unknown}`);
  }
  if(ws.panel==='contracts'){
    listLines(box,'冻结版本',Object.entries(d.contracts),([ref,r])=>`${ref} · ${r.status} · 拥有者 ${r.owner}\n${r.signature}\n单位：${r.units} · 错误：${r.errors}\n事务：${r.transaction} · 幂等：${r.idempotency}\n来源：${r.source} · 兼容：${r.compatibility}`);
    for(const [id,c] of Object.entries(d.changes)){
      const sec=section(`变更 ${id}`);sec.append(el('p',`${c.contract} → ${c.replacement} · ${c.executed?'已执行':'待影响确认'}`),el('p',`直接：${c.impact.direct.join('、')||'无'}；反向依赖：${c.impact.transitive.join('、')||'无'}`),el('p',`迁移：${c.migration}\n测试：${c.tests}`),el('p',`所需确认：${c.required.join('、')} · 已确认：${c.confirmations.join('、')||'无'}`));
      if(!c.executed&&c.required.includes(app.actor)&&!c.confirmations.includes(app.actor)){const b=el('button','确认此影响范围');b.onclick=()=>editWorkspace('contract_confirm',{id,impact_hash:c.impact_hash||'',summary:'已审阅影响、迁移和测试'});sec.append(b);}box.append(sec);
    }
  }
  if(ws.panel==='assets'){
    renderProjectResources(box);
    renderAssetLearning(box);
    listLines(box,'本项目私有资产',Object.entries(d.assets),([ref,r])=>`${ref} · ${r.kind} · ${r.sensitivity}\n来源：${r.source} · 许可：${r.license}\n${r.location}\nSHA256 ${r.sha256}`);
    listLines(box,'已审核共享版本',ws.shared.releases,r=>`${r.ref} · ${r.status}\n${r.location}\n许可：${r.license} · SHA256 ${r.sha256}`);
    listLines(box,'本项目固定消费',Object.entries(ws.shared.consumption),([alias,r])=>`${alias} → ${r.release} · ${r.status}\n提供方发布新版不会自动更新此引用。`);
  }
  if(ws.panel==='handoff'){
    const resourceNote=section('接手时核对项目资料');resourceNote.append(el('p','项目资产中统一登记本地/NAS资料、测试记录、日志与运行入口。接手前核对当前可见目录、维护者、文件权限、版本与保留规则；实例管理资料不随项目SE身份自动转交。','secondary'));const resourceButton=el('button','打开项目资产与资源入口');resourceButton.onclick=()=>selectWorkspacePanel('assets');resourceNote.append(resourceButton);box.append(resourceNote);
    listLines(box,'项目责任与角色',Object.entries(d.members),([id,r])=>`${id} · ${roleNames[r.role]||r.role}\n${r.scope}`);
    const h=d.handoff;listLines(box,'移交审计',h?[h]:[],r=>`${r.from} → ${r.to} · ${r.accepted?'已接受，原负责人管理权限已撤销':'等待继承 SE 接受'}\n风险：${r.risks}\n活跃任务：${r.active.join('、')||'无'}`);
    if(h&&!h.accepted&&h.to===app.actor){const b=el('button','接受当前交接');b.onclick=()=>editWorkspace('handoff_accept',{scope:h.scope,summary:''});box.append(b);}
  }
}
function drawGraph(box,d,planningGraph=false){
  const controls=el('div',undefined,'graph-controls');
  const family=selectInput(controls,'任务族','graph-family',{'':'全部任务',...Object.fromEntries(d.nodes.filter(n=>n.kind==='family').map(n=>[n.id,n.title]))},ws.graphFamily);
  if(![...family.options].some(o=>o.value===ws.graphFamily))ws.graphFamily='';family.value=ws.graphFamily;
  const mode=selectInput(controls,'关系','graph-mode',{all:'全部已记录关系',hard:'硬依赖',containment:'任务层级'},ws.graphMode);
  const search=el('input');search.type='search';search.placeholder='定位任务 ID 或名称';search.value=ws.graphQuery;search.setAttribute('aria-label','在依赖图中定位任务');controls.append(search);
  const zoomOut=el('button','缩小'),zoomIn=el('button','放大'),zoomLabel=el('span','','muted');controls.append(zoomOut,zoomLabel,zoomIn);
  const summary=el('p','','secondary'),legend=el('p',planningGraph?'实线箭头：规划所需前置。虚线箭头：模块包含与任务展开，不代表执行阻塞。':'实线箭头：已记录的硬前置。虚线箭头：任务包/任务族层级，不代表执行前置。未核定的依赖不会自动补全。','muted');
  const stage=el('div',undefined,'graph-stage');stage.tabIndex=0;stage.setAttribute('aria-label','可滚动的任务关系图');box.append(controls,summary,legend,stage);
  function draw(){
    const graph=projectGraph(d.nodes,d.graph,{family:ws.graphFamily,query:ws.graphQuery,mode:ws.graphMode}),layout=layoutProjectGraph(graph.nodes,graph.edges);
    const hard=graph.edges.filter(e=>e.type==='hard').length,parent=graph.edges.filter(e=>e.type==='containment').length,unknown=graph.nodes.filter(n=>n.category==='unknown').length;
    summary.textContent=`当前显示 ${graph.nodes.length} / ${d.nodes.length} 项任务 · ${hard} 条硬依赖 · ${parent} 条层级关系${unknown?' · '+unknown+' 项原子分类待核定':''}${layout.unresolved.length?' · 存在环或未分层节点，请SE核定':''}`;
    zoomLabel.textContent=Math.round(ws.zoom*100)+'%';const old={x:stage.scrollLeft,y:stage.scrollTop};stage.replaceChildren();
    if(!graph.nodes.length){stage.append(el('p','当前筛选无任务。','empty'));return;}
    const ns='http://www.w3.org/2000/svg',make=(tag,attrs={})=>{const n=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);return n;};
    const svg=make('svg',{viewBox:`0 0 ${layout.width} ${layout.height}`,role:'img','aria-label':'当前项目的真实任务关系图','data-nodes':graph.nodes.length,'data-edges':graph.edges.length});svg.classList.add('dependency-graph');svg.style.width=layout.width*ws.zoom+'px';svg.style.height=layout.height*ws.zoom+'px';
    const defs=make('defs'),marker=make('marker',{id:'dependency-arrow',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:7,markerHeight:7,orient:'auto-start-reverse'});marker.append(make('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'currentColor'}));defs.append(marker);svg.append(defs);
    for(const edge of graph.edges){const a=layout.positions.get(edge.from),b=layout.positions.get(edge.to),x1=a.x+a.width,y1=a.y+a.height/2,x2=b.x,y2=b.y+b.height/2,mid=(x1+x2)/2;const p=make('path',{d:`M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`,'marker-end':'url(#dependency-arrow)','data-edge-type':edge.type});p.classList.add('graph-edge');if(edge.type==='containment')p.classList.add('containment');svg.append(p);}
    for(const node of graph.nodes){const p=layout.positions.get(node.id),g=make('g',{'data-task':node.id,role:'button',tabindex:0,'aria-label':node.title});g.classList.add('graph-node');const title=make('title');title.textContent=node.title+' · '+node.id;g.append(title,make('rect',{x:p.x,y:p.y,width:p.width,height:p.height,rx:8}));
      for(const [line,label] of [[0,node.title],[1,node.id],[2,(node.id.startsWith('module:')?'模块':categoryNames[node.category]||kinds[node.kind]||'分类待核定')+' · '+(states[node.status]?.[0]||node.status)]]){const t=make('text',{x:p.x+12,y:p.y+22+line*22});t.textContent=label.length>32?label.slice(0,30)+'…':label;g.append(t);}
      const open=()=>{if(node.id.startsWith('module:')){const card=[...document.querySelectorAll('[data-module]')].find(c=>c.dataset.module===node.id.slice(7));if(card)card.scrollIntoView({behavior:'smooth'});}else showDetail(node.id);};g.onclick=open;g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open();}};svg.append(g);
    }
    stage.append(svg);stage.scrollLeft=old.x;stage.scrollTop=old.y;
  }
  family.onchange=()=>{ws.graphFamily=family.value;draw();};mode.onchange=()=>{ws.graphMode=mode.value;draw();};search.oninput=()=>{ws.graphQuery=search.value;draw();};zoomOut.onclick=()=>{ws.zoom=Math.max(.4,ws.zoom-.2);draw();};zoomIn.onclick=()=>{ws.zoom=Math.min(2,ws.zoom+.2);draw();};draw();
}
function selectInput(form,label,name,values,current){const group=el('label',label),input=el('select');input.name=name;for(const [v,l] of Object.entries(values)){const o=el('option',l);o.value=v;input.append(o);}input.value=current||Object.keys(values)[0];group.append(input);form.append(group);return input;}
function atomicInputs(form,task){
  const w=task?.spec.work;selectInput(form,'任务分类','category',{'':'历史任务包（不自动推断原子范围）',...categoryNames},w?.category||'');selectInput(form,'执行角色','work_role',Object.fromEntries(Object.entries(roleNames).filter(([k])=>!['runner','viewer','tracker'].includes(k))),w?.role||'developer');
  const label=el('label',undefined,'check'),check=el('input');check.type='checkbox';check.name='inputs_known';check.checked=w?.inputs_known||false;label.append(check,el('span','输入、来源版本与耦合已核定'));form.append(label);
  for(const [key,title] of [['inputs','输入与SHA引用'],['outputs','输出产物'],['contracts','固定接口（id@版本）'],['assets','固定资产（本项目引用ID）'],['resources','排他资源（端口/设备等）'],['couplings','共享修改（入口/数据库等）']])formInput(form,title+'，每行一项','work_'+key,true,w?.[key]?.join('\n')||'');
  formInput(form,'行为与反例验收条件','work_acceptance',true,w?.acceptance||'');
  formInput(form,'固定模块版本（id@version）','planning_module',false,w?.planning?.module||'');
  selectInput(form,'任务用途','planning_purpose',{execution:'执行模块方案',planning:'调研 / 采集 / 规划文档'},w?.planning?.purpose||'execution');
  formInput(form,'规划任务要解决的问题','planning_question',true,w?.planning?.question||'');
  formInput(form,'无共享接口的依据（未引用接口时必填）','planning_no_interface_reason',true,w?.planning?.no_interface_reason||'');
}
const actionFields={
  knowledge:['项目背景|background','目标|goals','非目标|non_goals','约束|constraints','必读材料（每行 标题 | 位置 | 版本 | SHA256）|materials','入口（同上格式）|entries','历史材料说明（无材料时说明原因）|history_notes','资源准备说明（无入口时说明准备计划）|resource_notes'],
  planning_enable:['启用依据（单向启用，不改写历史）|reason'],
  module_plan:['模块ID|id','新版本|version','模块名称|title','父模块ID，可留空|parent','目标|goal','职责与范围|scope','不包含的范围|non_goals','负责人ID|owner','达成路径|path','输入，每行一项|inputs','输出，每行一项|outputs','公共接口 id@版本，每行一项|interfaces','无共享接口依据，可留空|no_interface_reason','风险与应对|risks','未知项，每行一项|unknowns','规划前置任务ID，每行一项|planning_tasks','已确认研究决策ID，每行一项|decisions','规划依赖模块 id@版本，每行一项|depends_on','引用材料的登记位置，每行一项；空为仅项目章程|knowledge_refs','模块验收条件|acceptance','规划阶段 draft/research/design|stage','证据（每行 路径 | SHA256），草稿可空|evidence'],
  planning_decision:['不可变决策ID|id','研究问题|question','确认结论及未决边界|conclusion','已验收研究/采集/文档任务ID，每行一项|research_tasks','证据（每行 路径 | SHA256）|evidence'],
  module_review:['模块 id@版本|ref','当前评审摘要|scope','结论 approve/reject|result','评审依据|summary','证据（每行 路径 | SHA256）|evidence'],
  milestone_plan:['里程碑ID|id','新版本|version','阶段目标|goal','达成路径|path','进入条件|entry','关联模块 id@版本，每行一项|modules','关联交付任务ID，每行一项|tasks','验收条件|acceptance','检验方法|method','通过阈值|threshold','验证环境|environment','验收负责人ID|reviewer','计划日期或时间窗口|due','风险与未通过处置|risks'],
  milestone_review:['里程碑 id@版本|ref','当前评审摘要|scope','结论 pass/fail|result','实际检验结果与进入条件核对|summary','阶段验证证据（每行 路径 | SHA256）|evidence'],
  milestone:['里程碑ID|id','目标|goal','验收条件|acceptance','状态 planned/active/passed/blocked|status','证据（每行 路径 | SHA256）|evidence'],
  decision:['决策|summary','原因|reason','证据（每行 路径 | SHA256）|evidence'],member:['已登记Agent ID|actor','角色|role','职责与范围|scope','执行者类型 human/agent/unknown|actor_kind'],
  package:['任务包ID|id','原子任务ID，每行一项|tasks','历史来源|source','未知/待核定边界|unknown'],
  contract_freeze:['接口ID|id','不可变版本|version','接口拥有者ID|owner','签名/字段|signature','单位|units','错误|errors','事务|transaction','幂等|idempotency','来源版本|source','生产者，每行一项|producers','消费者，每行一项|consumers','兼容窗口|compatibility','证据（每行 路径 | SHA256）|evidence'],
  contract_propose:['提案ID|id','旧接口 id@版本|contract','新接口 id@版本|replacement','迁移清单|migration','测试清单|tests'],
  contract_confirm:['提案ID|id','影响摘要|impact_hash','确认依据|summary'],contract_execute:['已确认提案ID|id'],
  asset:['资产ID|id','不可变版本|version','类型 skill/methodology/infrastructure/private|kind','来源|source','许可|license','敏感性 public/private/secret|sensitivity','SHA256|sha256','项目私有位置|location','负责人ID|owner','证据（每行 路径 | SHA256）|evidence'],
  publish:['本项目资产 id@版本|asset','共享受众项目ID，每行一项；*代表所有项目|audience','显式共享位置|shared_location','发布审核依据|review','证据（每行 路径 | SHA256）|evidence'],consume:['共享版本 project/id@版本|ref','本项目固定引用ID|alias','选择依据|reason','消费验证|tests'],upgrade:['新共享版本 project/id@版本|ref','原本项目引用ID|alias','升级批准依据|reason','回归结果|tests'],
  deprecate:['共享版本|ref','原因|reason','消费方影响/迁移计划|migration','证据（每行 路径 | SHA256）|evidence'],withdraw:['共享版本|ref','原因|reason','消费方影响/迁移计划|migration','证据（每行 路径 | SHA256）|evidence'],
  handoff_propose:['继承SE ID|to','未决风险|risks','已读版本，每行一项|materials','移交原因|reason'],handoff_accept:['当前范围摘要|scope','接受说明|summary']};
const actionLabels={planning_enable:'启用规划门禁',module_plan:'登记模块新规划版本',planning_decision:'确认研究结论',module_review:'评审模块方案',milestone_plan:'登记里程碑规划版本',milestone_review:'阶段验收评审',knowledge:'更新项目背景与材料',milestone:'登记历史里程碑',decision:'追加决策',member:'指定角色与职责',package:'登记任务包映射',contract_freeze:'冻结新接口版本',contract_propose:'提议接口变更',contract_confirm:'确认影响范围',contract_execute:'执行已确认变更',asset:'登记私有资产',publish:'审核发布共享版本',consume:'固定消费版本',upgrade:'批准消费升级',deprecate:'弃用共享版本',withdraw:'撤回共享版本',handoff_propose:'提出SE交接',handoff_accept:'接受交接'};
async function postGovernance(action,payload){return api('/api/governance',{request_id:requestId(),expected_revision:ws.data.revision,action,payload});}
function editWorkspace(fixed,seed={}){
  const choices={overview:['knowledge',...(ws.data.planning_policy.mode==='enforced'?[]:['milestone']),'decision'],planning:['module_plan','planning_decision','module_review','milestone_plan','milestone_review','planning_enable'],relations:['package'],contracts:['contract_freeze','contract_propose','contract_confirm','contract_execute'],assets:['asset','publish','consume','upgrade','deprecate','withdraw'],handoff:['member','handoff_propose']}[ws.panel];
  app.selected=null;$('detail-title').textContent='管理'+panelNames[ws.panel];$('detail-kind').textContent='项目专属记录';$('stale').hidden=true;const body=$('detail-body');body.replaceChildren();const form=el('form',undefined,'review-form');
  const choose=selectInput(form,'操作','operation',Object.fromEntries((fixed?[fixed]:choices).map(k=>[k,actionLabels[k]])),fixed||choices[0]);const dynamic=el('div');form.append(dynamic);
  function draw(){dynamic.replaceChildren();const action=choose.value;const initial=action==='knowledge'?ws.data.knowledge:seed;for(const row of actionFields[action]){const at=row.lastIndexOf('|'),label=row.slice(0,at),key=row.slice(at+1);let value=initial?.[key]||'';if(Array.isArray(value))value=value.map(r=>typeof r==='string'?r:key==='evidence'?[r.path,r.sha256].join(' | '):[r.title,r.location,r.version,r.sha256].join(' | ')).join('\n');if(key==='actor_kind')selectInput(dynamic,label,key,{unknown:'未分类',human:'人员',agent:'Agent'},value||'unknown');else if(key==='role')selectInput(dynamic,label,key,roleNames,value||'developer');else if(key==='stage')selectInput(dynamic,label,key,{draft:'待澄清',research:'调研中',design:'方案待确认'},value||'draft');else if(key==='result')selectInput(dynamic,label,key,action==='module_review'?{approve:'批准方案',reject:'退回方案'}:{pass:'阶段通过',fail:'阶段未通过'},value);else formInput(dynamic,label,key,true,value);}if(action==='asset'){const l=el('label',undefined,'check'),c=el('input');c.type='checkbox';c.name='shareable';l.append(c,el('span','具备通用共享资格（发布仍需单独审核）'));dynamic.append(l);}}
  choose.onchange=draw;draw();const message=el('p','','form-message'),save=el('button','追加项目记录','primary');save.type='submit';form.append(message,save);body.append(form);
  const revision=ws.data.revision;
  form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{const action=choose.value,p={};for(const row of actionFields[action]){const key=row.slice(row.lastIndexOf('|')+1);p[key]=form.elements[key].value.trim();}
    for(const key of ['tasks','producers','consumers','audience','inputs','outputs','interfaces','unknowns','planning_tasks','decisions','depends_on','research_tasks','modules','knowledge_refs'])if(key in p)p[key]=p[key].split('\n').map(s=>s.trim()).filter(Boolean);
    if(action==='knowledge')for(const key of ['materials','entries'])p[key]=p[key]?p[key].split('\n').filter(Boolean).map(s=>{const [title,location,version,sha256]=s.split('|').map(x=>x.trim());return{title,location,version,sha256};}):[];
    if(action==='handoff_propose')p.materials=p.materials.split('\n').filter(Boolean);
    if('evidence' in p)p.evidence=p.evidence?p.evidence.split('\n').filter(Boolean).map(s=>{const at=s.lastIndexOf('|');return{path:s.slice(0,at).trim(),sha256:s.slice(at+1).trim()};}):[];
    if(action==='asset')p.shareable=form.elements.shareable.checked;
    await api(['publish','consume','upgrade','deprecate','withdraw'].includes(action)?'/api/shared':'/api/governance',['publish','consume','upgrade','deprecate','withdraw'].includes(action)?{request_id:requestId(),action,payload:p}:{request_id:requestId(),expected_revision:revision,action,payload:p});$('detail').close();await refreshWorkspace(app.generation);
  }catch(error){message.textContent=error.message;}finally{save.disabled=false;}};$('detail').showModal();
}
function selectWorkspacePanel(panel){if(!panelNames[panel])return;ws.panel=panel;const params=new URLSearchParams(location.search);params.set('panel',panel);history.replaceState(null,'',location.pathname+'?'+params.toString());renderWorkspace();}
document.querySelectorAll('[data-panel]').forEach(b=>b.onclick=()=>selectWorkspacePanel(b.dataset.panel));
$('workspace-edit').onclick=()=>ws.panel==='git'?editGit():['policy','time','quality'].includes(ws.panel)?editOperations():editWorkspace();
for(const [value,label] of Object.entries(categoryNames)){const option=el('option',label);option.value=value;$('kind').append(option);}
