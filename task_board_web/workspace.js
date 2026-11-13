'use strict';
const ws={panel:'overview',data:null,shared:null};
const categoryNames={research:'研究 / 调研',collection:'素材采集',generation:'资源生成',infrastructure:'框架 / 基建',frontend:'前端开发',backend:'后端开发',library:'公共库',documentation:'记录 / 约束 / 交接文档',test:'测试',integration:'集成',release:'发布'};
const roleNames={owner:'总负责人',se:'继承 SE',researcher:'研究员',collector:'素材采集',generator:'资源生成',developer:'开发',documenter:'文档',tester:'测试',agent:'Agent',viewer:'只读'};
const panelNames={overview:'项目概览',relations:'依赖与并行',contracts:'接口冻结',assets:'项目资产',handoff:'角色与交接'};
function clearWorkspace(){ws.data=null;ws.shared=null;$('workspace-body').replaceChildren();$('workspace').hidden=true;}
async function refreshWorkspace(generation){
  const [data,shared]=await Promise.all([api('/api/governance'),api('/api/shared')]);
  if(generation!==app.generation)return;
  ws.data=data;ws.shared=shared;$('workspace').hidden=false;renderWorkspace();
}
function listLines(box,title,rows,format){const sectionBox=section(title);if(!rows.length)sectionBox.append(el('p','尚未登记。','muted'));for(const row of rows)sectionBox.append(el('p',format(row),'detail-text'));box.append(sectionBox);}
function cards(box,items){const grid=el('div',undefined,'workspace-grid');for(const [label,value] of items)grid.append(field(label,value||'待负责人登记'));box.append(grid);}
function renderWorkspace(){
  const d=ws.data;if(!d)return;const box=$('workspace-body');box.replaceChildren();$('workspace-title').textContent=panelNames[ws.panel];$('workspace-subtitle').textContent=`本项目专属资料 · 记录 ${d.revision}`;$('workspace-edit').hidden=app.role!=='reviewer';
  if(ws.panel==='overview'){
    cards(box,[['项目背景',d.knowledge.background],['目标',d.knowledge.goals],['非目标',d.knowledge.non_goals],['约束',d.knowledge.constraints]]);
    for(const [key,title] of [['materials','必读材料 · 固定版本'],['entries','项目入口']])listLines(box,title,d.knowledge[key]||[],r=>`${r.title} · ${r.version}\n${r.location}\nSHA256 ${r.sha256}`);
    listLines(box,'里程碑与验收',Object.values(d.milestones),r=>`${r.id} · ${r.status} · ${r.goal}\n验收：${r.acceptance}${r.evidence.length?' · 证据 '+r.evidence.length+' 项':''}`);
    listLines(box,'决策与历史变更',d.decisions.slice(-8).reverse(),r=>`${r.summary}\n依据：${r.reason} · ${r.actor}`);
  }
  if(ws.panel==='relations'){
    const eligible=d.queue.filter(r=>!r.blockers.length);box.append(el('p',`可领取 ${eligible.length} 项；执行时会再次原子检查角色、前置、写路径、资源和固定版本。`,'secondary'));
    drawGraph(box,d);
    listLines(box,'前置与冲突',d.queue.slice(0,60),r=>`${r.id} · ${r.blockers.length?r.blockers.join('；'):'满足当前并行条件'}`);
    listLines(box,'产物 / 接口 / 资源耦合',d.graph.filter(r=>r.type!=='hard').slice(0,80),r=>`${r.from} → ${r.to} · ${{product:'输入产物',produces:'输出产物',coupling:'共享修改',exclusive:'排他资源',contract:'固定接口',asset:'固定资产'}[r.type]}`);
    listLines(box,'任务包与原子任务映射',Object.values(d.packages),r=>`${r.id} → ${r.tasks.join('、')}\n来源：${r.source}\n待核定：${r.unknown}`);
  }
  if(ws.panel==='contracts'){
    listLines(box,'冻结版本',Object.entries(d.contracts),([ref,r])=>`${ref} · ${r.status} · 拥有者 ${r.owner}\n${r.signature}\n单位：${r.units} · 错误：${r.errors}\n事务：${r.transaction} · 幂等：${r.idempotency}\n来源：${r.source} · 兼容：${r.compatibility}`);
    for(const [id,c] of Object.entries(d.changes)){
      const sec=section(`变更 ${id}`);sec.append(el('p',`${c.contract} → ${c.replacement} · ${c.executed?'已执行':'待影响确认'}`),el('p',`直接：${c.impact.direct.join('、')||'无'}；反向依赖：${c.impact.transitive.join('、')||'无'}`),el('p',`迁移：${c.migration}\n测试：${c.tests}`),el('p',`所需确认：${c.required.join('、')} · 已确认：${c.confirmations.join('、')||'无'}`));
      if(!c.executed&&c.required.includes(app.actor)&&!c.confirmations.includes(app.actor)){const b=el('button','确认此影响范围');b.onclick=()=>editWorkspace('contract_confirm',{id,impact_hash:c.impact_hash||'',summary:'已审阅影响、迁移和测试'});sec.append(b);}box.append(sec);
    }
  }
  if(ws.panel==='assets'){
    listLines(box,'本项目私有资产',Object.entries(d.assets),([ref,r])=>`${ref} · ${r.kind} · ${r.sensitivity}\n来源：${r.source} · 许可：${r.license}\n${r.location}\nSHA256 ${r.sha256}`);
    listLines(box,'已审核共享版本',ws.shared.releases,r=>`${r.ref} · ${r.status}\n${r.location}\n许可：${r.license} · SHA256 ${r.sha256}`);
    listLines(box,'本项目固定消费',Object.entries(ws.shared.consumption),([alias,r])=>`${alias} → ${r.release} · ${r.status}\n提供方发布新版不会自动更新此引用。`);
  }
  if(ws.panel==='handoff'){
    listLines(box,'项目责任与角色',Object.entries(d.members),([id,r])=>`${id} · ${roleNames[r.role]||r.role}\n${r.scope}`);
    const h=d.handoff;listLines(box,'移交审计',h?[h]:[],r=>`${r.from} → ${r.to} · ${r.accepted?'已接受，原负责人管理权限已撤销':'等待继承 SE 接受'}\n风险：${r.risks}\n活跃任务：${r.active.join('、')||'无'}`);
    if(h&&!h.accepted&&h.to===app.actor){const b=el('button','接受当前交接');b.onclick=()=>editWorkspace('handoff_accept',{scope:h.scope,summary:''});box.append(b);}
  }
}
function drawGraph(box,d){
  const nodes=d.nodes.filter(n=>n.category!=='unknown').slice(0,40), ids=new Set(nodes.map(n=>n.id)),edges=d.graph.filter(e=>e.type==='hard'&&ids.has(e.from)&&ids.has(e.to));
  if(!nodes.length){box.append(el('p','历史任务包尚未拆成原子任务；依赖未知，不自动推断。','notice'));return;}
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',`0 0 960 ${Math.max(120,nodes.length*72)}`);svg.setAttribute('role','img');svg.setAttribute('aria-label','本项目原子任务硬依赖图，箭头指向后继任务');svg.classList.add('dependency-graph');
  const positions=new Map(nodes.map((n,i)=>[n.id,{x:24+(i%2)*464,y:24+Math.floor(i/2)*120}]));svg.setAttribute('viewBox',`0 0 960 ${Math.ceil(nodes.length/2)*120+24}`);
  for(const e of edges){const a=positions.get(e.from),b=positions.get(e.to),path=document.createElementNS(ns,'path');path.setAttribute('d',`M ${a.x+200} ${a.y+56} L ${b.x+200} ${b.y} l -5 8 m 5 -8 l 5 8`);path.setAttribute('class','graph-edge');svg.append(path);}
  for(const n of nodes){const p=positions.get(n.id),rect=document.createElementNS(ns,'rect');rect.setAttribute('x',p.x);rect.setAttribute('y',p.y);rect.setAttribute('width',420);rect.setAttribute('height',64);rect.setAttribute('rx',8);svg.append(rect);for(const [line,label] of [[0,n.id],[1,(categoryNames[n.category]||n.category)+' · '+(states[n.status]?.[0]||n.status)]]){const t=document.createElementNS(ns,'text');t.setAttribute('x',p.x+16);t.setAttribute('y',p.y+24+line*24);t.textContent=label.slice(0,45);svg.append(t);}}
  box.append(svg,el('p','图仅展示当前项目已分类原子任务（最多40项）。箭头为硬前置；其他关系分别列出。','muted'));
}
function selectInput(form,label,name,values,current){const group=el('label',label),input=el('select');input.name=name;for(const [v,l] of Object.entries(values)){const o=el('option',l);o.value=v;input.append(o);}input.value=current||Object.keys(values)[0];group.append(input);form.append(group);return input;}
function atomicInputs(form,task){
  const w=task?.spec.work;selectInput(form,'任务分类','category',{'':'历史任务包（不自动推断原子范围）',...categoryNames},w?.category||'');selectInput(form,'执行角色','work_role',roleNames,w?.role||'developer');
  const label=el('label',undefined,'check'),check=el('input');check.type='checkbox';check.name='inputs_known';check.checked=w?.inputs_known||false;label.append(check,el('span','输入、来源版本与耦合已核定'));form.append(label);
  for(const [key,title] of [['inputs','输入与SHA引用'],['outputs','输出产物'],['contracts','固定接口（id@版本）'],['assets','固定资产（本项目引用ID）'],['resources','排他资源（端口/设备等）'],['couplings','共享修改（入口/数据库等）']])formInput(form,title+'，每行一项','work_'+key,true,w?.[key]?.join('\n')||'');
  formInput(form,'行为与反例验收条件','work_acceptance',true,w?.acceptance||'');
}
const actionFields={
  knowledge:['项目背景|background','目标|goals','非目标|non_goals','约束|constraints','必读材料（每行 标题 | 位置 | 版本 | SHA256）|materials','入口（同上格式）|entries'],
  milestone:['里程碑ID|id','目标|goal','验收条件|acceptance','状态 planned/active/passed/blocked|status','证据（每行 路径 | SHA256）|evidence'],
  decision:['决策|summary','原因|reason','证据（每行 路径 | SHA256）|evidence'],member:['已登记Agent ID|actor','角色|role','职责与范围|scope'],
  package:['任务包ID|id','原子任务ID，每行一项|tasks','历史来源|source','未知/待核定边界|unknown'],
  contract_freeze:['接口ID|id','不可变版本|version','接口拥有者ID|owner','签名/字段|signature','单位|units','错误|errors','事务|transaction','幂等|idempotency','来源版本|source','生产者，每行一项|producers','消费者，每行一项|consumers','兼容窗口|compatibility','证据（每行 路径 | SHA256）|evidence'],
  contract_propose:['提案ID|id','旧接口 id@版本|contract','新接口 id@版本|replacement','迁移清单|migration','测试清单|tests'],
  contract_confirm:['提案ID|id','影响摘要|impact_hash','确认依据|summary'],contract_execute:['已确认提案ID|id'],
  asset:['资产ID|id','不可变版本|version','类型 skill/methodology/infrastructure/private|kind','来源|source','许可|license','敏感性 public/private/secret|sensitivity','SHA256|sha256','项目私有位置|location','负责人ID|owner','证据（每行 路径 | SHA256）|evidence'],
  publish:['本项目资产 id@版本|asset','共享受众项目ID，每行一项；*代表所有项目|audience','显式共享位置|shared_location','发布审核依据|review','证据（每行 路径 | SHA256）|evidence'],consume:['共享版本 project/id@版本|ref','本项目固定引用ID|alias','选择依据|reason','消费验证|tests'],upgrade:['新共享版本 project/id@版本|ref','原本项目引用ID|alias','升级批准依据|reason','回归结果|tests'],
  deprecate:['共享版本|ref','原因|reason','消费方影响/迁移计划|migration','证据（每行 路径 | SHA256）|evidence'],withdraw:['共享版本|ref','原因|reason','消费方影响/迁移计划|migration','证据（每行 路径 | SHA256）|evidence'],
  handoff_propose:['继承SE ID|to','未决风险|risks','已读版本，每行一项|materials','移交原因|reason'],handoff_accept:['当前范围摘要|scope','接受说明|summary']};
