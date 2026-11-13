'use strict';
// Primary: actual commit ancestry and changes. Secondary: branch/ref, author,
// task/run/asset links. Tertiary: sync audit and SHA. One management action;
// existing surface/ink/muted/action/line tokens, 8/12/16/24 spacing, 14/16 type.
const scm={repo:'',ref:'',anchor:'',path:'',q:'',author:'',offset:0,request:0};
function resetGit(){Object.assign(scm,{repo:'',ref:'',anchor:'',path:'',q:'',author:'',offset:0,request:scm.request+1});}
function navigateGit(repo,commit){if($('detail').open)$('detail').close();Object.assign(scm,{repo,anchor:commit,path:'',q:'',author:'',offset:0});selectWorkspacePanel('git');}
function gitLink(label,url){const a=el('a',label);a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a;}
function gitUrl(r,sha,path=''){return 'https://github.com/'+r.repository+(path?'/blob/':'/commit/')+sha+(path?'/'+path.split('/').map(encodeURIComponent).join('/'):'');}
async function gitQuery(endpoint,params){return api('/api/git/'+endpoint+'?'+new URLSearchParams({repo:scm.repo,...params}));}
function gitButton(box,label,fn){const b=el('button',label);b.onclick=fn;box.append(b);return b;}
async function renderGit(box){
  const state=ws.git;if(!state)return;
  box.append(el('p','GitHub仅追踪审核纳入的源码。缓存、调研材料、历史归档、美术资产、测试记录、日志和运行时文件保留在本地/NAS；通过任务、版本与摘要关联。此页不暂存、提交或推送文件。','secondary'));
  const repos=Object.entries(state.repos).filter(([,r])=>r.enabled);
  if(!repos.length){box.append(el('p','尚未绑定代码仓库。负责人可绑定GitHub owner/name；实例管理员配置仓库专用只读接入后开始同步。','empty'));return;}
  if(!repos.some(([id])=>id===scm.repo)){scm.repo=repos[0][0];scm.ref='';scm.anchor='';scm.offset=0;}
  const repo=state.repos[scm.repo],generation=app.generation,request=++scm.request;
  const controls=el('div',undefined,'graph-controls');box.append(controls);
  const rs=selectInput(controls,'代码仓库','git-repo',Object.fromEntries(repos.map(([id,r])=>[id,r.title+' · '+r.repository])),scm.repo);
  rs.onchange=()=>{scm.repo=rs.value;scm.ref='';scm.anchor='';scm.offset=0;renderWorkspace();};
  box.append(gitLink('在GitHub查看仓库','https://github.com/'+repo.repository));
  box.append(el('p',repo.synced_at?'最近快照 '+new Date(repo.synced_at*1000).toLocaleString():'尚未同步，当前绑定未核验。','muted'));
  if(repo.last_check)box.append(el('p','最近检查 '+new Date(repo.last_check.at*1000).toLocaleString()+' · '+(repo.last_check.error?'失败':'成功，未变化时保留原快照'),'muted'));
  if(repo.sync_error)box.append(el('p','同步失败，保留上一次可见快照：'+repo.sync_error,'notice'));
  if(app.role==='reviewer')gitButton(controls,'请求同步',()=>editGit('sync_request',{repo:scm.repo,reason:'更新GitHub只读提交与引用快照'}));
  if(repo.alerts?.length)relationDetails(box,'已误入Git的本地保留路径告警（不自动删除历史）',repo.alerts,r=>r.path+'\n'+r.reason);
  const refs=Object.keys(repo.refs);if(!refs.length){box.append(el('p','等待第一次成功同步；本地材料不会为此被上传。','empty'));return;}
  if(!refs.includes(scm.ref)){scm.ref=repo.default_branch in repo.refs?repo.default_branch:refs[0];scm.anchor='';scm.offset=0;}
  const branch=selectInput(controls,'分支 / 标签','git-ref',Object.fromEntries(refs.map(r=>[r,r.replace(/^refs\/(heads|tags)\//,'')])),scm.ref);
  branch.onchange=()=>{scm.ref=branch.value;scm.anchor='';scm.offset=0;renderWorkspace();};
  if(!scm.anchor)scm.anchor=repo.refs[scm.ref];
  if(scm.anchor!==repo.refs[scm.ref])gitButton(controls,'查看最新提交',()=>{scm.anchor='';scm.offset=0;renderWorkspace();});
  const filters=el('form',undefined,'graph-controls');box.append(filters);
  for(const [key,label] of [['q','提交说明'],['author','作者'],['path','文件历史（仓库相对路径）']]){const l=el('label',label),i=el('input');i.name='git-'+key;i.value=scm[key];l.append(i);filters.append(l);}
  const search=el('button','筛选');search.type='submit';filters.append(search);filters.onsubmit=e=>{e.preventDefault();for(const k of ['q','author','path'])scm[k]=filters.elements['git-'+k].value.trim();scm.offset=0;renderWorkspace();};
  gitButton(box,'比较两个提交',()=>compareGit(repo));
  gitButton(box,'浏览当前版本文件',()=>showGitTree(scm.anchor,repo));
  const locate=el('form',undefined,'graph-controls'),input=el('input');input.name='git-commit';input.placeholder='定位完整40位提交SHA';input.setAttribute('aria-label','定位完整提交SHA');const go=el('button','定位提交');go.type='submit';locate.append(input,go);locate.onsubmit=e=>{e.preventDefault();showGitCommit(input.value.trim(),repo);};box.append(locate);
  box.append(el('p','当前历史固定在 '+scm.anchor+'；父子边来自Git对象。合并提交保留多个父提交，分页外的父提交可在详情继续打开。','muted'));
  const output=el('div');box.append(output);output.append(el('p','读取提交历史…','muted'));
  try{
    const data=await gitQuery('log',{ref:scm.anchor,offset:scm.offset,path:scm.path,q:scm.q,author:scm.author});
    if(generation!==app.generation||request!==scm.request||ws.panel!=='git')return;
    output.replaceChildren();if(!data.commits.length)output.append(el('p','当前范围没有提交。','empty'));else drawCommitGraph(output,data.commits,repo);
    const nav=el('div',undefined,'graph-controls');output.append(nav);
    if(scm.offset)gitButton(nav,'上一页',()=>{scm.offset=Math.max(0,scm.offset-50);renderWorkspace();});
    if(data.next!==null)gitButton(nav,'下一页',()=>{scm.offset=data.next;renderWorkspace();});
    relationDetails(box,'同步与历史重写记录',repo.history.slice().reverse(),r=>new Date(r.at*1000).toLocaleString()+' · '+(r.error||'同步成功')+'\n非快进引用：'+(r.rewritten.join('、')||'无'));
  }catch(error){if(generation===app.generation&&request===scm.request)output.replaceChildren(el('p',error.message,'notice'));}
}
function drawCommitGraph(box,commits,repo){
  const ns='http://www.w3.org/2000/svg',make=(tag,attrs={})=>{const n=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);return n;};
  const stage=el('div',undefined,'graph-stage git-history'),svg=make('svg',{viewBox:`0 0 1000 ${commits.length*80+24}`,role:'img','aria-label':'Git提交父子关系图'});svg.classList.add('dependency-graph');svg.style.width='1000px';svg.style.height=(commits.length*80+24)+'px';stage.append(svg);box.append(stage);
  const lanes=new Map(),positions=new Map();let next=0;
  for(let i=0;i<commits.length;i++){const c=commits[i];if(!lanes.has(c.sha))lanes.set(c.sha,next++);const lane=lanes.get(c.sha);positions.set(c.sha,{x:24+lane*20,y:32+i*80});c.parents.forEach((p,j)=>{if(!lanes.has(p))lanes.set(p,j?next++:lane);});}
  const textX=Math.max(140,...[...positions.values()].map(p=>p.x+32)),width=textX+860;svg.setAttribute('viewBox',`0 0 ${width} ${commits.length*80+24}`);svg.style.width=width+'px';
  for(const c of commits){const a=positions.get(c.sha);for(const p of c.parents){const b=positions.get(p);const edge=make('path',{d:b?`M ${a.x} ${a.y} C ${a.x} ${(a.y+b.y)/2}, ${b.x} ${(a.y+b.y)/2}, ${b.x} ${b.y}`:`M ${a.x} ${a.y} L ${a.x} ${Math.min(a.y+56,commits.length*80)}`,'data-parent':p,'data-child':c.sha});edge.classList.add('graph-edge');if(!b)edge.classList.add('containment');svg.append(edge);}}
  for(const c of commits){const a=positions.get(c.sha),g=make('g',{'data-commit':c.sha,tabindex:0,role:'button','aria-label':c.subject});g.classList.add('git-node');const circle=make('circle',{cx:a.x,cy:a.y,r:5});g.append(circle);for(const [y,value] of [[a.y-4,c.subject.slice(0,92)||'（无提交说明）'],[a.y+20,c.sha.slice(0,8)+' · '+c.author+' · '+(c.author_date||'时间未知')],[a.y+42,Object.entries(repo.refs).filter(([,h])=>h===c.sha).map(([r])=>r.replace(/^refs\/(heads|tags)\//,'')).join('、')+' · 关联任务 '+c.relations.tasks.length+' / 测试 '+c.relations.runs.length+' / 资产 '+c.relations.assets.length]]){const t=make('text',{x:textX,y});t.textContent=value;g.append(t);}const open=()=>showGitCommit(c.sha,repo);g.onclick=open;g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open();}};svg.append(g);}
}
function gitDialog(title){app.selected=null;$('detail-kind').textContent='GitHub · 只读代码溯源';$('detail-title').textContent=title;$('stale').hidden=true;const body=$('detail-body');body.replaceChildren();if(!$('detail').open)$('detail').showModal();return body;}
async function showGitCommit(commit,repo){
  const generation=app.generation,rid=scm.repo,body=gitDialog(commit),request=++scm.request;body.append(el('p','读取提交…','muted'));
  try{
    const c=await gitQuery('commit',{commit});if(generation!==app.generation||rid!==scm.repo||request!==scm.request)return;
    body.replaceChildren();body.append(gitLink('在GitHub查看提交',gitUrl(repo,c.sha)),el('pre',c.message));cards(body,[['作者',c.author+' · '+c.author_date],['提交者',c.committer+' · '+c.committer_date]]);
    const parents=section('父提交（合并时比较各父版本）');for(const p of c.parents){gitButton(parents,p.slice(0,12),()=>showGitCommit(p,repo));gitButton(parents,'比较此父提交',()=>showGitComparison(p,c.sha,repo));}if(!c.parents.length)parents.append(el('p','根提交','muted'));body.append(parents);
    for(const t of c.relations.tasks){const s=section(t.id+' · '+t.title);s.append(el('p',t.status+' · '+t.matches.join('、')+'\n'+t.explicit.map(l=>(l.current?'当前范围':'历史范围')+' · '+l.reason).join('\n')));gitButton(s,'打开任务',()=>{selectWorkspacePanel('tasks');showDetail(t.id);});body.append(s);}
    listLines(body,'固定输入的测试运行',c.relations.runs,r=>r.id+' · '+r.status+' · '+(r.suite||'手工记录'));
    listLines(body,'来源资产版本',c.relations.assets,r=>r.ref+' · '+r.stage+' · '+r.title);
    if(app.role==='reviewer')gitButton(body,'关联当前任务范围',()=>editGit('link',{repo:rid,commit:c.sha}));
    appendGitFiles(body,c.files,c.parents[0]||'',c.sha,repo);
  }catch(error){if(generation===app.generation&&request===scm.request)body.replaceChildren(el('p',error.message,'notice'));}
}
function appendGitFiles(body,files,base,head,repo,browse=false){
  const sec=section('变更文件 · '+files.length);body.append(sec);
  for(const f of files){const row=el('div',undefined,'git-file');row.append(el('p',f.path+(browse?'':' · +'+(f.additions??'二进制')+' / −'+(f.deletions??'二进制')),'detail-text'));if(f.local_only)row.append(el('p',f.local_only,'notice'));else{if(!browse)gitButton(row,'查看差异',()=>showGitPatch(base,head,f.path));gitButton(row,'文件历史',()=>{if($('detail').open)$('detail').close();scm.path=f.path;scm.anchor=head;scm.offset=0;selectWorkspacePanel('git');});gitButton(row,'逐行溯源',()=>showGitBlame(head,f.path,repo));row.append(gitLink('GitHub文件',gitUrl(repo,head,f.path)));}sec.append(row);}
}
async function showGitPatch(base,head,path){const generation=app.generation,repo=scm.repo,request=++scm.request,body=gitDialog(path+' · 差异');try{const d=await gitQuery('patch',{base,head,path});if(generation!==app.generation||repo!==scm.repo||request!==scm.request)return;const pre=el('pre',undefined,'git-diff');for(const line of d.patch.split('\n'))pre.append(el('span',line+'\n',line.startsWith('+')?'git-added':line.startsWith('-')?'git-removed':''));body.append(el('p',(base||'空树')+' → '+head,'muted'),pre);}catch(e){if(generation===app.generation&&request===scm.request)body.append(el('p',e.message,'notice'));}}
async function showGitBlame(head,path,repo,start=1){const generation=app.generation,rid=scm.repo,request=++scm.request,body=gitDialog(path+' · 逐行溯源');try{const d=await gitQuery('blame',{head,path,start});if(generation!==app.generation||rid!==scm.repo||request!==scm.request)return;body.append(el('p','固定提交 '+head+' · '+d.total_lines+' 行。归属表示最后修改来源，不表示工作量或质量。','muted'));for(const line of d.lines){const row=el('div',undefined,'git-blame-line');gitButton(row,line.line+' · '+line.sha.slice(0,8)+' · '+line.author,()=>showGitCommit(line.sha,repo));row.append(el('pre',line.text));body.append(row);}if(start>1)gitButton(body,'上一段',()=>showGitBlame(head,path,repo,Math.max(1,start-200)));if(d.next)gitButton(body,'下一段',()=>showGitBlame(head,path,repo,d.next));}catch(e){if(generation===app.generation&&request===scm.request)body.append(el('p',e.message,'notice'));}}
function compareGit(repo){const body=gitDialog('比较固定提交'),form=el('form',undefined,'review-form');formInput(form,'起点完整SHA','base',false,'');formInput(form,'终点完整SHA','head',false,scm.anchor);const b=el('button','比较');b.type='submit';form.append(b);form.onsubmit=e=>{e.preventDefault();showGitComparison(form.elements.base.value.trim(),form.elements.head.value.trim(),repo);};body.append(form);}
async function showGitTree(head,repo,prefix=''){const generation=app.generation,rid=scm.repo,request=++scm.request,body=gitDialog('版本文件目录'),form=el('form',undefined,'review-form');formInput(form,'文件或目录前缀','prefix',false,prefix);const b=el('button','定位');b.type='submit';form.append(b);form.onsubmit=e=>{e.preventDefault();showGitTree(head,repo,form.elements.prefix.value.trim());};body.append(form);try{const d=await gitQuery('tree',{head,path:prefix});if(generation!==app.generation||rid!==scm.repo||request!==scm.request)return;body.append(el('p',head+' · '+d.files.length+' 项；最多展示500项，可缩小目录。','muted'));appendGitFiles(body,d.files.slice(0,500).map(f=>({...f,additions:null,deletions:null})),head,head,repo,true);}catch(e){if(generation===app.generation&&request===scm.request)body.append(el('p',e.message,'notice'));}}
async function showGitComparison(base,head,repo){const generation=app.generation,rid=scm.repo,request=++scm.request,body=gitDialog('版本比较');try{const d=await gitQuery('compare',{base,head});if(generation!==app.generation||rid!==scm.repo||request!==scm.request)return;body.append(el('p',d.meaning,'secondary'),el('p',base+' → '+head,'detail-text'));appendGitFiles(body,d.files,base,head,repo);}catch(e){if(generation===app.generation&&request===scm.request)body.append(el('p',e.message,'notice'));}}
function editGit(fixed,seed={}){
  const generation=app.generation,project=app.project,revision=ws.git.revision,body=gitDialog('管理代码仓库与存储边界'),form=el('form',undefined,'review-form');
  const labels={bind:'绑定GitHub仓库',sync_request:'请求只读同步',enable:'启用 / 停用仓库',policy:'设置本地保留规则',link:'关联提交与当前任务范围'},actions=fixed?{[fixed]:labels[fixed]}:labels;
  const choose=selectInput(form,'操作','git-action',actions,fixed||'bind'),fieldsBox=el('div');form.append(fieldsBox);let frozen=null;
  const definitions={bind:[['id','仓库ID'],['repository','GitHub owner/name'],['title','显示名称'],['reason','绑定依据']],sync_request:[['repo','仓库ID'],['reason','同步依据']],enable:[['repo','仓库ID'],['enabled','是否启用 true / false'],['reason','启停依据']],policy:[['patterns','额外本地保留模式，每行一项'],['exceptions','逐文件审核例外 JSON 对象，路径:依据'],['reason','边界依据']],link:[['repo','仓库ID'],['commit','完整提交SHA'],['task','任务ID'],['reason','关联依据']]};
  function draw(){fieldsBox.replaceChildren();frozen=null;for(const [key,label]of definitions[choose.value])formInput(fieldsBox,label,key,['patterns','exceptions','reason'].includes(key),String(seed[key]??(key==='repo'?scm.repo:key==='enabled'?'false':key==='exceptions'?JSON.stringify(ws.git.policy.exceptions):key==='patterns'?ws.git.policy.patterns.join('\n'):'')));}
  choose.onchange=draw;draw();const message=el('p','','form-message'),button=el('button','保存项目记录');button.type='submit';form.append(message,button);body.append(form);
  form.onsubmit=async e=>{e.preventDefault();button.disabled=true;try{if(generation!==app.generation||project!==app.project)throw new Error('项目已切换');if(!frozen){const p={};for(const [key]of definitions[choose.value])p[key]=form.elements[key].value.trim();if(choose.value==='policy'){p.patterns=p.patterns.split('\n').filter(Boolean);p.exceptions=JSON.parse(p.exceptions||'{}');}if(choose.value==='enable')p.enabled=p.enabled==='true';if(choose.value==='link'){const task=app.tasks.find(t=>t.spec.id===p.task);if(!task)throw new Error('当前项目无此任务');p.scope=task.scope_hash;}frozen={request_id:requestId(),expected_revision:revision,action:choose.value,payload:p};}await api('/api/git',frozen);await refreshWorkspace(generation);if(generation===app.generation)$('detail').close();}catch(error){message.textContent=error.message;if(error.status===400)frozen=null;}finally{button.disabled=false;}};
}
