'use strict';
// Primary: effective risk, time bottlenecks and current verification. Secondary:
// actual records and next permitted action. Tertiary: history. One management
// action per panel, using existing surface/ink/secondary/muted and spacing tokens.
const tierNames={light:'轻量',standard:'标准',strict:'严格'};
const phaseNames={research:'调研',design:'设计',implementation:'实现',testing:'测试',review:'审核',integration:'集成',release:'发布',asset:'资产提炼',governance:'治理协调'};
const opLabels={policy:'设置项目治理档位',assess:'核定任务风险',assess_package:'批量核定任务包风险',estimate:'登记 / 调整估算',benchmark_import:'采用已固定共享工时基准',time_change:'记录作业 / 等待 / 暂停',time_complete:'确认时间记录完整',time_correct:'校正已结束时段',time_close:'关闭遗留时段',case:'登记测试用例版本',suite:'批准自动化套件版本',case_retire:'弃用 / 撤回用例版本',test_plan:'核定任务测试计划',runner:'授权项目执行器',run_request:'申请自动化测试',run_cancel:'取消测试运行',manual_run:'记录实际手工检验',candidate:'提议资产候选版本',candidate_refine:'提炼候选资产',candidate_validate:'核验提炼结果',candidate_promote:'登记已验证私有版本',candidate_retire:'弃用候选版本',asset_feedback:'记录消费反馈'};
const opFields={
  policy:['项目默认档位|profile','采用 / 调整依据|reason'],
  assess:['任务ID|task','任务档位|level','风险标记，每行一项|flags','影响面与裁剪依据|reason'],
  assess_package:['任务包ID|package','任务档位|level','风险标记，每行一项|flags','任务包裁剪依据|reason'],
  estimate:['任务ID|task','乐观投入（分钟）|low','通常投入（分钟）|likely','保守投入（分钟）|high','计划完成时间（带时区ISO），可留空|due','任务规模|size','不确定性|uncertainty','执行者/模型、工具、环境与复用背景|context','估算或重估依据|reason'],
  benchmark_import:['本项目已批准消费的基准资产引用ID|asset','完整基准JSON文档（保留末尾换行，SHA需匹配固定消费）|document','采用依据|reason'],
  time_change:['任务ID|task','当前状态|mode','工作阶段|phase','作业或等待的具体原因|reason','是否返修|rework'],
  time_complete:['任务ID|task','确认当前范围时间记录完整的说明|summary'],
  time_correct:['时段ID|session','核实后的有效秒数|seconds','校正依据|reason'],time_close:['时段ID|session','关闭原因|reason'],
  case:['用例ID|id','不可覆盖版本|version','用例名称|title','用例类型|kind','重要性|priority','覆盖对象，每行 task:ID / module:ID@版本 / contract:ID@版本|targets','前置条件|preconditions','输入与固定数据版本|inputs','操作步骤|steps','预期行为与反例|expected','执行环境标识|environment','排他资源，每行一项|resources'],
  case_retire:['用例 id@版本|ref','处置方式 deprecated / withdrawn|mode','弃用或撤回依据|reason'],
  suite:['套件ID|id','不可覆盖版本|version','逐用例命令：每行 用例@版本 | 参数JSON数组（{python}表示执行器Python）|commands','执行环境标识|environment','排他资源，每行一项|resources','总超时（秒，最多900）|timeout_seconds','需核验并保留的产物相对路径，每行一项|artifact_paths'],
  test_plan:['任务ID|task','需通过的用例@版本，每行一项|cases','覆盖与选择依据|reason'],
  runner:['已登记runner角色Actor ID|actor','执行环境标识|environment','是否启用|enabled','授权或撤销依据|reason'],
  run_request:['任务ID，每行一项；可一次验证多张任务卡|tasks','套件@版本|suite','固定输入 git:完整提交|input_anchor','运行依据|reason'],
  run_cancel:['运行ID|run','取消原因|reason'],
  manual_run:['任务ID，每行一项|tasks','固定输入 git:提交 或 sha256:产物摘要|input_anchor','检验依据|reason','逐用例结果：用例@版本 | passed/failed/blocked | 秒数 | 实际结果|results','核验产物：相对路径 | SHA256 | 归档位置，可空|artifacts','证据：路径 | SHA256|evidence'],
  candidate:['候选ID|id','不可覆盖版本|version','候选名称|title','资产类型|kind','来源任务ID，每行一项|source_tasks','解决的问题|problem','适用条件|applicability','不适用范围|exclusions','依赖，每行一项|dependencies','维护者Actor ID|owner'],
  candidate_refine:['候选 id@版本|ref','验证输入 git:提交 或 sha256:产物|input_anchor','套件内核验的产物相对路径|artifact_path','产物SHA256|sha256','许可|license','敏感性|sensitivity','本项目产物位置|location','具备共享资格（仍需审核发布）|shareable','提炼与去耦说明|summary'],
  candidate_validate:['候选 id@版本|ref','通过的验证运行ID，每行一项|runs','实际复用验证结论|summary'],
  candidate_promote:['候选 id@版本|ref','登记依据|summary','证据：路径 | SHA256|evidence'],candidate_retire:['候选 id@版本|ref','弃用及影响处置|reason'],
  asset_feedback:['任务实际消费的资产引用ID|asset','消费任务ID|task','消费结果|outcome','实测接入分钟|integration_minutes','预估节省分钟，未知可空|estimated_saved_minutes','问题与维护反馈|issues']
};
function hours(s){return s===null||s===undefined?'未知':s<60?s.toFixed(1)+' 秒':s<3600?(s/60).toFixed(1)+' 分钟':(s/3600).toFixed(2)+' 小时';}
function opRole(){return ws.data.members[app.actor]?.role||(app.role==='reviewer'?'reviewer':'agent');}
function opActions(){
  if(app.role==='reviewer')return {policy:['policy','assess','assess_package'],time:['estimate','time_change','time_complete','time_correct','time_close','benchmark_import'],quality:['case','case_retire','suite','test_plan','runner','run_request','manual_run','run_cancel'],assets:['candidate','candidate_refine','candidate_validate','candidate_promote','candidate_retire','asset_feedback']}[ws.panel]||[];
  return {time:['estimate','time_change','time_complete'],quality:opRole()==='tester'?['case','run_request','manual_run','run_cancel']:['run_request','run_cancel'],assets:['candidate','asset_feedback']}[ws.panel]||[];
}
function operationButton(box,label,action,seed={}){const b=el('button',label);b.onclick=()=>editOperations(action,seed);box.append(b);}
function renderOperations(box){
  const o=ws.ops;if(!o)return;const active=o.policy.enabled;
  if(ws.panel==='policy'){
    cards(box,[['项目默认',active?tierNames[o.policy.profile]:'历史行为，尚未采用分级策略'],['策略依据',o.policy.reason]]);
    box.append(el('p','项目档位是默认值；SE可按当前任务影响面裁剪。权限、持久化数据、生产与共享资产等已知高风险不得降级。风险评估随范围版本失效。','secondary'));
    listLines(box,'当前任务风险与门禁',Object.entries(o.effective),([tid,r])=>`${tid} · ${tierNames[r.level]} · ${r.assessed?'当前范围已核定':'待核定'}\n风险：${r.flags.join('、')||'未声明共享影响'}\n依据：${r.reason}`);
  }
  if(ws.panel==='time'){
    const t=o.time_report;cards(box,[['申报有效投入',hours(t.work_seconds)],['等待',hours(t.wait_seconds)],['返修（投入子集）',hours(t.rework_seconds)],['治理与协调',hours(t.phases_seconds.governance||0)]]);
    box.append(el('p',`统计截至 ${new Date(t.as_of*1000).toLocaleString()}。投入与自然历时分别记录；空白历史不是零工时。`,'muted'));
    const refresh=el('button','刷新统计');refresh.onclick=()=>renderWorkspace();box.append(refresh);
    if(app.role!=='viewer'&&opRole()!=='runner')operationButton(box,'时间记录与估算',null);
    listLines(box,'人员与Agent投入',Object.entries(t.actor_kind_seconds),([kind,s])=>`${{human:'人员',agent:'Agent',unknown:'未分类'}[kind]} · ${hours(s)}`);
    listLines(box,'阶段投入',Object.entries(t.phases_seconds),([phase,s])=>`${phaseNames[phase]} · ${hours(s)}`);
    listLines(box,'待验证的改进方向',t.opportunities,r=>`${r.observation} · ${hours(r.seconds)}\n${r.suggestion}`);
    listLines(box,'自动化运行成本（不并入申报投入）',Object.entries(t.automation_runtime),([suite,r])=>`${suite} · ${r.runs} 次运行 · ${r.failures} 次失败/超时/受阻\n执行 ${hours(r.seconds)} · 队列等待 ${hours(r.queue_seconds)}`);
    listLines(box,'等待原因',Object.entries(t.waiting_seconds).sort((a,b)=>b[1]-a[1]),([reason,s])=>`${reason} · ${hours(s)}`);
    const cp=t.critical_path;listLines(box,'硬前置估算路径',[cp],r=>`${r.unknown_tasks?'估算尚不完整 · '+r.unknown_tasks+' 项缺少当前估算':'当前估算最长路径'}\n${r.path.join(' → ')||'暂无路径'} · ${r.minutes===null?'未知':r.minutes+' 分钟'}\n不包含设备、端口和审核排队；不能作为承诺交期。`);
    listLines(box,'任务投入、历时与估算',t.tasks,r=>`${r.task} · 投入 ${hours(r.work_seconds)} · 观察历时 ${hours(r.observed_elapsed_seconds)}${r.open?' · 有未结束时段':''}\n估算 ${r.estimated_minutes===null?'未知':r.estimated_minutes+' 分钟'}${r.estimate_current?'':'（非当前范围）'} · ${r.time_complete?'已确认记录完整':'完整性未确认'}${r.overdue?' · 已超计划窗口':''}`);
    listLines(box,'相似历史校准',Object.entries(t.forecasts),([tid,r])=>`${tid} · ${r.samples} 个参考样本 · 来源 ${r.source}\n${r.p50_minutes===null?'样本不足，暂不生成分位估计':`P50 ${r.p50_minutes.toFixed(1)} / P80 ${r.p80_minutes.toFixed(1)} 分钟`}`);
    relationDetails(box,'已采用的固定共享基准',Object.entries(o.benchmarks),([alias,r])=>`${alias} → ${r.release} · ${r.available?'可用于参考':'不可用/已撤回'}\nSHA256 ${r.sha256}\n采用依据：${r.reason}`);
    relationDetails(box,'时段与校正记录',Object.entries(o.sessions),([sid,r])=>`${sid} · ${r.actor} · ${r.task}\n${r.mode} / ${phaseNames[r.phase]} · ${r.reason} · ${r.end?'已结束':'进行中'} · 校正 ${r.corrections.length} 次`);
    relationDetails(box,'估算与调整记录',Object.entries(o.estimates).flatMap(([task,rows])=>rows.map(r=>({task,...r}))),r=>`${r.task} · ${r.low} / ${r.likely} / ${r.high} 分钟\n${r.context}\n依据：${r.reason} · ${new Date(r.at*1000).toLocaleString()}`);
  }
  if(ws.panel==='quality'){
    const running=Object.values(o.runs).filter(r=>r.status==='running'||r.status==='cancel_requested');cards(box,[['用例版本',String(Object.keys(o.cases).length)],['待执行',String(Object.values(o.runs).filter(r=>r.status==='queued').length)],['执行中',String(running.length)],['实际通过',String(Object.values(o.runs).filter(r=>r.status==='passed').length)]]);
    box.append(el('p','自动化命令仅由本机批准套件摘要的项目执行器运行。固定输入、范围、租约和真实退出码与产物SHA一并回传；失败与重试保留。','secondary'));
    if(opRole()==='tester')operationButton(box,'登记用例','case');
    for(const [rid,r]of Object.entries(o.runs).reverse()){
      const s=section(`${r.status} · ${rid}`);s.append(el('p',`${r.suite||'实际手工检验'} · ${r.input_anchor}\n任务：${Object.keys(r.scopes).join('、')}\n${r.summary||r.reason}`,'detail-text'));
      listLines(s,'逐用例结果',r.results,c=>`${c.case} · ${c.status} · ${c.seconds} 秒 · 退出码 ${c.exit_code??'手工检验'}\n${c.summary}`);
      if(!['passed','failed','blocked','timeout','cancelled'].includes(r.status)&&app.role==='reviewer')operationButton(s,'请求取消','run_cancel',{run:rid});
      box.append(s);
    }
    relationDetails(box,'测试计划',Object.values(o.test_plans),r=>`${r.task} · ${r.cases.join('、')}\n${r.reason}`);
    relationDetails(box,'用例库',Object.entries(o.cases),([ref,r])=>`${ref} · ${r.title} · ${r.kind}/${r.priority} · ${o.case_status[ref].status}\n覆盖 ${r.targets.join('、')}\n前置：${r.preconditions}\n输入：${r.inputs}\n步骤：${r.steps}\n预期：${r.expected}`);
    relationDetails(box,'已批准自动套件与本机批准摘要',Object.entries(o.suites),([ref,r])=>`${ref} · ${r.environment} · ${r.timeout_seconds} 秒\n本机需核对批准 SHA256 ${r.manifest_hash}\n用例 ${r.commands.map(c=>c.case).join('、')}`);
    relationDetails(box,'项目执行器',Object.values(o.runners),r=>`${r.actor} · ${r.environment} · ${r.enabled?'已授权':'已停用'}`);
  }
}
function renderAssetLearning(box){
  if(!ws.ops)return;
  box.append(el('p','交付成果 → 候选 → 提炼 → 实际验证 → 私有版本 → 审核共享。实测接入成本与预估节省分别记录。','secondary'));
  if(app.role!=='viewer'&&opRole()!=='runner')operationButton(box,'管理资产沉淀',null);
  listLines(box,'候选与提炼阶段',Object.entries(ws.ops.candidates),([ref,c])=>`${ref} · ${c.title} · ${c.stage}\n解决：${c.problem}\n适用：${c.applicability}\n不适用：${c.exclusions}\n来源：${c.source_tasks.join('、')} · 维护者 ${c.owner}\n验证运行 ${c.validation_runs.join('、')||'尚无'}`);
  listLines(box,'实际消费反馈',ws.ops.usage,r=>`${r.asset} · ${r.task} · ${r.outcome}\n实测接入 ${r.integration_minutes} 分钟 · 预估节省 ${r.estimated_saved_minutes===null?'未知':r.estimated_saved_minutes+' 分钟'}\n${r.issues}`);
}
function editOperations(fixed,seed={}){
  const choices=fixed?[fixed]:opActions();if(!choices.length)return;
  app.selected=null;$('detail-title').textContent='项目操作';$('detail-kind').textContent='范围、版本与实际记录';$('stale').hidden=true;const body=$('detail-body');body.replaceChildren();const form=el('form',undefined,'review-form');
  const choose=selectInput(form,'操作','op_action',Object.fromEntries(choices.map(k=>[k,opLabels[k]])),fixed||choices[0]);const dynamic=el('div');form.append(dynamic);
  const enums={profile:tierNames,level:tierNames,phase:phaseNames,mode:{work:'有效作业',wait:'等待',pause:'暂停',stop:'结束当前时段'},size:{small:'小',medium:'中',large:'大'},uncertainty:{low:'低',medium:'中',high:'高'},outcome:{succeeded:'复用成功',failed:'复用失败'},sensitivity:{private:'项目私有',public:'可审核共享',secret:'敏感'}};
  function draw(){dynamic.replaceChildren();const action=choose.value;for(const row of opFields[action]){const at=row.lastIndexOf('|'),key=row.slice(at+1),label=row.slice(0,at);let value=seed[key]??'';if(Array.isArray(value))value=value.join('\n');let options=key==='mode'&&action==='case_retire'?{deprecated:'弃用（旧固定计划保留）',withdrawn:'撤回（不再允许用于验收）'}:enums[key];if(['enabled','rework','shareable'].includes(key))options={false:'否',true:'是'};if(key==='kind')options=action==='case'?{manual:'手工检验',automated:'自动化测试'}:{skill:'技能',methodology:'方法',infrastructure:'基建',test_case:'测试用例',test_data:'测试数据',test_tool:'测试工具',private:'项目专用'};if(key==='priority')options={normal:'普通',critical:'关键'};if(options)selectInput(dynamic,label,key,options,String(value));else formInput(dynamic,label,key,true,value);}}
  choose.onchange=draw;draw();const message=el('p','','form-message'),save=el('button','保存当前操作','primary');save.type='submit';form.append(message,save);body.append(form);const revision=ws.ops.revision,project=app.project,generation=app.generation,taskScopes=new Map(app.tasks.map(t=>[t.spec.id,t.scope_hash])),packages=structuredClone(ws.data.packages);let frozenRequest=null;
  form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{
    if(app.project!==project||app.generation!==generation)throw new Error('项目身份已变化，请关闭并重新读取');
    const action=choose.value,p={};for(const row of opFields[action]){const key=row.slice(row.lastIndexOf('|')+1);p[key]=key==='document'?form.elements[key].value:form.elements[key].value.trim();}
    for(const key of ['flags','targets','resources','artifact_paths','cases','tasks','source_tasks','dependencies','runs'])if(key in p)p[key]=p[key].split('\n').map(s=>s.trim()).filter(Boolean);
    for(const key of ['low','likely','high','seconds','timeout_seconds','integration_minutes'])if(key in p)p[key]=Number(p[key]);
    if('estimated_saved_minutes'in p)p.estimated_saved_minutes=p.estimated_saved_minutes===''?null:Number(p.estimated_saved_minutes);
    for(const key of ['enabled','rework','shareable'])if(key in p)p[key]=p[key]==='true';
    if('task'in p){if(!taskScopes.has(p.task))throw new Error('请选择已读取的本项目任务');p.scope=taskScopes.get(p.task);}
    const scopeMap=ids=>Object.fromEntries(ids.map(id=>{if(!taskScopes.has(id))throw new Error('任务不存在：'+id);return[id,taskScopes.get(id)];}));
    if('package'in p){const pack=packages[p.package];if(!pack)throw new Error('任务包不存在');p.scopes=scopeMap(pack.tasks);}
    if('tasks'in p)p.scopes=scopeMap(p.tasks);if('source_tasks'in p)p.source_scopes=scopeMap(p.source_tasks);
    if('commands'in p)p.commands=p.commands.split('\n').filter(Boolean).map(s=>{const i=s.indexOf('|');return{case:s.slice(0,i).trim(),argv:JSON.parse(s.slice(i+1))};});
    if('results'in p)p.results=p.results.split('\n').filter(Boolean).map(s=>{const [ref,status,seconds,...summary]=s.split('|').map(x=>x.trim());return{case:ref,status,seconds:Number(seconds),summary:summary.join(' | '),exit_code:null};});
    if('artifacts'in p)p.artifacts=p.artifacts.split('\n').filter(Boolean).map(s=>{const [path,sha256,location]=s.split('|').map(x=>x.trim());return{path,sha256,location};});
    if('evidence'in p)p.evidence=p.evidence.split('\n').filter(Boolean).map(s=>{const i=s.lastIndexOf('|');return{path:s.slice(0,i).trim(),sha256:s.slice(i+1).trim()};});
    const request={request_id:frozenRequest?.request_id||requestId(),expected_revision:revision,action,payload:p};
    if(frozenRequest&&JSON.stringify(frozenRequest)!==JSON.stringify(request))throw new Error('原请求已冻结；请关闭并重读后准备不同内容');
    frozenRequest=request;await api('/api/operations',request);await refreshWorkspace(app.generation);$('detail').close();
  }catch(error){if(error.status===400)frozenRequest=null;message.textContent=error.message;}finally{save.disabled=false;}};$('detail').showModal();
}
