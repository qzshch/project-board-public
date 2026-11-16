'use strict';
// Product goals lead; nested native details retain technical plans/history.
// Existing plain HTML forms, semantic tokens and light/dark styles are reused.
const roadmapUI={project:null,query:'',expanded:{},stages:{}};
function roadmapProject(){if(roadmapUI.project!==app.project)Object.assign(roadmapUI,{project:app.project,query:'',expanded:{},stages:{}});}
function roadmapFocusRank(task){const h=ws.roadmap?.task_hints?.[task.spec.id];return (h?.focused?0:1)+({P0:0,P1:.1,P2:.2,P3:.3}[h?.stage_priority]||0);}
function roadmapButton(box,label,callback){const b=el('button',label);b.type='button';b.onclick=callback;box.append(b);return b;}
function roadmapState(row){if(row.state.passed)return row.state.baseline_matches_current===false?'固定版本已验 · 当前主线另需核对':'固定版本阶段验收通过';if(row.plan.reviews.length&&!row.state.review_current)return '已有历史结论 · 当前范围待核对';return row.state.ready?'交付条件就绪 · 待实际场景验收':'尚有交付条件待完成';}
function renderStageSummary(box,compact=false){
 const data=ws.roadmap;if(!data)return;roadmapProject();const host=section('当前交付目标');host.id=compact?'project-stage-summary':'project-stage-plans';
 const focus=data.focus?.ref,row=focus&&data.stages[focus];
 if(row){host.append(el('h4',row.plan.title),el('p',`${row.plan.priority} · ${roadmapState(row)}`,'badge'),el('p',row.plan.goal,'detail-text'),el('p',`固定基线：${row.plan.input_anchor||'尚未冻结'}${row.state.current_repository_head?'\n最近同步主线：'+row.state.current_repository_head:''}`,'secondary detail-text'));host.append(el('p',`${row.state.tasks.filter(t=>t.ready).length} / ${row.state.tasks.length} 项交付条件满足 · 任务完成不自动等于阶段通过`,'secondary'));if(!Object.values(data.heads).includes(focus))host.append(el('p','当前聚焦固定于历史版本；SE应明确选择是否采用新阶段范围，任务执行权不自动变化。','notice'));}
 else host.append(el('p','尚未选择当前交付目标。SE可冻结本次产品范围、优先级与验证标准，历史里程碑不自动代表当前目标已通过。','secondary'));
 if(row?.state.repository_sync_error)host.append(el('p','仓库同步异常；所列主线是最近观察值，请核对源状态。','notice'));
 host.append(el('p',data.policy,'secondary'));
 if(compact){roadmapButton(host,'查看阶段目标与功能树',()=>selectWorkspacePanel('planning'));box.prepend(host);return;}
 if(wfManager()){roadmapButton(host,'新增阶段目标',()=>editProductStage());const picker=selectInput(host,'聚焦阶段','stage-focus-ref',{'':'暂不聚焦',...Object.fromEntries(Object.values(data.heads).map(ref=>[ref,data.stages[ref].plan.title+' · '+ref]))},focus||'');roadmapButton(host,'调整当前聚焦',()=>editStageFocus(picker.value));}
 for(const ref of Object.values(data.heads).sort((a,b)=>(a===focus?-1:b===focus?1:data.stages[a].plan.priority.localeCompare(data.stages[b].plan.priority)))){
  const r=data.stages[ref],p=r.plan,s=r.state,card=el('details',undefined,'relation-details');card.dataset.productStage=ref;card.open=roadmapUI.stages[ref]||false;card.addEventListener('toggle',()=>{roadmapUI.stages[ref]=card.open;});
  card.append(el('summary',`${p.title} · ${p.priority} · ${roadmapState(r)}`));cards(card,[['阶段目标',p.goal],['本次纳入范围',p.scope],['明确不包含',p.non_goals]]);
  card.append(el('p',`基线 ${p.input_anchor||'待冻结'}\n验收负责人 ${p.reviewer}\n阶段验收前置 ${p.entry_stages.join('、')||'无'}（不作为任务领取前置）`,'secondary detail-text'));
  for(const t of s.tasks){const row=el('p');focusTaskButton(row,t.task,t.title);row.append(el('span',` · 要求 ${t.stage} · 当前 ${states[t.status]?.[0]||t.status}`,'secondary'));card.append(row);}
  for(const c of p.criteria)card.append(el('p',c.id+' · '+c.expected,'detail-text'));
  if(s.blockers.length)relationDetails(card,'阶段验收待处理',s.blockers,x=>x);
  if(s.baseline_matches_current===false)card.append(el('p','本结论固定于所列版本；当前主线不同，不能仅凭提交包含关系宣称后续修改已验证。','notice'));
  if(wfManager()){roadmapButton(card,'另建阶段版本',()=>editProductStage(ref));if(app.actor===p.reviewer)roadmapButton(card,'逐项核对阶段验收',()=>editStageReview(ref));}
  relationDetails(card,'阶段检验历史',p.reviews,x=>`${x.result} · ${x.by}\n${x.summary}\n固定基线 ${x.input_anchor} · 证据 ${x.evidence.length} 项`);host.append(card);
 }
 const history=Object.keys(data.stages).filter(ref=>!Object.values(data.heads).includes(ref));if(history.length)relationDetails(host,'历史阶段版本',history,ref=>`${ref} · ${data.stages[ref].plan.title} · ${data.stages[ref].plan.reviews.length} 次检验`);box.append(host);
}
function renderProductPlanning(box){
 const data=ws.roadmap;if(!data)return;renderStageSummary(box);
 roadmapProject();
 const tree=data.tree,host=section('产品功能树');host.id='product-function-tree';host.append(el('p',`组织来源：${tree.source==='function_tree'?'独立功能分类 v'+tree.definition.version:'既有模块父子关系'} · ${tree.classified_tasks} / ${tree.total_tasks} 条记录已归类；整理层级不改变任务范围、接口或历史验收。`,'secondary'));
 if(wfManager())roadmapButton(host,'编辑功能树',()=>editFunctionTree());const search=filterInput('搜索功能、模块或任务…');search.setAttribute('aria-label','搜索功能树');search.value=roadmapUI.query;host.append(search);const content=el('div');host.append(content);box.append(host);
 const nodes=new Map(tree.nodes.map(n=>[n.id,n]));
 function draw(){content.replaceChildren();const q=search.value.trim().toLowerCase();roadmapUI.query=search.value;const cache=new Map();
  const ownMatch=n=>[n.id,n.title,n.description,...n.modules.map(m=>m.id+' '+m.title)].join(' ').toLowerCase().includes(q);
  function has(nid){if(cache.has(nid))return cache.get(nid);const n=nodes.get(nid),v=!q||ownMatch(n)||n.tasks.some(t=>(t.id+' '+t.title).toLowerCase().includes(q))||n.children.some(has);cache.set(nid,v);return v;}
  function taskRows(parent,rows){let limit=40;const list=el('div');parent.append(list);const more=roadmapButton(parent,'显示更多记录',()=>{limit+=40;render();});function render(){list.replaceChildren();for(const t of rows.slice(0,limit)){const row=el('p');focusTaskButton(row,t.id,t.title);row.append(el('span',' · '+(states[t.status]?.[0]||t.status),'secondary'));list.append(row);}more.hidden=rows.length<=limit;}render();}
  function node(nid,parent,force=false,depth=0){const n=nodes.get(nid);if(!force&&!has(nid))return;const d=el('details',undefined,'relation-details');d.dataset.functionNode=n.id;d.open=!!q||(roadmapUI.expanded[nid]??(depth===0));d.addEventListener('toggle',()=>{if(!q)roadmapUI.expanded[nid]=d.open;});d.append(el('summary',`${n.title} · ${n.task_count} 条记录`));if(n.description)d.append(el('p',n.description,'secondary'));parent.append(d);const own=force||!!q&&ownMatch(n);
   for(const child of n.children)node(child,d,own,depth+1);
   const records=n.tasks.filter(t=>!q||own||(t.id+' '+t.title).toLowerCase().includes(q)),current=records.filter(t=>t.kind==='atomic'||['active','submitted','changes_requested'].includes(t.status)),history=records.filter(t=>!current.includes(t));taskRows(d,current);
   if(history.length){const h=el('details',undefined,'relation-details');h.append(el('summary',`历史与结构记录 · ${history.length} 项`));taskRows(h,history);d.append(h);}
   if(n.modules.length)relationDetails(d,'关联技术模块',n.modules,m=>`${m.title} · ${m.ref}`);
  }
  for(const root of tree.roots)node(root,content);
  const unknown=tree.unclassified_tasks.filter(t=>!q||(t.id+' '+t.title).toLowerCase().includes(q));if(unknown.length){const h=el('details',undefined,'relation-details');h.dataset.unclassified='tasks';h.open=!!q;h.append(el('summary',`待归类记录 · ${unknown.length} 项（原记录保留）`));taskRows(h,unknown);content.append(h);}
  if(tree.unclassified_modules.length)relationDetails(content,'待归类模块',tree.unclassified_modules,x=>x);
  if(!content.children.length)content.append(el('p','没有匹配项；原记录仍可在任务与历史中查阅。','empty'));
 }
 search.oninput=draw;draw();
}
async function roadmapForm(title,action,seed,builder){
 const project=app.project,generation=app.generation,body=resourceDialog(title);$('detail-kind').textContent='框架与规划';let data;
 try{data=await api('/api/roadmap');if(!validResourceDialog(body,project,generation))return;}catch(e){body.append(el('p',e.message,'notice'));return;}
 const form=el('form',undefined,'review-form');body.append(form);const read=builder(form,data,seed||{});const message=el('p','','form-message'),save=el('button','保存'+title,'primary');save.type='submit';form.append(message,save);let frozen=null;
 form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{if(!validResourceDialog(body,project,generation))throw new Error('项目或窗口已变化');frozen??={request_id:requestId(),expected_revision:data.revision,action,payload:read()};await api('/api/governance',frozen);await refreshWorkspace(generation);if(validResourceDialog(body,project,generation))$('detail').close();}catch(e){if(e.status===400)frozen=null;message.textContent=e.message;}finally{save.disabled=false;}};
}
function roadmapText(form,key,label,value='',multiline=true){const input=formInput(form,label,key,multiline,value);return ()=>input.value.trim();}
function roadmapLines(read){return read().split('\n').map(s=>s.trim()).filter(Boolean);}
function editStageFocus(ref){roadmapForm('调整阶段聚焦','stage_focus',{ref},(form,data,s)=>{const select=selectInput(form,'当前阶段','ref',{'':'暂不聚焦',...Object.fromEntries(Object.values(data.heads).map(r=>[r,data.stages[r].plan.title]))},s.ref);const reason=roadmapText(form,'reason','优先级调整依据');form.append(el('p','只调整推荐，不增加任何任务硬依赖，也不阻止其他无前置任务认领。','secondary'));return ()=>({ref:select.value,reason:reason()});});}
function editProductStage(ref){roadmapForm('阶段目标','stage_plan',{ref},(form,data,s)=>{
 const p=data.stages[s.ref]?.plan||{},reads={};for(const [key,label]of [['id','阶段稳定ID'],['version','新版本ID'],['title','阶段名称'],['goal','可验证的产品目标'],['scope','本次纳入范围'],['non_goals','明确不包含'],['input_anchor','固定基线 git:完整SHA 或 sha256:产物；未知可留空'],['repo','项目仓库ID；非Git留空'],['reviewer','阶段验收负责人Actor'],['reason','本次规划依据']])reads[key]=roadmapText(form,key,label,key==='version'?String(Date.now()):key==='reviewer'?(p[key]||app.actor):p[key]||'',!['id','version','title','input_anchor','repo','reviewer'].includes(key));
 const priority=selectInput(form,'阶段优先级','priority',{P0:'P0 · 紧急',P1:'P1 · 优先',P2:'P2 · 常规',P3:'P3 · 后续'},p.priority||'P1');
 const tasks=el('fieldset');tasks.append(el('legend','本阶段实际交付条件'));form.append(tasks);const rows=[];function addTask(value={}){const row=el('div',undefined,'resource-location-editor'),select=selectInput(row,'已有任务','task',{'':'选择任务',...Object.fromEntries(app.tasks.map(t=>[t.spec.id,t.spec.id+' · '+t.spec.title]))},value.task||''),stage=selectInput(row,'本阶段要求','stage',{accepted:'成果已验收',merged:'代码已合入',native_accepted:'实际运行已验收'},value.stage||'accepted');roadmapButton(row,'移除条件',()=>{row.remove();});tasks.append(row);rows.push({row,select,stage});}for(const t of p.tasks||[])addTask(t);roadmapButton(form,'关联已有任务',()=>addTask());
 const criteria=roadmapText(form,'criteria','逐项产品验收：每行 稳定ID | 可判定预期',(p.criteria||[]).map(c=>c.id+' | '+c.expected).join('\n'));const entry=roadmapText(form,'entry_stages','阶段验收前置版本，每行一项；不作为任务领取前置',(p.entry_stages||[]).join('\n'));
 return ()=>({...Object.fromEntries(Object.entries(reads).map(([k,v])=>[k,v()])),priority:priority.value,tasks:rows.filter(r=>r.row.isConnected&&r.select.value).map(r=>({task:r.select.value,stage:r.stage.value})),criteria:roadmapLines(criteria).map(l=>{const [id,...expected]=l.split('|').map(x=>x.trim());return {id,expected:expected.join(' | ')};}),entry_stages:roadmapLines(entry)});
 });}
