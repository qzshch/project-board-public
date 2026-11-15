'use strict';
async function renderGitOnboarding(box){
 const project=app.project,generation=app.generation,sec=section('仓库只读接入');box.prepend(sec);sec.append(el('p','项目SE可申请、授权和同步本项目仓库；不再逐项目请实例管理员编辑NAS文件。GitHub仓库授权仍需有权者完成。','secondary'));
 for(const [id,repo]of Object.entries(ws.git?.repos||{})){
  const row=el('details');row.append(el('summary',repo.title+' · '+repo.repository));sec.append(row);
  try{const state=await api('/api/git-onboarding?repo='+encodeURIComponent(id));if(project!==app.project||generation!==app.generation||!sec.isConnected)return;row.append(el('p','阶段：'+state.stage+' · 下一步负责：'+state.next_owner),el('p',state.next,'secondary'));
   if(state.public_key){row.append(el('pre',state.public_key));pButton(row,'复制专属公钥',async()=>{try{await navigator.clipboard.writeText(state.public_key);notice('已复制公钥；NAS私钥不会下发。');}catch(e){notice('请选中公钥复制');}});}
   if(app.role==='reviewer'&&repo.enabled){const refresh=pButton(row,state.stage==='bound'?'申请NAS专属只读接入':'重新核对并同步',async()=>{refresh.disabled=true;try{await api('/api/git-onboarding/'+(state.stage==='bound'?'request':'sync'),{repo:id});ws.signature=null;await refreshWorkspace(app.generation);}catch(e){notice(e.message);}finally{refresh.disabled=false;}});
    const grant=el('details');grant.append(el('summary','完成GitHub仓库授权'));const form=el('form',undefined,'review-form');form.append(el('p','在GitHub为本仓库创建短期 fine-grained 授权：只选择当前仓库，Administration读写用于登记只读部署公钥。平台核验后仅保留仓库专属只读密钥；临时授权不写入账本、证据或本地存储。授权完成后可立即撤销临时授权。','secondary'));const help=el('a','所需权限与最短操作手册');help.href='/help/github';help.target='_blank';help.rel='noopener';form.append(help);const input=aInput(form,'grant','本仓库短期fine-grained授权','','password');input.autocomplete='off';aSubmit(form,'核验授权并接入',async result=>{const token=input.value;input.value='';try{await api('/api/git-onboarding/authorize',{repo:id,grant:token});result.textContent='专属只读权限与真实Git对象已核对。';ws.signature=null;await refreshWorkspace(app.generation);}finally{input.value='';}});grant.append(form);row.append(grant);
   }
  }catch(e){row.append(el('p',e.message,'notice'));}
 }
 if(!Object.keys(ws.git?.repos||{}).length&&app.role==='reviewer')pButton(sec,'绑定项目仓库',()=>editGit('bind'));
}
const gitRenderBase=renderGit;renderGit=function(box){renderGitOnboarding(box);return gitRenderBase(box);};
