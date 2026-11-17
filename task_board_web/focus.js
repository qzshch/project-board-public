'use strict';
// Reuse the plain HTML application's tokens and native details/forms. Current
// actions lead; versioned references and history remain available on demand.
function taskRecordView(t){if(['accepted','merged','native_accepted','baseline_merged'].includes(t.status))return 'completed';return t.spec.kind==='atomic'||['active','submitted','changes_requested'].includes(t.status)?'current':'structure';}
const recordView=selectInput(document.querySelector('.filters'),'记录范围','record-view',{current:'当前执行',completed:'已完成',structure:'历史结构记录','':'全部记录'},'current');
recordView.id='record-view';
recordView.onchange=()=>{app.view='all';app.limit=40;document.querySelectorAll('[data-view]').forEach(n=>n.setAttribute('aria-pressed',String(n.dataset.view==='all')));render();};
const focusSetView=setView;setView=function(view){recordView.value=view==='archive'?'completed':view==='all'?'':'current';focusSetView(view);};
function focusTaskButton(box,id,label){const b=el('button',label||id);b.onclick=()=>showDetail(id);box.append(b);return b;}
async function renderCurrentState(box){
 const project=app.project,generation=app.generation,host=section('当前状态 · 实时权威记录');host.id='current-state';box.prepend(host);
 try{const d=await api('/api/current');if(project!==app.project||generation!==app.generation||!host.isConnected)return;
  host.append(el('p',d.instruction,'secondary'));cards(host,[['当前执行',String(d.counts.current||0)],['已完成',String(d.counts.completed||0)],['历史结构记录',String(d.counts.structure||0)],['未决评审发现',String(d.open_findings)]]);
  host.append(el('p',`任务链 ${d.heads.tasks.seq} · 与范围、候选、验收及合入记录直接对应；文件报告不代表现在。`,'muted'));
  const current=d.tasks.filter(t=>['active','submitted','changes_requested'].includes(t.status));
  const list=el('details',undefined,'relation-details');list.append(el('summary',`正在推进与待处理 · ${current.length} 项`));
  for(const t of current){const row=el('p');focusTaskButton(row,t.id,t.title);row.append(el('span',' · '+(states[t.status]?.[0]||t.status)+' · 范围 v'+t.scope_version,'secondary'));list.append(row);}host.append(list);
  const git=section('仓库同步状态');for(const r of d.repositories)git.append(el('p',`${r.repository} · ${r.sync_error?'同步异常':r.synced_at?'已有同步记录':'尚未同步'}${r.default_branch&&r.refs?.[r.default_branch]?' · '+r.refs[r.default_branch]:''}`,'detail-text'));if(d.repositories.length)host.append(git);
  const tools=el('div',undefined,'graph-controls');for(const [label,view]of [['查看当前任务','active'],['查看已完成任务','archive'],['查看全部与历史','all']]){const b=el('button',label);b.onclick=()=>setView(view);tools.append(b);}host.append(tools);
 }catch(e){if(host.isConnected)host.append(el('p','当前状态读取失败：'+e.message,'notice'));}
}
const focusWorkspace=renderWorkspace;renderWorkspace=function(){focusWorkspace();if(ws.panel==='overview')renderCurrentState($('workspace-body'));};

function renderFocusInbox(host,workbench){
 const names={se:'待SE处理',worker:'待执行者确认',collaborators:'协作待处理'},types={thread:'讨论',submission:'候选评审',criterion:'逐项验收',finding:'评审发现'};
 const controls=el('div',undefined,'graph-controls'),filter=selectInput(controls,'下一责任方','inbox-focus',{'':'全部当前行动',...names},'');host.append(controls);
 const groups=workbench.action_groups||workbench.items.map(i=>({task:i.task,id:i.task||i.id,roles:[],items:[i]})),list=el('div');host.append(el('p',`${groups.length} 组当前行动 · 原始 ${workbench.items.length} 条记录按任务汇总，内容与门禁保留。`,'secondary'),list);
 function draw(){list.replaceChildren();for(const group of groups){const actions=group.items.filter(i=>!filter.value||i.next_role===filter.value);if(!actions.length)continue;
  const task=app.tasks.find(t=>t.spec.id===group.task),card=el('details',undefined,'relation-details');card.dataset.inboxGroup=group.id;card.append(el('summary',`${task?.spec.title||group.task||actions[0].title} · ${actions.length} 项`));if(group.task)focusTaskButton(card,group.task,'打开当前任务与成果');
  for(const i of actions){const row=el('article',undefined,'resource-card');row.dataset.inbox=i.kind;row.append(el('p',`${types[i.kind]||i.kind} · ${i.title}`),el('p',`${i.id} · ${wfStatuses[i.status]||i.status} · ${names[i.next_role]||'待处理'}`,'secondary'));if(i.reason)row.append(el('p',i.reason,'secondary'));if(i.kind==='retrospective')pButton(row,'打开整理核定',()=>selectWorkspacePanel('time'));if(i.action){if(cvLabels[i.action])cvButton(row,i.action,i.task||null,i.seed);else coButton(row,i.action,i.task||null,i.seed);}card.append(row);}list.append(card);}
  if(!list.children.length)list.append(el('p','此责任方暂无当前行动。','empty'));}
 filter.onchange=draw;draw();
 const notifications=workbench.notifications||[];if(notifications.length){const history=el('details',undefined,'relation-details');history.dataset.notifications='true';history.append(el('summary',`已解决讨论的未读通知 · ${notifications.length} 项`),el('p','未读与未解决分别计算；阅读通知不会改变验收结论。','secondary'));for(const n of notifications)focusTaskButton(history,n.task,n.title);host.append(history);}
}