function editStageReview(ref){roadmapForm('阶段逐项验收','stage_review',{ref},(form,data,s)=>{
 const row=data.stages[s.ref],p=row.plan,checks=[];form.append(el('p',`${p.title}\n固定基线 ${p.input_anchor||'尚未冻结'}\n${row.state.blockers.join('；')}`,'secondary detail-text'));
 for(const c of p.criteria){const group=el('fieldset');group.append(el('legend',c.id+' · '+c.expected));const result=selectInput(group,'实际结论','check-'+c.id,{'':'明确选择',pass:'通过',fail:'不通过'},'');const summary=roadmapText(group,'summary-'+c.id,'实际场景、原件核对与结论');checks.push({id:c.id,result,summary});form.append(group);}
 const result=selectInput(form,'本阶段结论','result',{fail:'尚未通过',pass:'固定版本通过'},'fail'),summary=roadmapText(form,'summary','总体结论与剩余范围'),ev=roadmapText(form,'evidence','原件证据：每行 位置 | SHA256');
 return ()=>({ref:s.ref,scope:row.state.scope,input_anchor:p.input_anchor,result:result.value,summary:summary(),checks:checks.map(c=>({id:c.id,result:c.result.value,summary:c.summary()})),evidence:roadmapLines(ev).map(l=>{const [path,sha256]=l.split('|').map(x=>x.trim());return {path,sha256};})});
 });}
