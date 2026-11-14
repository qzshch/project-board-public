'use strict';
// Primary: next action and unresolved collaboration. Secondary: fixed scope,
// input and evidence. History stays collapsed. Reuse existing semantic tokens,
// 12/16/24 spacing, native forms, one main action and responsive single columns.
const wfLabels={thread_open:'发起讨论 / 阻塞 / 偏离说明',thread_reply:'回复',thread_decide:'SE记录决策',thread_ack:'确认障碍已解决',thread_resolve:'记录解决 / 停止跟进',thread_read:'标记已读',criteria_plan:'核定结构化验收计划',criteria_claim:'声明此项验证结果',criteria_review:'审核此验收项',review_open:'提出逐条评审发现',review_disposition:'说明修复或异议',review_resolve:'复核处置',git_check:'核验实际Git证据',rollback_plan:'发起回退预览',rollback_confirm:'确认回退影响',rollback_approve:'批准执行回退',rollback_cancel:'取消回退',rollback_apply:'验收并应用回退',rollback_recover:'核对失联执行器并结束',rollback_executor:'授权项目回退执行器',criteria_defaults:'登记项目完成清单版本'};
const wfKinds={discussion:'普通讨论',blocker:'阻塞求助',deviation:'计划偏离'};
const wfStatuses={open:'待处理',awaiting_worker:'待执行者确认',resolved:'已解决',awaiting_review:'待复核',fixed:'已核验修复',dismissed:'已核验非问题',proposed:'待影响确认',approved:'已批准',running:'执行中',prepared:'候选已生成 / 部署待验收',failed:'失败（证据保留）',needs_recovery:'需SE核对并恢复',cancelled:'已取消',applied:'已应用'};
function wfButton(box,action,task,seed={},label){const b=el('button',label||wfLabels[action]);b.type='button';b.onclick=()=>wfForm(action,task,seed);box.append(b);return b;}
function wfManager(){return app.role==='reviewer';}
function wfWriter(){return app.role!=='viewer'&&!['runner','tracker','restorer'].includes(opRole());}
function wfJson(box,value){const d=el('details',undefined,'relation-details');d.append(el('summary','核对固定输入、影响与证据'),el('pre',JSON.stringify(value,null,2)));box.append(d);}
async function renderTaskWorkflow(body,task){
 const project=app.project,generation=app.generation,host=section('任务协作与逐项验收');host.id='task-workflow';body.append(host);host.append(el('p','读取当前项目协作记录…','muted'));
 try{const data=await api('/api/workflow/task?task='+encodeURIComponent(task.spec.id));if(project!==app.project||generation!==app.generation||!host.isConnected)return;host.dataset.revision=data.revision;host.replaceChildren(el('h3','任务协作与逐项验收'));renderTaskConvergence(host,task);const continuation=el('details',undefined,'relation-details');continuation.open=!!ws.ops?.cv_attempt_policies?.[task.spec.id]||!!ws.ops?.co_plan_policy?.[task.spec.id]||Object.values(ws.ops?.co_checkpoints||{}).some(e=>e.task===task.spec.id);continuation.append(el('summary','实施计划、检查点与增量评审'));host.append(continuation);renderTaskContinuation(continuation,task);
  if(data.blockers.length)host.append(el('p',data.blockers.join('\n'),'notice detail-text'));
  const controls=el('div',undefined,'graph-controls');host.append(controls);if(wfWriter())wfButton(controls,'thread_open',task.spec.id,fAttemptSeed(task.spec.id));if(wfManager())wfButton(controls,'criteria_plan',task.spec.id);wfButton(controls,'rollback_plan',task.spec.id,{},'查看 / 发起回退').hidden=!wfManager();
  const threads=section('讨论、阻塞与计划偏离');host.append(threads);
  if(!Object.keys(data.threads).length)threads.append(el('p','尚无评论。遇到阻塞可暂停相关步骤并请求SE决定；独立范围仍按原授权执行。','muted'));
  for(const th of Object.values(data.threads).reverse()){
   const card=el('article',undefined,'resource-card');card.dataset.thread=th.id;card.append(el('h4',th.title),el('p',`${wfKinds[th.kind]} · ${wfStatuses[th.status]} · 未读 ${data.unread[th.id]||0}\n影响步骤：${th.affected_step}`,'secondary detail-text'));
   for(const m of th.messages.slice(-5))card.append(el('p',`${m.actor} · ${new Date(m.at*1000).toLocaleString()}\n${m.body}`,'detail-text'));
   if(th.messages.length>5)wfJson(card,th.messages);
   const buttons=el('div',undefined,'graph-controls');card.append(buttons);
   if(wfWriter()){wfButton(buttons,'thread_reply',task.spec.id,{thread:th.id});wfButton(buttons,'thread_read',task.spec.id,{thread:th.id,count:th.messages.length});
    if(wfManager()&&th.status!=='resolved'){wfButton(buttons,'thread_decide',task.spec.id,{thread:th.id});wfButton(buttons,'thread_resolve',task.spec.id,{thread:th.id});}
    if((task.owner===app.actor||th.author===app.actor&&fParticipant(task))&&th.status==='awaiting_worker')wfButton(buttons,'thread_ack',task.spec.id,{thread:th.id,...fAttemptSeed(task.spec.id)});}
   if(wfWriter())coButton(card,'intake_open',null,{title:th.title,body:th.messages[0]?.body||'',sources:[{kind:'thread',id:th.id}]},'需要独立跟踪时转为需求');threads.append(card);
  }
  const ac=section('结构化验收标准');host.append(ac);const plan=data.current_plan;if(plan){if(wfWriter()&&task.owner===app.actor)fBatchButton(ac,task,data,false);if(wfManager())fBatchButton(ac,task,data,true);}
  if(!plan)ac.append(el('p','此范围尚未核定结构化验收计划；历史验收不自动补造。','muted'));
  else{ac.append(el('p',`${plan.id} · 固定范围 v${plan.scope_version} · ${plan.git_required?'要求实际Git核验':'按产物或检查验证'}`,'secondary'));
   for(const c of plan.items){const key=plan.id+':'+c.id,claim=data.claims[key],verdict=data.verdicts[key],row=el('article',undefined,'resource-card');row.dataset.criterion=c.id;row.append(el('h4',c.id+' · '+c.expected),el('p',`${c.deliverable} · ${c.method} · ${verdict&&claim&&verdict.claim===claim.id?verdict.result:'待验证 / 审核'}`,'secondary'));
    if(claim)row.append(el('p',claim.input_anchor+'\n'+claim.summary,'detail-text'));if(verdict)row.append(el('p','审核：'+verdict.summary,'detail-text'));
    if(wfWriter()&&task.owner===app.actor)wfButton(row,'criteria_claim',task.spec.id,{plan:plan.id,criterion:c.id,input_anchor:claim?.input_anchor||'git:'+(task.latest_submission?.implementation_commit||task.spec.work?.baseline||'')});
    if(wfManager()&&claim)wfButton(row,'criteria_review',task.spec.id,{plan:plan.id,criterion:c.id,claim:claim.id});ac.append(row);}
  }
  const findings=section('逐条评审与返修');host.append(findings);if(wfManager()||opRole()==='tester')wfButton(findings,'review_open',task.spec.id);
  for(const f of Object.values(data.findings)){const row=el('article',undefined,'resource-card');row.dataset.finding=f.id;row.append(el('h4',f.description),el('p',`${f.id} · ${f.blocking?'阻塞交付':'建议'} · ${wfStatuses[f.status]}\n验证要求：${f.acceptance}\n${f.anchor.path||f.anchor.resource||'任务范围'} ${f.anchor.line||''}`,'detail-text'));
   if(f.disposition)row.append(el('p','执行者：'+f.disposition.summary,'detail-text'));if(f.resolution)row.append(el('p','复核：'+f.resolution.summary,'detail-text'));
   if(wfWriter()&&task.owner===app.actor)wfButton(row,'review_disposition',task.spec.id,{finding:f.id,input_anchor:'git:'+(task.latest_submission?.implementation_commit||task.spec.work?.baseline||'')});
   if(wfManager()&&f.disposition)wfButton(row,'review_resolve',task.spec.id,{finding:f.id,disposition:f.disposition.id});if(wfWriter())coButton(row,'intake_open',null,{title:f.description,body:f.acceptance,sources:[{kind:'finding',id:f.id}]},'需另立范围时转为需求');wfJson(row,f.history);findings.append(row);}
  const git=section('实际Git核验');host.append(git);if(wfWriter()&&(wfManager()||task.owner===app.actor))wfButton(git,'git_check',task.spec.id,{repo:plan?.repo||Object.keys(ws.git?.repos||{})[0]||'',baseline:task.spec.work?.baseline||'',implementation:task.latest_submission?.implementation_commit||'',target:task.latest_submission?.implementation_commit||''});
  if(wfWriter()&&(wfManager()||task.owner===app.actor)){const b=el('button','同一输入分阶段核验');b.onclick=()=>wfForm('git_check_batch',task.spec.id,{repo:plan?.repo||Object.keys(ws.git?.repos||{})[0]||'',baseline:task.spec.work?.baseline||'',implementation:task.latest_submission?.implementation_commit||'',target:task.latest_submission?.implementation_commit||'',phases:['submit']});git.append(b);}
  for(const check of Object.values(data.checks).reverse()){git.append(el('p',`${check.phase} · ${check.target}\n实际文件 ${check.files.length} 项 · 精确输入通过运行 ${check.exact_input_runs.length} 项\n${check.observation}`,'detail-text'));wfJson(git,check);}
  for(const rollback of Object.values(data.rollbacks))renderRollback(host,rollback);
 }catch(error){if(host.isConnected&&app.project===project)host.append(el('p',error.message,'notice'));}
}
function renderRollback(box,p){const row=section(`回退 ${p.id} · ${wfStatuses[p.status]}`);row.dataset.rollback=p.id;row.append(el('p',`${p.kind} · ${p.object} → ${p.target}\n${p.reason}\n受影响任务：${p.affected_tasks.join('、')}\n需确认：${p.required.join('、')} · 已确认：${Object.keys(p.confirmations).join('、')||'无'}`,'detail-text'));wfJson(row,p);
 const controls=el('div',undefined,'graph-controls');row.append(controls);const seed={id:p.id,manifest_hash:p.manifest_hash},tid=p.affected_tasks[0];
 if(wfWriter()&&p.status==='proposed'&&p.required.includes(app.actor))wfButton(controls,'rollback_confirm',tid,seed);
 if(wfManager()){if(p.status==='proposed')wfButton(controls,'rollback_approve',tid,seed);if(['proposed','approved','prepared','running'].includes(p.status))wfButton(controls,'rollback_cancel',tid,{id:p.id});
  if(p.status==='approved'&&!p.commits.length&&p.kind!=='deploy'||p.status==='prepared')wfButton(controls,'rollback_apply',tid,{...seed,commit:p.result?.commit||''});if(['running','needs_recovery'].includes(p.status))wfButton(controls,'rollback_recover',tid,{id:p.id});}
 if(p.status==='approved'&&(p.commits.length||p.kind==='deploy'))row.append(el('p','由项目restorer使用本机批准配置执行 tools/rollback_runner.py；候选需验证并进入授权目标后，由SE应用。网页不能提交命令或目录。','secondary'));
 box.append(row);}
