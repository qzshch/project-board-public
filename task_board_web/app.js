'use strict';
const $ = id => document.getElementById(id);
const app = {tasks: [], view: 'review', etag: null, limit: 40, selected: null, role: 'viewer', actor: null, loading: false, project: null, projects: [], generation: 0, admin: false};
const states = {
  planned: ['待登记 / 待开始',''], blocked: ['等待具体前置',''], active: ['进行中','info'],
  reported: ['材料已交 · 待复核','warn'], submitted: ['已上报 · 待验收','warn'], changes_requested: ['需返修','bad'],
  accepted: ['验收通过','good'], partial_accepted: ['部分验收通过','good'], merged: ['已合入主线','good'],
  partial_merged: ['部分已合入','good'], native_accepted: ['运行验收通过','good'], partial_native: ['部分运行验收','good'],
  baseline_merged: ['声明范围已合入',''], partial_baseline: ['有限候选 / 研究',''], integration_pending: ['候选待接线','info']
};
const kinds = {family:'任务族', plan:'新增协作', integration:'主线集成', delivery:'协作交付', native:'原客户端'};
const eventNames = {import:'导入已知基线', create:'建立任务范围', assign:'派发 / 转交', claim:'领取任务', scope:'追加范围版本',
  progress:'上报进展', submit:'提交交付声明', accept:'验收记录', request_changes:'提出返修', reopen:'重新打开已验内容',
  merge:'记录主线合入', native:'记录运行验收', note:'追加说明', scope_proposal:'提出范围变更'};