const actionLabels={knowledge:'更新项目背景与材料',milestone:'登记里程碑',decision:'追加决策',member:'指定角色与职责',package:'登记任务包映射',contract_freeze:'冻结新接口版本',contract_propose:'提议接口变更',contract_confirm:'确认影响范围',contract_execute:'执行已确认变更',asset:'登记私有资产',publish:'审核发布共享版本',consume:'固定消费版本',upgrade:'批准消费升级',deprecate:'弃用共享版本',withdraw:'撤回共享版本',handoff_propose:'提出SE交接',handoff_accept:'接受交接'};
async function postGovernance(action,payload){return api('/api/governance',{request_id:requestId(),expected_revision:ws.data.revision,action,payload});}
function editWorkspace(fixed,seed={}){
  const choices={overview:['knowledge','milestone','decision'],relations:['package'],contracts:['contract_freeze','contract_propose','contract_confirm','contract_execute'],assets:['asset','publish','consume','upgrade','deprecate','withdraw'],handoff:['member','handoff_propose']}[ws.panel];
  app.selected=null;$('detail-title').textContent='管理'+panelNames[ws.panel];$('detail-kind').textContent='项目专属记录';$('stale').hidden=true;const body=$('detail-body');body.replaceChildren();const form=el('form',undefined,'review-form');
  const choose=selectInput(form,'操作','operation',Object.fromEntries((fixed?[fixed]:choices).map(k=>[k,actionLabels[k]])),fixed||choices[0]);const dynamic=el('div');form.append(dynamic);
  function draw(){dynamic.replaceChildren();const action=choose.value;const initial=action==='knowledge'?ws.data.knowledge:seed;for(const row of actionFields[action]){const at=row.lastIndexOf('|'),label=row.slice(0,at),key=row.slice(at+1);let value=initial?.[key]||'';if(Array.isArray(value))value=value.map(r=>typeof r==='string'?r:[r.title,r.location,r.version,r.sha256].join(' | ')).join('\n');if(key==='role')selectInput(dynamic,label,key,roleNames,value||'developer');else formInput(dynamic,label,key,true,value);}if(action==='asset'){const l=el('label',undefined,'check'),c=el('input');c.type='checkbox';c.name='shareable';l.append(c,el('span','具备通用共享资格（发布仍需单独审核）'));dynamic.append(l);}}
  choose.onchange=draw;draw();const message=el('p','','form-message'),save=el('button','追加项目记录','primary');save.type='submit';form.append(message,save);body.append(form);
  const revision=ws.data.revision;
  form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{const action=choose.value,p={};for(const row of actionFields[action]){const key=row.slice(row.lastIndexOf('|')+1);p[key]=form.elements[key].value.trim();}
    for(const key of ['tasks','producers','consumers','audience'])if(key in p)p[key]=p[key].split('\n').filter(Boolean);
    if(action==='knowledge')for(const key of ['materials','entries'])p[key]=p[key]?p[key].split('\n').filter(Boolean).map(s=>{const [title,location,version,sha256]=s.split('|').map(x=>x.trim());return{title,location,version,sha256};}):[];
    if(action==='handoff_propose')p.materials=p.materials.split('\n').filter(Boolean);
    if('evidence' in p)p.evidence=p.evidence?p.evidence.split('\n').filter(Boolean).map(s=>{const at=s.lastIndexOf('|');return{path:s.slice(0,at).trim(),sha256:s.slice(at+1).trim()};}):[];
    if(action==='asset')p.shareable=form.elements.shareable.checked;
    await api(['publish','consume','upgrade','deprecate','withdraw'].includes(action)?'/api/shared':'/api/governance',['publish','consume','upgrade','deprecate','withdraw'].includes(action)?{request_id:requestId(),action,payload:p}:{request_id:requestId(),expected_revision:revision,action,payload:p});$('detail').close();await refreshWorkspace(app.generation);
  }catch(error){message.textContent=error.message;}finally{save.disabled=false;}};$('detail').showModal();
}
document.querySelectorAll('[data-panel]').forEach(b=>b.onclick=()=>{ws.panel=b.dataset.panel;document.querySelectorAll('[data-panel]').forEach(n=>n.setAttribute('aria-pressed',String(n===b)));renderWorkspace();});
$('workspace-edit').onclick=()=>editWorkspace();
for(const [value,label] of Object.entries(categoryNames)){const option=el('option',label);option.value=value;$('kind').append(option);}
