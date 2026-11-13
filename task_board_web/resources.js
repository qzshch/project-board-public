'use strict';
// Primary: actual resource entry points and access conditions. Secondary:
// category, maintainer, version and retention. Tertiary: provenance/history.
// One registration action; existing surface/ink/secondary/muted/action tokens,
// spacing 8/12/16/24, 14/16 type, native inputs and responsive single columns.
const resourceCategories={cache:'缓存',research:'调研材料',art:'美术与媒体',archive:'历史归档',test_records:'测试记录与产物',logs:'日志',runtime:'运行态',documentation:'接手资料',other:'其他资源'};
const resourceKinds={nas:'NAS目录 / 文件',smb:'SMB共享',ssh:'SSH位置',local:'本地机器',http:'HTTP(S)入口',repo:'仓库内说明'};
const resourceVisibility={project:'本项目成员',managers:'负责人 / 继承SE',operator:'仅实例管理员'};
const resourceAvailability={available:'登记为可用（读取时仍需核对）',request_access:'需要申请文件权限',offline:'所属机器离线',missing:'入口已失效',unknown:'尚未复核原件现状'};
const resourceView={category:'',origin:'',q:'',task:'',retired:false,offset:0,token:0};
function resetResources(){Object.assign(resourceView,{category:'',origin:'',q:'',task:'',retired:false,offset:0,token:resourceView.token+1});}
function openTaskResources(task){resourceView.task=task;resourceView.offset=0;selectWorkspacePanel('assets');}
function resourceAction(box,label,fn){const b=el('button',label);b.type='button';b.onclick=fn;box.append(b);return b;}
function resourceCard(e){
  const card=el('article',undefined,'resource-card');card.dataset.resource=e.id;
  const head=el('div',undefined,'section-head'),title=el('div');title.append(el('h3',e.title),el('p',`${resourceCategories[e.category]} · ${resourceVisibility[e.visibility]} · ${e.status==='retired'?'已停止推荐':'有效入口'} · v${e.entry_version}`,'muted'));head.append(title);card.append(head);
  card.append(el('p',e.description,'detail-text'),el('p',`维护者 ${e.owner} · 版本 ${e.version}\n${resourceAvailability[e.availability]}${e.mutable?' · 动态内容，不以固定SHA代表整个目录':''}`,'detail-text secondary'));
  for(const loc of e.locations){const block=el('div',undefined,'resource-location');block.append(el('p',resourceKinds[loc.kind]+' · '+loc.machine,'muted'));
    if(loc.kind==='http'){const a=el('a',loc.location);a.href=loc.location;a.target='_blank';a.rel='noopener noreferrer';block.append(a);}else block.append(el('code',loc.location));
    block.append(el('p',loc.access,'detail-text'));card.append(block);
  }
  const details=el('details',undefined,'relation-details');details.append(el('summary','使用、保留与登记摘要'));
  details.append(el('p','使用约束：'+e.usage_notes,'detail-text'),el('p','保留规则：'+e.retention,'detail-text'));
  if(e.integrity.kind!=='none')details.append(el('p',`登记摘要（访问原件核对）\n${e.integrity.subject}\nSHA256 ${e.integrity.sha256}`,'detail-text'));
  details.append(el('p',`关联任务：${e.tasks.join('、')||'项目通用'}\n模块：${e.modules.join('、')||'未限定'}\n资产版本：${e.asset_refs.join('、')||'尚未关联'}\n登记更新：${e.updated_at?new Date(e.updated_at*1000).toLocaleString():'原知识未记录更新时间'} · ${e.updated_by}\n依据：${e.reason}`,'detail-text'));
  if(e.record_scope_current===false)details.append(el('p','历史任务范围的记录，仅供追溯，不能替代当前验证。','notice'));
  card.append(details);const actions=el('div',undefined,'graph-controls');card.append(actions);
  if(e.origin==='registered'){
    resourceAction(actions,'位置版本历史',()=>showResourceHistory(e.id));
    if(app.role==='reviewer'&&(e.visibility!=='operator'||app.admin)&&e.status!=='retired'){
      resourceAction(actions,'更新登记',()=>editResource(e.id));resourceAction(actions,'停止推荐此入口',()=>retireResource(e));
    }
  }else if(e.origin==='run_artifact'){resourceAction(actions,'查看测试与自动化',()=>selectWorkspacePanel('quality'));}
  else{resourceAction(actions,'查看项目知识原登记',()=>selectWorkspacePanel('overview'));if(app.role==='reviewer')resourceAction(actions,'补全分类与访问说明',()=>editResource(undefined,{...e,id:''}));}
  return card;
}
async function renderProjectResources(box){
  const project=app.project,generation=app.generation,token=++resourceView.token;
  const sectionBox=section('本地与NAS资源入口');sectionBox.id='resource-directory';box.append(sectionBox);
  sectionBox.append(el('p','统一登记缓存、调研、美术、归档、测试记录、日志、运行态和接手资料。原件留在所在机器；这里的入口不授予文件权限，也不代表已经审核为可复用资产。','secondary'));
  const tools=el('div',undefined,'graph-controls');sectionBox.append(tools);
  if(app.role==='reviewer')resourceAction(tools,'登记资源入口',()=>editResource());
  const guide=el('a','资源与接手操作手册');guide.href='/help/resources';guide.target='_blank';guide.rel='noopener';tools.append(guide);
  const filter=el('form',undefined,'graph-controls');sectionBox.append(filter);
  const category=selectInput(filter,'分类','resource-category',{'':'全部分类',...resourceCategories},resourceView.category);
  const origin=selectInput(filter,'来源','resource-origin',{'':'全部来源',registered:'人工登记入口',run_artifact:'自动运行记录',knowledge:'既有项目知识'},resourceView.origin);
  const task=selectInput(filter,'相关任务','resource-task',{'':'整个项目',...Object.fromEntries(app.tasks.map(t=>[t.spec.id,t.spec.id]))},resourceView.task);
  const status=selectInput(filter,'状态','resource-status',{active:'有效入口',all:'含已停用历史'},resourceView.retired?'all':'active');
  const search=el('input');search.name='resource-search';search.type='search';search.placeholder='搜索位置、用途或维护者';search.setAttribute('aria-label','搜索项目资源');search.value=resourceView.q;filter.append(search);const submit=el('button','筛选资源');submit.type='submit';filter.append(submit);
  function changed(){Object.assign(resourceView,{category:category.value,origin:origin.value,task:task.value,retired:status.value==='all',q:search.value.trim(),offset:0});renderWorkspace();}
  for(const input of [category,origin,task,status])input.onchange=changed;
  filter.onsubmit=e=>{e.preventDefault();changed();};
  const output=el('div');sectionBox.append(output);output.append(el('p','读取本项目可见资源…','muted'));
  try{
    const params=new URLSearchParams({category:resourceView.category,origin:resourceView.origin,task:resourceView.task,q:resourceView.q,retired:String(resourceView.retired),offset:resourceView.offset,limit:50});
    const data=await api('/api/resources?'+params);
    if(project!==app.project||generation!==app.generation||token!==resourceView.token||ws.panel!=='assets'||!sectionBox.isConnected)return;
    output.replaceChildren();output.append(el('p',`当前可见 ${data.total} 项 · `+Object.entries(data.counts).map(([k,n])=>resourceCategories[k]+' '+n).join(' / '),'muted'));
    if(!data.entries.length)output.append(el('p','此范围尚未登记入口。没有登记不表示资源不存在；接手时请向SE核对，勿猜测路径或创建演练数据。','empty'));
    const automatic=new Map();
    for(const e of data.entries){if(e.origin!=='run_artifact')output.append(resourceCard(e));else{if(!automatic.has(e.run))automatic.set(e.run,[]);automatic.get(e.run).push(e);}}
    for(const [run,entries]of automatic){const group=el('details',undefined,'relation-details');group.dataset.resourceRun=run;group.append(el('summary',`运行 ${run.slice(0,12)} · ${entries[0].test_status} · ${entries.length} 项记录 / 产物`));for(const e of entries)group.append(resourceCard(e));output.append(group);}
    const nav=el('div',undefined,'graph-controls');output.append(nav);
    if(resourceView.offset)resourceAction(nav,'上一页资源',()=>{resourceView.offset=Math.max(0,resourceView.offset-50);renderWorkspace();});
    if(data.next!==null)resourceAction(nav,'下一页资源',()=>{resourceView.offset=data.next;renderWorkspace();});
  }catch(error){if(project===app.project&&generation===app.generation&&token===resourceView.token&&sectionBox.isConnected)output.replaceChildren(el('p',error.message,'notice'));}
}
function resourceDialog(title){app.selected=null;$('detail-kind').textContent='项目资产 · 资源入口';$('detail-title').textContent=title;$('stale').hidden=true;const outer=$('detail-body');outer.replaceChildren();const body=el('div',undefined,'resource-dialog');outer.append(body);if(!$('detail').open)$('detail').showModal();return body;}
function validResourceDialog(body,project,generation){return body.isConnected&&$('detail').open&&app.project===project&&app.generation===generation;}
async function showResourceHistory(id){const project=app.project,generation=app.generation,body=resourceDialog('资源位置与登记历史');try{const data=await api('/api/resources/'+encodeURIComponent(id)+'/history');if(!validResourceDialog(body,project,generation))return;body.append(el('p','仅展示当前身份可见的历史版本。停止推荐或更新登记不会删除原件。','secondary'));for(const e of data.versions)body.append(resourceCard(e));}catch(error){if(validResourceDialog(body,project,generation))body.append(el('p',error.message,'notice'));}}
async function editResource(id,preset){
  const project=app.project,generation=app.generation,body=resourceDialog(id?'更新资源登记':'登记资源入口');let revision,seed;
  try{const data=await api(id?'/api/resources/'+encodeURIComponent(id):'/api/resources?limit=1');if(!validResourceDialog(body,project,generation))return;revision=data.revision;seed=data.entry||preset||{};}catch(error){body.append(el('p',error.message,'notice'));return;}
  const form=el('form',undefined,'review-form');body.append(form);
  for(const [key,label]of [['id','稳定资源ID（实例资料使用operator-前缀）'],['title','入口名称'],['description','用途与内容范围'],['owner','维护者Actor ID'],['version','内容版本或动态标识']])formInput(form,label,key,key==='description',seed[key]||(key==='owner'?app.actor:key==='version'?'live':''));
  if(id)form.elements.id.readOnly=true;
  selectInput(form,'资源分类','category',resourceCategories,seed.category||'research');selectInput(form,'可见范围','visibility',app.admin?resourceVisibility:{project:resourceVisibility.project,managers:resourceVisibility.managers},seed.visibility||'project');
  selectInput(form,'是否动态变化','mutable',{true:'动态目录 / 内容',false:'固定文件 / 清单版本'},String(seed.mutable??true));selectInput(form,'登记可用性','availability',resourceAvailability,seed.availability||'unknown');
  const locations=el('fieldset');locations.append(el('legend','资源位置（注明所属机器及访问条件，不填密钥或临时鉴权链接）'));form.append(locations);let count=0;
  function addLocation(value={}){const row=el('div',undefined,'resource-location-editor');locations.append(row);const n=count++;const kind=selectInput(row,'位置类型','loc-'+n,resourceKinds,value.kind||'nas');kind.dataset.locationField='kind';for(const [key,label]of [['machine','所属机器'],['location','完整位置 / 稳定URL'],['access','访问方式与申请授权的条件']]){const l=el('label',label),input=el(key==='access'?'textarea':'input');input.dataset.locationField=key;input.value=value[key]||'';input.required=true;l.append(input);row.append(l);}resourceAction(row,'移除此位置',()=>row.remove());}
  for(const loc of seed.locations||[{}])addLocation(loc);resourceAction(form,'增加备用位置',()=>addLocation());
  selectInput(form,'摘要覆盖类型','integrity_kind',{none:'未登记摘要（动态目录）',file:'单个文件SHA256',manifest:'目录清单SHA256'},seed.integrity?.kind||'none');
  formInput(form,'实际SHA256（无摘要时留空）','sha256',false,seed.integrity?.sha256||'');formInput(form,'摘要对应的文件 / 清单（无摘要时留空）','digest_subject',false,seed.integrity?.subject||'');
  for(const [key,label]of [['retention','保留与清理规则'],['usage_notes','许可、使用限制及其他接手注意事项'],['tasks','关联任务ID，每行一项；留空为项目通用'],['modules','关联模块@版本，每行一项'],['asset_refs','关联私有资产版本或固定消费ID，每行一项'],['reason','本次登记 / 更新依据']])formInput(form,label,key,true,Array.isArray(seed[key])?seed[key].join('\n'):seed[key]||'');
  form.append(el('p','本操作只登记入口，不读取/上传原件，不授予NAS权限，也不删除任何文件。','secondary'));
  const message=el('p','','form-message'),save=el('button',id?'保存入口新版本':'登记入口');save.type='submit';form.append(message,save);let frozen=null;
  form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{if(!validResourceDialog(body,project,generation))throw new Error('项目或当前窗口已变化');if(!frozen){const p={};for(const k of ['id','title','description','owner','version','category','visibility','availability','retention','usage_notes','reason'])p[k]=form.elements[k].value.trim();p.mutable=form.elements.mutable.value==='true';p.integrity={kind:form.elements.integrity_kind.value,sha256:form.elements.sha256.value.trim(),subject:form.elements.digest_subject.value.trim()};for(const k of ['tasks','modules','asset_refs'])p[k]=form.elements[k].value.split('\n').map(s=>s.trim()).filter(Boolean);p.locations=[...locations.querySelectorAll('.resource-location-editor')].map(row=>Object.fromEntries([...row.querySelectorAll('[data-location-field]')].map(i=>[i.dataset.locationField,i.value.trim()])));if(id)p.expected_version=seed.entry_version;frozen={request_id:requestId(),expected_revision:revision,action:id?'resource_update':'resource_register',payload:p};}await api('/api/governance',frozen);await refreshWorkspace(generation);if(validResourceDialog(body,project,generation))$('detail').close();}catch(error){if(error.status===400)frozen=null;if(validResourceDialog(body,project,generation))message.textContent=error.message;}finally{save.disabled=false;}};
}
function retireResource(entry){const project=app.project,generation=app.generation,body=resourceDialog('停止推荐入口，不删除原件'),form=el('form',undefined,'review-form');body.append(form);form.append(el('p',entry.title+' · v'+entry.entry_version,'secondary'));formInput(form,'停用依据与替代入口','reason',true,'');const msg=el('p','','form-message'),save=el('button','确认停止推荐');save.type='submit';form.append(msg,save);let frozen=null;form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{if(!validResourceDialog(body,project,generation))throw new Error('项目已变化');if(!frozen)frozen={request_id:requestId(),expected_revision:ws.data.revision,action:'resource_retire',payload:{id:entry.id,expected_version:entry.entry_version,reason:form.elements.reason.value.trim()}};await api('/api/governance',frozen);await refreshWorkspace(generation);if(validResourceDialog(body,project,generation))$('detail').close();}catch(error){if(error.status===400)frozen=null;if(validResourceDialog(body,project,generation))msg.textContent=error.message;}finally{save.disabled=false;}};}