function renderCandidateDelivery(body,task){
 if(!wfWriter())return;
 if(task.status==='planned'&&!task.owner&&task.spec.registered&&task.spec.claimable){const sec=section('领取当前任务'),button=el('button','认领此任务','primary'),msg=el('p','','form-message');let frozen=null;button.onclick=async()=>{button.disabled=true;try{frozen??={request_id:requestId(),task_id:task.spec.id,action:'claim',expected_revision:task.revision,scope_version:task.scope_version,payload:{summary:'本人按当前范围认领'}};await api('/api/events',frozen);await refresh();await showDetail(task.spec.id);}catch(e){msg.textContent=e.message;}finally{button.disabled=false;}};sec.append(button,msg);body.append(sec);return;}
 if(task.owner!==app.actor||!['active','changes_requested'].includes(task.status))return;
 const sec=section('提交候选成果'),form=el('form',undefined,'review-form');sec.id='candidate-delivery';sec.append(el('p','完成工作即可先提交待评审，无需等SE预审。此表记录一次成果与证据；逐项声明和缺少的检查在验收前补齐，严格门禁保持。','secondary'),form);body.append(sec);
 formInput(form,'成果与结论（注明工作记录入口及剩余未知）','summary',true,'');
 const selected=[];const items=el('fieldset');items.append(el('legend','本次实际交付项（明确选择）'));for(const d of task.spec.deliverables){const label=el('label',d.id+' · '+d.label),check=el('input');check.type='checkbox';check.value=d.id;label.prepend(check);items.append(label);selected.push(check);}form.append(items);
 selectInput(form,'交付范围','completeness',{partial:'部分成果',full:'全部约定交付项'},'partial');
 formInput(form,'实现提交（完整Git SHA；非代码可用下方产物）','implementation_commit',false,'');
 const artifact=el('details',undefined,'relation-details');artifact.append(el('summary','非代码产物锚点'));formInput(artifact,'原件位置','artifact_ref',false,'');formInput(artifact,'原件SHA256','artifact_sha256',false,'');form.append(artifact);
 formInput(form,'实际验证结果或未执行原因','tests',true,'');selectInput(form,'验证方式','verification_method',{manual:'手工验证',inspection:'检查',automated:'自动测试',not_applicable:'不适用'},'manual');selectInput(form,'实际验证状态','verification_status',{not_run:'尚未执行',passed:'已通过',failed:'有失败'},'not_run');
 formInput(form,'验证方式选择依据','verification_reason',true,'');formInput(form,'证据：每行 标签 | 位置 | SHA256','evidence',true,'');formInput(form,'剩余范围（确无则写无）','remaining',true,'');
 const extra=el('details',undefined,'relation-details');extra.append(el('summary','已有运行与返修引用（按需）'));formInput(extra,'实际运行ID，每行一项','test_runs',true,'');formInput(extra,'本次处理的返修ID，每行一项','addresses',true,'');form.append(extra);
 const message=el('p','','form-message'),save=el('button','提交到待评审队列','primary');save.type='submit';form.append(message,save);let frozen=null;
 form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{if(app.project!==project||app.generation!==generation)throw new Error('项目已切换，请重新读取');if(!frozen){const val=k=>form.elements[k].value.trim(),lines=k=>val(k).split('\n').map(x=>x.trim()).filter(Boolean),ids=selected.filter(c=>c.checked).map(c=>c.value);if(!ids.length)throw new Error('请选择本次实际交付项');const p={summary:val('summary'),completeness:val('completeness'),deliverable_ids:ids,implementation_commit:val('implementation_commit'),evidence:lines('evidence').map(l=>{const [label,path,sha256]=l.split('|').map(x=>x.trim());return {label,path,sha256};}),tests:val('tests'),remaining:val('remaining'),addresses:lines('addresses'),verification:{method:val('verification_method'),status:val('verification_status'),summary:val('tests'),reason:val('verification_reason')}};if(lines('test_runs').length)p.test_runs=lines('test_runs');if(val('artifact_ref')||val('artifact_sha256'))p.artifact={ref:val('artifact_ref'),sha256:val('artifact_sha256')};frozen={request_id:requestId(),task_id:task.spec.id,action:'submit',expected_revision:task.revision,scope_version:task.scope_version,payload:p};}await api('/api/events',frozen);await refresh();await showDetail(task.spec.id);}catch(e){message.textContent=e.message;if(e.status===400)frozen=null;}finally{save.disabled=false;}};
 const project=app.project,generation=app.generation;
}
wfLabels.thread_supersede='由新讨论接续';wfFields.thread_supersede=[['thread','被替代的普通讨论ID'],['replacement','同任务当前接续讨论ID'],['summary','接续依据与哪些提醒不再重复','text']];