function editFunctionTree(){roadmapForm('功能树组织版本','function_tree',{},(form,data)=>{
 const old=data.tree.definition,version=roadmapText(form,'version','新组织版本ID',String(Date.now()),false),reason=roadmapText(form,'reason','分类调整依据'),host=el('div'),rows=[];form.append(el('p','仅关联既有稳定ID。模块ID覆盖该模块绑定任务；只有零散或历史记录才需额外关联任务。未归类记录仍保留。','secondary'),host);
 function add(n={}){const group=el('details',undefined,'relation-details');group.open=!n.id;group.append(el('summary',n.title||'新功能节点'));host.append(group);const reads={};for(const [key,label]of [['id','功能稳定ID'],['title','功能名称'],['parent','父功能ID；顶层留空'],['description','范围说明'],['module_ids','关联已有模块ID，每行一项'],['task_ids','额外关联已有任务ID，每行一项']])reads[key]=roadmapText(group,key+'-'+rows.length,label,Array.isArray(n[key])?n[key].join('\n'):n[key]||'',!['id','title','parent'].includes(key));roadmapButton(group,'移除此分类节点',()=>group.remove());rows.push({group,reads});}
 for(const n of old?.nodes||data.tree.nodes.map(({id,title,parent,description,module_ids})=>({id,title,parent,description,module_ids,task_ids:[]})))add(n);roadmapButton(form,'添加功能/子功能',()=>add());
 return ()=>({version:version(),reason:reason(),nodes:rows.filter(r=>r.group.isConnected).map(r=>Object.fromEntries(Object.entries(r.reads).map(([key,read])=>[key,key.endsWith('_ids')?roadmapLines(read):read()]))) });
 });}