async function renderWorkflowInbox(box){
 const project=app.project,generation=app.generation,host=section('当前项目 · SE待办与协作');box.append(host);
 try{const [d,cv]=await Promise.all([api('/api/workflow'),api('/api/convergence')]);if(project!==app.project||generation!==app.generation||!host.isConnected)return;
  host.querySelector('h3').textContent=cv.workbench.role==='se'?'SE工作台 · 当前下一步':'执行工作台 · 当前下一步';
  host.append(el('p','待办由项目权限、评论和交付门禁生成；等待不等于投入，评论不等于范围授权。','secondary'));
  const tools=el('div',undefined,'graph-controls');host.append(tools);if(wfManager()){wfButton(tools,'rollback_plan',null);wfButton(tools,'criteria_defaults',null);wfButton(tools,'rollback_executor',null);}
  if(!cv.workbench.items.length)host.append(el('p','当前没有待处理事项。','empty'));
  for(const item of cv.workbench.items){const row=el('article',undefined,'resource-card');row.dataset.inbox=item.kind;row.append(el('h4',item.title),el('p',`${item.task||item.id} · ${wfStatuses[item.status]||item.status}${item.unread?' · 未读 '+item.unread:''}${item.waiting_seconds!==undefined?' · 等待 '+hours(item.waiting_seconds):''}`,'secondary'));if(item.reason)row.append(el('p',item.reason,'secondary'));if(item.task){const b=el('button','打开相关任务');b.onclick=()=>showDetail(item.task);row.append(b);}else{const b=el('button',item.kind==='rule'?'打开治理规则':'打开规划与模板');b.onclick=()=>selectWorkspacePanel(item.kind==='rule'?'policy':'planning');row.append(b);}if(item.action){if(cvLabels[item.action])cvButton(row,item.action,item.task||null,item.seed);else coButton(row,item.action,item.task||null,item.seed);}host.append(row);}
  for(const [title,items]of [['我正在执行',cv.workbench.my_tasks],['可领取与阻塞原因',cv.workbench.claimable]]){const group=section(title);if(!items.length)group.append(el('p','当前无任务。','muted'));for(const t of items){const b=el('button',t.title+' · '+t.id);b.onclick=()=>showDetail(t.id);group.append(b);if(t.blockers?.length)group.append(el('p',t.blockers.join('；'),'secondary'));}host.append(group);}
  const history=el('details',undefined,'relation-details');history.append(el('summary','已结束回退历史'));for(const p of Object.values(d.rollbacks).reverse())renderRollback(['applied','cancelled','failed'].includes(p.status)?history:host,p);if(history.children.length>1)host.append(history);
 }catch(error){if(host.isConnected)host.append(el('p',error.message,'notice'));}
}
const wfFields={
 thread_open:[['id','线程ID','id'],['kind','评论类型','select',wfKinds],['title','主题'],['body','障碍、已尝试方法或偏离原因','text'],['affected_step','受影响步骤 / 独立部分'],['to','接收人Actor，每行一项；SE表示项目负责人','lines'],['pause','暂停相关工作并开始记录等待','bool']],
 thread_reply:[['thread','线程ID'],['body','回复内容','text']],thread_decide:[['thread','线程ID'],['decision','决策','select',{continue:'按当前授权继续',changes:'按已登记正式变更继续',stop:'保持暂停'}],['summary','结论、依据与边界','text'],['reference','正式scope事件ID，或治理序号:哈希；无变更留空']],
 thread_ack:[['thread','线程ID'],['summary','已核对的输入、决策与解决情况','text']],thread_resolve:[['thread','线程ID'],['summary','解决 / 停止跟进依据','text']],thread_read:[['thread','线程ID'],['count','已读到第几条消息','number']],
 criteria_defaults:[['id','清单不可变版本ID','id'],['items','项目完成要求，每行一项','lines'],['reason','登记依据','text']],
 criteria_plan:[['id','验收计划不可变ID','id'],['items','每行 标准ID | 交付项ID | inspection/manual/automated | 可判定预期','criteria'],['defaults','完成清单版本；不填则固定当前项目默认版本'],['git_required','要求实际Git核验','bool'],['repo','项目仓库ID；不要求Git时留空'],['reason','覆盖与验证选择依据','text']],
 criteria_claim:[['plan','固定验收计划'],['criterion','标准ID'],['input_anchor','本次精确输入 git:提交 或 sha256:产物'],['summary','实际验证结果','text'],['runs','通过的运行ID，每行一项','lines'],['evidence','每行 证据位置 | 实际SHA256，可空','evidence']],
 criteria_review:[['plan','固定验收计划'],['criterion','标准ID'],['claim','被审核的声明ID'],['result','结论','select',{passed:'通过',failed:'不通过'}],['summary','实际核对与结论','text'],['evidence','每行 证据位置 | SHA256，可空','evidence']],
 review_open:[['id','发现稳定ID','id'],['criterion','关联标准ID，可空'],['description','具体问题','text'],['acceptance','复现与返修验收要求','text'],['blocking','阻塞交付','bool'],['anchor','锚点JSON：commit/path/line/resource','json'],['previous','继承的旧发现ID，可空']],
 review_disposition:[['finding','发现ID'],['status','处置声明','select',{fixed:'已修复，等待审核',rejected:'提出异议，等待审核'}],['input_anchor','精确验证输入'],['summary','修复或可证伪事实依据','text'],['runs','通过运行ID，每行一项','lines'],['evidence','每行 证据位置 | SHA256，可空','evidence']],
 review_resolve:[['finding','发现ID'],['disposition','最新处置ID'],['result','复核结论','select',{fixed:'核验修复',dismissed:'核验为非问题',reopen:'仍需修复'}],['summary','复核事实依据','text'],['evidence','每行 证据位置 | SHA256，可空','evidence']],
 git_check:[['repo','项目仓库ID'],['baseline','任务固定基线提交'],['implementation','本次实现提交'],['target','本阶段精确目标提交'],['phase','阶段','select',{submit:'交付 / 验收',merge:'合入',native:'运行验收'}],['reason','核验依据','text']],
 rollback_plan:[['id','回退单ID','id'],['kind','回退对象类型','select',{task:'任务范围 / 成果',module:'模块规划版本',code:'Git提交',deploy:'批准部署目标',asset:'固定资产消费'}],['object','任务ID / 模块ID / 部署目标ID / 消费引用'],['target','历史scope事件ID或current / 模块@版本 / 发布ID / 资产引用'],['tasks','影响起点任务ID，每行一项','lines'],['repo','代码仓库ID，无代码回退留空'],['target_ref','目标完整分支引用，无代码回退留空'],['base','当前分支完整提交，无代码回退留空'],['commits','需反向提交的完整SHA，每行一项','lines'],['mainlines','合并主线JSON映射，无则 {}','json'],['mapping','提交SHA到归属任务数组JSON，无则 {}','json'],['reason','为什么回退','text'],['data_plan','数据、接口、原件与备份处置；无影响也说明依据','text'],['tests','回退验证与部署读回方案','text']],
 rollback_confirm:[['id','回退单ID'],['manifest_hash','固定方案SHA'],['summary','已核对的影响与处置','text']],rollback_approve:[['id','回退单ID'],['manifest_hash','固定方案SHA'],['summary','批准依据','text']],rollback_cancel:[['id','回退单ID'],['summary','取消原因','text']],
 rollback_apply:[['id','回退单ID'],['manifest_hash','固定方案SHA'],['summary','实际验收结论','text'],['runs','精确最终提交的通过运行ID，每行一项','lines'],['commit','实际最终提交；无代码/部署留空'],['evidence','每行 证据位置 | SHA256','evidence']],rollback_recover:[['id','回退单ID'],['summary','核对过期执行者进程、工作区和资源后的处置','text'],['evidence','每行 证据位置 | SHA256','evidence']],
 rollback_executor:[['actor','已签发restorer角色Actor'],['kinds','允许code/deploy，每行一项','lines'],['targets','批准仓库ID或部署目标ID，每行一项','lines'],['enabled','启用','bool'],['reason','范围与授权依据','text']]
};
async function wfForm(action,taskId,seed={}){
 fPrepareFields(action);
 const project=app.project,generation=app.generation,body=resourceDialog(wfLabels[action]);let state,task;
 try{state=await api('/api/operations');if(taskId)task=await api('/api/task?id='+encodeURIComponent(taskId));if(!validResourceDialog(body,project,generation))return;}catch(error){if(body.isConnected)body.append(el('p',error.message,'notice'));return;}
 const form=el('form',undefined,'review-form');body.append(form);const defaults={id:action.replaceAll('_','-')+'-'+requestId().slice(0,8),kind:action==='rollback_plan'?'task':'discussion',to:['SE'],pause:false,affected_step:'整个任务 / 请明确步骤',items:action==='criteria_plan'?(task?.spec.deliverables||[]).map((d,i)=>({id:'AC'+(i+1),deliverable:d.id,method:'manual',expected:d.label})):[],git_required:false,repo:'',anchor:{commit:'',path:'',line:0,resource:''},blocking:true,mainlines:{},mapping:{},object:taskId||'',target:'current',tasks:taskId?[taskId]:[],commits:[],runs:[],evidence:[],defaults:'',previous:'',reference:'',criterion:'',enabled:true,...seed};
 for(const [key,label,type,options]of wfFields[action]){let value=defaults[key]??'';
  if(type==='select')selectInput(form,label,key,options,value||Object.keys(options)[0]);else if(type==='bool')selectInput(form,label,key,{true:'是',false:'否'},String(value));else{
   if(type==='json')value=JSON.stringify(value,null,2);else if(type==='criteria')value=value.map(c=>[c.id,c.deliverable,c.method,c.expected].join(' | ')).join('\n');else if(type==='evidence')value=value.map(e=>e.path+' | '+e.sha256).join('\n');else if(type==='lines')value=Array.isArray(value)?value.join('\n'):value;
   formInput(form,label,key,['text','json','lines','criteria','evidence'].includes(type),value);}
 }
 if(['draft_save','template_register'].includes(action))cvDraftEditor(form,defaults.items);if(action==='intake_convert')fAttachSpec(form,defaults.spec);if(['thread_open','thread_ack','checkpoint'].includes(action))fOptionalFields(form,['attempt_id','attempt_lease','selection_id']);
 body.append(el('p','评论不授予越界修改权限；回退先确认影响，不删除历史或执行网页提供的命令。','secondary'));const message=el('p','','form-message'),save=el('button','追加'+wfLabels[action],'primary');save.type='submit';form.append(message,save);let frozen=null;
 form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{if(!validResourceDialog(body,project,generation))throw new Error('项目或窗口已变化');if(!frozen){const p={};
   for(const [key,,type]of wfFields[action]){let value=form.elements[key].value.trim();if(type==='bool')value=value==='true';else if(type==='number')value=Number(value);else if(type==='json')value=JSON.parse(value);else if(type==='lines')value=value.split('\n').map(s=>s.trim()).filter(Boolean);else if(type==='evidence')value=value.split('\n').map(s=>s.trim()).filter(Boolean).map(s=>{const [path,sha256]=s.split('|').map(x=>x.trim());return {path,sha256};});else if(type==='criteria')value=value.split('\n').map(s=>s.trim()).filter(Boolean).map(s=>{const [id,deliverable,method,...expected]=s.split('|').map(x=>x.trim());return {id,deliverable,method,expected:expected.join(' | ')};});p[key]=value;}
   if(task&&['thread_open','criteria_plan','criteria_claim','criteria_review','review_open','review_disposition','review_resolve','git_check',...coScopeActions,...cvScopeActions,'git_check_batch'].includes(action))Object.assign(p,{task:task.spec.id,scope:task.scope_hash,scope_version:task.scope_version});
   frozen={request_id:requestId(),expected_revision:state.revision,action,payload:p};}
  await api('/api/operations',frozen);if(!validResourceDialog(body,project,generation))return;await refreshWorkspace(generation);if(taskId){const fresh=await api('/api/task?id='+encodeURIComponent(taskId));if(app.project!==project||app.generation!==generation)return;app.tasks=app.tasks.map(t=>t.spec.id===taskId?fresh:t);await showDetail(taskId);}else $('detail').close();
 }catch(error){if(error.status===400||error instanceof SyntaxError)frozen=null;if(validResourceDialog(body,project,generation))message.textContent=error.message;}finally{save.disabled=false;}};
}