function el(tag, text, className) { const node=document.createElement(tag); if(text!==undefined) node.textContent=text; if(className) node.className=className; return node; }
function notice(message) { $('notice').textContent=message; $('notice').hidden=!message; }
function date(value) { return value ? new Date(value).toLocaleString('zh-CN',{hour12:false}) : '—'; }
function requestId() { const value=crypto.getRandomValues(new Uint8Array(16));value[6]=(value[6]&15)|64;value[8]=(value[8]&63)|128;const h=Array.from(value,b=>b.toString(16).padStart(2,'0')).join('');return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`; }
function statusNode(value) { const [label,color]=states[value] || [value,'']; return el('span',label,'badge '+color); }
function projectPath(path) { if(!app.project) throw new Error('请先选择已授权的项目'); return `/api/projects/${app.project}/${path.slice(5)}`; }
async function api(path, value, global=false) {
  if(!global) path=projectPath(path);
  const response=await fetch(path,{method:value===undefined?'GET':'POST',credentials:'same-origin',
    headers:value===undefined?{}:{'Content-Type':'application/json'},body:value===undefined?undefined:JSON.stringify(value),cache:'no-store'});
  const result=await response.json(); if(!response.ok){const error=new Error(result.error||'请求失败');error.status=response.status;throw error;}return result;
}
function matchView(task) {
  if(app.view==='review') return ['reported','submitted'].includes(task.status);
  if(app.view==='rework') return task.status==='changes_requested';
  if(app.view==='active') return ['plan','integration','atomic'].includes(task.spec.kind)||Boolean(task.spec.work);
  if(app.view==='archive') return ['baseline_merged','partial_baseline','accepted','partial_accepted','merged','partial_merged','native_accepted','partial_native'].includes(task.status);
  return true;
}
function setView(view) { if(typeof selectWorkspacePanel==='function')selectWorkspacePanel('tasks');app.view=view; app.limit=40; document.querySelectorAll('[data-view]').forEach(n=>n.setAttribute('aria-pressed',String(n.dataset.view===view))); render(); }
function render() {
  $('count-review').textContent=app.tasks.filter(t=>['reported','submitted'].includes(t.status)).length;
  $('count-rework').textContent=app.tasks.filter(t=>t.status==='changes_requested').length;
  $('count-active').textContent=app.tasks.filter(t=>t.status==='active').length;
  $('count-family').textContent=app.tasks.filter(t=>t.spec.work).length;
  $('scope-note').textContent=`${app.tasks.length} 项任务 · ${app.tasks.filter(t=>t.spec.kind==='plan').length} 张协作卡 · 交付、合入与运行验收分别追踪`;
  const query=$('search').value.trim().toLowerCase();
  const rows=app.tasks.filter(t=>matchView(t) && (!$('kind').value || t.spec.kind===$('kind').value || t.spec.work?.category===$('kind').value) &&
    (!$('priority').value || t.spec.priority===$('priority').value) &&
    (!query || `${t.spec.id} ${t.spec.title} ${t.spec.description} ${t.owner||''} ${t.latest_summary}`.toLowerCase().includes(query)))
    .sort((a,b)=>(a.spec.priority||'P1').localeCompare(b.spec.priority||'P1') || b.updated_at.localeCompare(a.updated_at) || a.spec.id.localeCompare(b.spec.id));
  const list=$('task-list'); list.replaceChildren();
  for(const task of rows.slice(0,app.limit)) {
    const row=$('task-template').content.firstElementChild.cloneNode(true);
    const title=row.querySelector('.task-title'); title.textContent=task.spec.title; title.addEventListener('click',()=>showDetail(task.spec.id));
    row.querySelector('.task-description').textContent=task.latest_summary || task.spec.description;
    row.querySelector('.task-meta').append(el('span',task.spec.work?categoryNames[task.spec.work.category]:(kinds[task.spec.kind] || task.spec.kind)),el('span',task.spec.priority),
      el('span',task.spec.registered ? '范围已登记' : '待登记具体输入'));
    row.querySelector('.status').replaceWith(statusNode(task.status));
    row.querySelector('.owner').textContent=task.owner ? `负责人 · ${task.owner}` : '负责人待登记';
    const commit=task.latest_submission?.implementation_commit || task.spec.source?.source_head;
    row.querySelector('.version').textContent=`范围 v${task.scope_version} · 记录 ${task.revision}${commit?' · '+commit.slice(0,7):''}`;
    row.querySelector('time').textContent=date(task.updated_at); list.append(row);
  }
  if(!rows.length) list.append(el('div','当前筛选没有任务。可切换视图或清除搜索。','empty'));
  $('result-count').textContent=`显示 ${Math.min(rows.length,app.limit)} / ${rows.length} 项`;
  $('more').hidden=rows.length<=app.limit;
}
async function refresh() {
  if(app.loading || !app.project) return; app.loading=true; const generation=app.generation;
  try {
    const response=await fetch(projectPath('/api/snapshot'),{headers:app.etag?{'If-None-Match':app.etag}:{},credentials:'same-origin',cache:'no-store'});
    if(response.status!==304) {
      if(!response.ok) { const data=await response.json(); const error=new Error(data.error||'公告板读取失败');error.status=response.status;throw error; }
      const data=await response.json(); if(generation!==app.generation) return; app.etag=response.headers.get('ETag'); app.tasks=data.tasks; render();
      if(app.selected && $('detail').open) {
        const latest=app.tasks.find(t=>t.spec.id===app.selected.spec.id);
        $('stale').hidden=!latest || latest.revision===app.selected.revision;
      }
    }
    if(generation!==app.generation) return;
    if(typeof refreshWorkspace==='function') await refreshWorkspace(generation);
    if(app.connectionError) {notice('');app.connectionError=false;}
    $('connection').textContent='● 实时连接 · 2 秒更新'; $('connection').classList.remove('offline');
    $('last-updated').textContent='最近同步 '+new Date().toLocaleTimeString('zh-CN',{hour12:false});
  } catch(error) {
    if(generation!==app.generation) return;
    if([401,403,404].includes(error.status)) {clearProject();app.projects=[];app.admin=false;$('project-select').replaceChildren(el('option','请重新授权'));$('project-select').disabled=true;$('new-project').hidden=true;$('identity').textContent='未授权';$('project-description').textContent='授权已失效，请使用本项目的有效入口。';}
    app.connectionError=true;
    $('connection').textContent='● 连接中断 · 保留上次数据'; $('connection').classList.add('offline');
    notice(error.message);
  } finally { if(generation===app.generation) app.loading=false; }
}
function section(title) { const box=el('section',undefined,'detail-section'); box.append(el('h3',title)); return box; }
function field(label,value) { const box=el('div');box.append(el('div',label,'detail-label'),el('div',value,'detail-value'));return box; }
async function showDetail(id) {
  const generation=app.generation;
  const task=app.tasks.find(t=>t.spec.id===id); if(!task) return;
  app.selected=structuredClone(task); $('detail-kind').textContent=`${task.spec.work?categoryNames[task.spec.work.category]:(kinds[task.spec.kind]||task.spec.kind)} / ${task.spec.id}`;
  $('detail-title').textContent=task.spec.title; $('stale').hidden=true;
  const body=$('detail-body');body.replaceChildren();
  const summary=section('当前范围'); const grid=el('div',undefined,'details-grid');
  grid.append(field('状态',states[task.status]?.[0] || task.status),field('负责人',task.owner || '待登记'),
    field('范围与记录版本',`v${task.scope_version} / revision ${task.revision}`),field('最近更新',`${date(task.updated_at)} · ${task.last_actor}`));
  summary.append(grid,el('p',task.spec.description,'detail-text'));
  if(task.spec.source?.existing) summary.append(el('p','已有成果：'+task.spec.source.existing,'detail-text secondary'));
  body.append(summary);
  const deliverables=section('约定交付与验收');const items=el('ul');
  for(const item of task.spec.deliverables) items.append(el('li',`${Object.hasOwn(task.accepted,item.id)?'已验收':'待验收'} · ${item.id} ${item.label}`,'detail-text'));
  deliverables.append(items); body.append(deliverables);
  const deps=section('依赖与修改边界');
  for(const dep of task.spec.depends_on) { const button=el('button',dep,'dependency');button.addEventListener('click',()=>showDetail(dep));deps.append(button); }
  if(task.spec.source?.missing_inputs) deps.append(el('p',task.spec.source.missing_inputs.join('\n'),'detail-text'));
  if(task.spec.allowed_paths.length) deps.append(el('pre',task.spec.allowed_paths.join('\n')));
  if(!task.spec.depends_on.length && !task.spec.allowed_paths.length) deps.append(el('p','按该任务冻结的范围执行；新增或共享修改由负责人另行登记。','detail-text secondary'));
  body.append(deps);
  if(task.latest_submission) {
    const submitted=section(`第 ${task.latest_submission.round} 轮交付`);const submission=task.latest_submission;
    submitted.append(el('p',submission.summary,'detail-text'),field('实现提交',submission.implementation_commit),
      field('测试声明',submission.tests),field('尚余范围',submission.remaining));
    for(const item of submission.evidence) submitted.append(field(item.label,`${item.path}\nSHA256 ${item.sha256}`));
    body.append(submitted);
  }
  if(ws.git){const code=section('代码提交追踪'),anchor=task.latest_submission?.implementation_commit||task.spec.work?.baseline;
    if(/^[0-9a-f]{40}$/.test(anchor||''))for(const [id,repo]of Object.entries(ws.git.repos))if(repo.enabled){const b=el('button','在 '+repo.title+' 中查找此提交');b.onclick=()=>navigateGit(id,anchor);code.append(b);}
    if(code.children.length>1)body.append(code);}
  if(task.findings.length) {
    const returned=section('返修记录');
    for(const f of task.findings) { const box=el('div');box.append(statusNode(f.open?'changes_requested':'accepted'),el('p',f.description,'detail-text'),field('修正验收要求',f.acceptance),field('返修项ID',f.id));returned.append(box); }
    body.append(returned);
  }
  if(app.role==='reviewer') body.append(reviewForm(task));
  if(ws.ops){const sectionBox=section('治理、时间与测试'),risk=ws.ops.effective[task.spec.id];sectionBox.append(el('p',risk?`${tierNames[risk.level]} · ${risk.assessed?'当前范围已核定':'待SE核定'} · ${risk.reason}`:'尚未采用分级策略','detail-text'));
    const plan=ws.ops.test_plans[task.spec.id];if(plan)sectionBox.append(el('p','验证计划：'+plan.cases.join('、'),'detail-text'));
    if(app.role==='reviewer')operationButton(sectionBox,'核定当前任务风险','assess',{task:task.spec.id,level:risk?.level||'light'});
    if(task.owner===app.actor||app.role==='reviewer')operationButton(sectionBox,'记录当前作业','time_change',{task:task.spec.id,phase:'implementation',mode:'work',rework:false});body.append(sectionBox);}
  const history=section('历史时间线');const timeline=el('div','正在读取…','timeline');history.append(timeline);body.append(history);
  if(!$('detail').open) $('detail').showModal();
  $('detail').scrollTop=0;
  try {
    const data=await api('/api/history?task='+encodeURIComponent(id)+'&limit=200'); if(generation!==app.generation) return;
    if(app.selected?.spec.id!==id) return;
    timeline.replaceChildren();
    for(const event of data.events.toReversed()) {
      const node=el('article',undefined,'event');const head=el('div',undefined,'event-head');head.append(el('span',event.actor+' · '+event.role),el('time',date(event.created_at)));
      node.append(head,el('h3',eventNames[event.kind]||event.kind));
      if(event.kind==='import') node.append(el('p','导入时观察到的基线快照；不代表该时刻发生过历史验收。'));
      else node.append(el('p',event.payload.summary||event.payload.reason||''));
      const details=el('details');details.append(el('summary','查看此次事件与证据'),el('pre',JSON.stringify(event,null,2)));node.append(details);timeline.append(node);
    }
    if(data.events.length===200) timeline.append(el('p','此处显示前200条；完整历史可通过Agent客户端按游标读取。','muted'));
  } catch(error) { timeline.textContent=error.message; }
}
function formInput(form,label,name,multiline=false,value='') {
  const group=el('label',label);const input=el(multiline?'textarea':'input');input.name=name;input.value=value;group.append(input);form.append(group);return input;
}
function evidenceInput(form) { formInput(form,'证据路径（每行：路径 | SHA256）','evidence',true); }
function parseEvidence(form) { return form.elements.evidence.value.trim().split('\n').filter(Boolean).map(line=>{const split=line.lastIndexOf('|');if(split<1) throw new Error('每条证据需“路径 | SHA256”');return {path:line.slice(0,split).trim(),sha256:line.slice(split+1).trim(),label:'验收证据'};}); }
function scopeInputs(form,task) {
  const priorityLabel=el('label','优先级');const priority=el('select');priority.name='scope_priority';
  for(const value of ['P0','P1','P2']) {const option=el('option',value);option.value=value;priority.append(option);}
  priority.value=task?.spec.priority||'P1';priorityLabel.append(priority);form.append(priorityLabel);
  formInput(form,'任务名称','title',false,task?.spec.title||'');
  formInput(form,'完整范围说明','description',true,task?.spec.description||'');
  formInput(form,'约定交付项（每行一项）','deliverables',true,task?.spec.deliverables.map(i=>i.label).join('\n')||'');
  formInput(form,'依赖任务ID（每行一个）','depends',true,task?.spec.depends_on.join('\n')||'');
  formInput(form,'可写目录（每行一项，工程相对路径）','paths',true,task?.spec.allowed_paths.join('\n')||'');
  formInput(form,'已固定输入包SHA256（新规划任务登记时必填）','packet',false,task?.spec.source?.packet_sha256||'');
  formInput(form,'实现基点完整提交SHA（登记新规划任务时必填）','base',false,task?.spec.source?.base_commit||task?.spec.source?.base||'');
  atomicInputs(form,task);
}
function readScope(form,task) {
  const lines=name=>form.elements[name].value.split('\n').map(s=>s.trim()).filter(Boolean);
  const spec=task?structuredClone(task.spec):{id:form.elements.taskid.value.trim(),kind:'plan',parents:[],claimable:true,registered:false,priority:'P1',source:{}};
  spec.title=form.elements.title.value;spec.description=form.elements.description.value;
  spec.priority=form.elements.scope_priority.value;
  spec.deliverables=lines('deliverables').map((label,i)=>({id:'D'+(i+1),label}));spec.depends_on=lines('depends');spec.allowed_paths=lines('paths');
  if(form.elements.packet.value.trim()) spec.source.packet_sha256=form.elements.packet.value.trim();
  if(form.elements.base.value.trim()) spec.source.base_commit=form.elements.base.value.trim();
  if(form.elements.category.value) {
    spec.kind='atomic';spec.registered=true;
    spec.work={category:form.elements.category.value,role:form.elements.work_role.value,inputs_known:form.elements.inputs_known.checked,
      inputs:lines('work_inputs'),outputs:lines('work_outputs'),contracts:lines('work_contracts'),assets:lines('work_assets'),resources:lines('work_resources'),couplings:lines('work_couplings'),baseline:form.elements.base.value.trim(),acceptance:form.elements.work_acceptance.value};
    if(form.elements.planning_module.value.trim())spec.work.planning={module:form.elements.planning_module.value.trim(),purpose:form.elements.planning_purpose.value,question:form.elements.planning_question.value,no_interface_reason:form.elements.planning_no_interface_reason.value};
  }
  return spec;
}
function reviewForm(task) {
  const form=el('form',undefined,'review-form');form.append(el('h3','负责人操作'));
  const group=el('label','操作');const select=el('select');select.name='action';
  const actions={assign:'派发 / 转交',scope:'追加范围版本',accept:'验收本次提交',request_changes:'提出返修',reopen:'重新打开已验内容',merge:'记录已合入主线',native:'记录运行验收'};
  for(const [key,value] of Object.entries(actions)) { const option=el('option',value);option.value=key;
    if(['accept','request_changes','merge','native','reopen'].includes(key) && !task.latest_submission) option.disabled=true;select.append(option); }
  select.value=task.status==='submitted'?'accept':'assign';group.append(select);form.append(group);
  const dynamic=el('div');form.append(dynamic);const message=el('p','','form-message');const submit=el('button','追加记录','primary');submit.type='submit';form.append(message,submit);
  function draw() {
    dynamic.replaceChildren();const action=select.value;
    formInput(dynamic,action==='request_changes'||action==='reopen'?'返修原因':'本次说明','summary',true);
    if(action==='assign') { formInput(dynamic,'Agent负责人ID','owner',false,task.owner||'');const label=el('label',undefined,'check');const check=el('input');check.type='checkbox';check.name='registered';label.append(check,el('span','输入包及范围已固定，允许领取'));dynamic.append(label); }
    if(action==='scope') { dynamic.append(el('p','将开始新范围版本；旧提交与验收保留在历史中。','secondary'));scopeInputs(dynamic,task); }
    if(action==='accept') {
      const list=el('fieldset');list.append(el('legend','本次实际验收通过的交付项'));
      for(const id of task.latest_submission?.deliverable_ids||[]) { const label=el('label',undefined,'check');const check=el('input');check.type='checkbox';check.name='accepted';check.value=id;label.append(check,el('span',id+' · '+task.spec.deliverables.find(d=>d.id===id)?.label));list.append(label); }dynamic.append(list);evidenceInput(dynamic);
    }
    if(action==='request_changes'||action==='reopen') { formInput(dynamic,'具体问题','finding',true);formInput(dynamic,'返修验收要求','acceptance',true); }
    if(action==='merge'||action==='native') { formInput(dynamic,'已合入的完整提交SHA','commit');evidenceInput(dynamic); }
  }
  select.addEventListener('change',draw);draw();
  form.addEventListener('submit',async event=>{
    event.preventDefault();message.textContent='';submit.disabled=true;
    try {
      const current=app.tasks.find(t=>t.spec.id===task.spec.id);
      if(current?.revision!==task.revision) throw new Error('任务已有新记录，请先重新读取再决定。');
      const action=select.value;let payload;
      if(action==='assign') payload={owner:form.elements.owner.value,reason:form.elements.summary.value,registered:form.elements.registered.checked};
      if(action==='scope') payload={spec:readScope(form,task),reason:form.elements.summary.value};
      if(action==='accept') payload={submission:task.latest_submission.id,summary:form.elements.summary.value,
        deliverable_ids:Array.from(form.querySelectorAll('input[name=accepted]:checked')).map(n=>n.value),evidence:parseEvidence(form)};
      if(action==='request_changes'||action==='reopen') payload={submission:task.latest_submission.id,reason:form.elements.summary.value,
        findings:[{description:form.elements.finding.value,acceptance:form.elements.acceptance.value}]};
      if(action==='merge'||action==='native') payload={submission:task.latest_submission.id,summary:form.elements.summary.value,commit:form.elements.commit.value.trim(),evidence:parseEvidence(form)};
      await api('/api/events',{request_id:requestId(),task_id:task.spec.id,action,expected_revision:task.revision,scope_version:task.scope_version,payload});
      await refresh();await showDetail(task.spec.id);
    } catch(error) { message.textContent=error.message; } finally { submit.disabled=false; }
  });return form;
}
function createTask() {
  app.selected=null;$('detail-kind').textContent='新建范围';$('detail-title').textContent='建立可追溯的任务范围';$('stale').hidden=true;
  const body=$('detail-body');body.replaceChildren();const form=el('form',undefined,'review-form');
  formInput(form,'新任务ID（例如 plan/N-EXAMPLE）','taskid');scopeInputs(form,null);formInput(form,'设立原因','reason',true);
  const message=el('p','','form-message');const button=el('button','建立任务','primary');button.type='submit';form.append(message,button);body.append(form);
  form.addEventListener('submit',async event=>{event.preventDefault();button.disabled=true;try {
    const spec=readScope(form,null);await api('/api/events',{request_id:requestId(),task_id:spec.id,action:'create',expected_revision:0,payload:{spec,reason:form.elements.reason.value}});
    await refresh();await showDetail(spec.id);
  } catch(error) {message.textContent=error.message;} finally {button.disabled=false;}});
  $('detail').showModal();
}
function clearProject() {
  app.generation++;app.tasks=[];app.selected=null;app.etag=null;app.loading=false;app.project=null;app.role='viewer';
  if($('detail').open) $('detail').close();$('detail-body').replaceChildren();render();$('create').hidden=true;
  if(typeof clearWorkspace==='function') clearWorkspace();
}
async function selectProject(id) {
  clearProject();const project=app.projects.find(item=>item.id===id);if(!project) return;
  app.project=id;app.role=project.role;$('project-select').value=id;
  $('project-description').textContent=project.description;
  $('identity').textContent=app.admin?`全局管理员 · ${app.actor}`:`${app.role==='reviewer'?'项目审核者':'Agent'} · ${app.actor}`;
  $('create').hidden=app.role!=='reviewer';
  const params=new URLSearchParams(location.search);params.set('project',id);history.replaceState(null,'',location.pathname+'?'+params.toString());
  $('search').value='';$('kind').value='';$('priority').value='';notice('');await refresh();
}
async function loadProjects(preferred) {
  const identity=await api('/api/me',undefined,true);app.admin=identity.global_admin;app.actor=identity.actor;
  app.projects=(await api('/api/projects',undefined,true)).projects;
  const select=$('project-select');select.replaceChildren();
  for(const project of app.projects) {const option=el('option',project.name);option.value=project.id;select.append(option);}
  select.disabled=app.projects.length<2;$('new-project').hidden=!app.admin;$('logout').hidden=false;
  await selectProject(app.projects.some(p=>p.id===preferred)?preferred:app.projects[0]?.id);
}
async function handleAccess() {
  const hash=new URLSearchParams(location.hash.slice(1));const ticket=hash.get('access');
  const preferred=new URLSearchParams(location.search).get('project')||'sampleapp';clearProject();
  if(ticket) {
    history.replaceState(null,'',location.pathname+location.search);
    try {if(hash.get('kind')==='admin') await api('/api/session',{ticket},true);
      else {app.project=preferred;await api('/api/session',{ticket});}
    } catch(error) {notice(error.message);} finally {app.project=null;}
  }
  try {await loadProjects(preferred);app.connection=await api('/api/connection',undefined,true);}
  catch(error) {clearProject();app.projects=[];$('project-select').replaceChildren(el('option','请先授权'));$('project-select').disabled=true;$('new-project').hidden=true;$('logout').hidden=true;$('identity').textContent='未授权';$('project-description').textContent='请打开项目专属私有入口；网络连接本身不授予项目权限。';notice(error.message);}
}
function createProject() {
  const body=$('detail-body');body.replaceChildren();$('detail-kind').textContent='项目管理';$('detail-title').textContent='建立独立项目';$('stale').hidden=true;
  const form=el('form',undefined,'review-form');formInput(form,'项目ID（小写字母、数字、连字符）','projectid');formInput(form,'项目名称','projectname');formInput(form,'项目说明','projectdescription',true);
  form.append(el('p','新项目默认启用规划门禁。先建立上下文；模块可保留未知项，逐步调研与展开。','secondary'));
  for(const [key,label]of [['background','项目背景'],['goals','目标与成功标准'],['non_goals','非目标'],['constraints','约束'],['history_notes','历史材料说明'],['resource_notes','项目资源与准备计划']])formInput(form,label,'init_'+key,true);
  selectInput(form,'项目默认治理档位','init_governance_profile',{light:'轻量 · 可逆小项目，按任务风险升级',standard:'标准 · 多模块协作',strict:'严格 · 高风险交付'},'standard');
  formInput(form,'历史材料（每行 标题 | 位置 | 版本 | SHA256）','init_materials',true);formInput(form,'资源入口（同上格式）','init_entries',true);
  const message=el('p','','form-message');const submit=el('button','建立项目','primary');submit.type='submit';form.append(message,submit);body.append(form);
  form.addEventListener('submit',async event=>{event.preventDefault();submit.disabled=true;try {
    const knowledge={};for(const key of ['background','goals','non_goals','constraints','history_notes','resource_notes'])knowledge[key]=form.elements['init_'+key].value.trim();for(const key of ['materials','entries'])knowledge[key]=form.elements['init_'+key].value.split('\n').map(s=>s.trim()).filter(Boolean).map(s=>{const [title,location,version,sha256]=s.split('|').map(x=>x.trim());return{title,location,version,sha256};});
    const project=await api('/api/projects',{id:form.elements.projectid.value.trim(),name:form.elements.projectname.value,description:form.elements.projectdescription.value,knowledge,governance_profile:form.elements.init_governance_profile.value},true);
    $('detail').close();await loadProjects(project.id);
  }catch(error){message.textContent=error.message;}finally{submit.disabled=false;}});$('detail').showModal();
}
async function initialize() {
  await handleAccess();await refresh();
  setInterval(()=>{if(!document.hidden) refresh();},2000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden) refresh();});
}
window.addEventListener('hashchange',()=>{if(new URLSearchParams(location.hash.slice(1)).has('access')) handleAccess();});
$('project-select').addEventListener('change',()=>selectProject($('project-select').value));
$('new-project').addEventListener('click',createProject);
$('logout').addEventListener('click',async()=>{await api('/api/logout',{},true);clearProject();await handleAccess();});
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>setView(button.dataset.view)));
$('review-shortcut').addEventListener('click',()=>setView('review'));
for(const id of ['search','kind','priority']) $(id).addEventListener('input',()=>{app.limit=40;render();});
$('more').addEventListener('click',()=>{app.limit+=40;render();});
$('close-detail').addEventListener('click',()=>$('detail').close());
$('refresh-detail').addEventListener('click',()=>{if(app.selected) showDetail(app.selected.spec.id);});
$('create').addEventListener('click',createTask);
$('access').addEventListener('click',()=>{ const origin=app.connection?.url||location.origin;const endpoint=new URL(origin);const ip=app.connection?.connect_ip;const resolve=ip?` --resolve ${endpoint.hostname}:${endpoint.port}:${ip}`:'';const connect=ip?` --connect-ip ${ip}`:'';
  $('access-command').textContent=`curl --noproxy "*"${resolve} ${origin}/client.py -o task_board_client.py\n\n# 向负责人领取 project_id=${app.project||'<项目ID>'} 的专属私有身份文件\npython task_board_client.py --project ${app.project||'<项目ID>'} --profile <本机私有身份文件> projects\n\npython task_board_client.py --profile <本机私有身份文件> task <任务ID>\n\npython task_board_client.py --profile <本机私有身份文件> portal --out <Git外私有入口.html>\n\n# 按文档 prepare → post；回执和outbox均属于本项目`; $('access-dialog').showModal(); });
$('close-access').addEventListener('click',()=>$('access-dialog').close());
initialize();