function renderTaskRoadmap(box,task){const data=ws.roadmap;if(!data)return;const h=data.task_hints[task.spec.id],node=data.tree.task_map[task.spec.id],nodes=new Map(data.tree.nodes.map(n=>[n.id,n]));const path=[];let n=nodes.get(node);while(n){path.unshift(n.title);n=nodes.get(n.parent);}const sec=section('产品归属与阶段');sec.append(el('p',path.join(' → ')||'待归类（任务与原范围保留）','detail-text'),el('p',`${h?.focused?'当前聚焦阶段任务':'其他可并行范围'} · ${(h?.stages||[]).join('、')||'未纳入某次阶段交付'}\n阶段只影响推荐；能否领取以真实前置、权限和资源检查为准。`,'secondary detail-text'));box.append(sec);}
const roadmapWorkspace=renderWorkspace;renderWorkspace=function(){roadmapWorkspace();const box=$('workspace-body');if(ws.panel==='overview')renderStageSummary(box,true);if(ws.panel==='planning'){const stages=box.querySelector('#project-stage-plans'),tree=box.querySelector('#product-function-tree'),technical=box.querySelector('#technical-planning');if(stages)box.prepend(stages);if(stages&&tree)stages.after(tree);if(technical&&ws.roadmap?.tree.definition)for(const child of [...box.children])if(![stages,tree,technical].includes(child))technical.append(child);}};

if(ws.data)renderWorkspace();
