'use strict';
async function renderGitOnboarding(box){
 const project=app.project,generation=app.generation,sec=section('仓库只读接入');box.prepend(sec);sec.append(el('p','已有GitHub仓库管理权限的SE，优先在本机复用gh或Git登录登记NAS公钥，再由NAS独立核验；无需新建token、NAS SSH或管理员代办。','secondary'));
 for(const [id,repo]of Object.entries(ws.git?.repos||{})){
  const row=el('details');row.append(el('summary',repo.title+' · '+repo.repository));sec.append(row);
  try{const state=await api('/api/git-onboarding?repo='+encodeURIComponent(id));if(project!==app.project||generation!==app.generation||!sec.isConnected)return;row.append(el('p','阶段：'+state.stage+' · 下一步负责：'+state.next_owner),el('p',state.next,'secondary'));
   if(state.public_key){row.append(el('pre',state.public_key));pButton(row,'复制专属公钥',async()=>{try{await copyProjectText(state.public_key);notice('已复制公钥；NAS私钥不会下发。');}catch(e){notice('请选中公钥复制');}});}
   if(app.role==='reviewer'&&repo.enabled){const refresh=pButton(row,state.stage==='bound'?'申请NAS专属只读接入':'重新核对并同步',async()=>{refresh.disabled=true;try{await api('/api/git-onboarding/'+(state.stage==='bound'?'request':'sync'),{repo:id});ws.signature=null;await refreshWorkspace(app.generation);}catch(e){notice(e.message);}finally{refresh.disabled=false;}});
    const local=el('div');local.dataset.githubLocal=id;local.append(el('h4','优先：使用本机现有GitHub管理授权'));
    const kit=el('a','下载SE本机接入工具包');kit.href='/github-kit.zip';local.append(kit,el('pre','python tools/github_connect.py --profile <本项目SE身份文件> --repo '+id+' --evidence <非C盘证据目录>'),el('p','工具只在本机使用现有gh/Git凭据，登记当前仓库的同一公钥；NAS不接收GitHub凭据。网络中断原命令重试，先核对已有密钥。','secondary'));
    const settings=el('a','也可在GitHub手动添加此部署公钥（不勾选写权限）');settings.href='https://github.com/'+repo.repository+'/settings/keys';settings.target='_blank';settings.rel='noopener';local.append(settings);
    if(state.public_key)pButton(local,'我已登记公钥，核验并接入',async()=>{try{await api('/api/git-onboarding/complete',{repo:id,repository:repo.repository,public_key:state.public_key});notice('NAS已独立核对目标仓库身份、可读及明确只读拒写，并同步镜像。');ws.signature=null;await refreshWorkspace(app.generation);}catch(e){notice(e.message);}});
    const help=el('a','接入步骤与权限排查');help.href='/help/github';help.target='_blank';help.rel='noopener';local.append(help);row.append(local);
    const grant=el('details');grant.append(el('summary','可选：使用单仓库临时授权'));const form=el('form',undefined,'review-form');form.append(el('p','仅在不使用本机登录或手动登记时，提供只选当前仓库的fine-grained授权，Administration读写用于登记只读公钥。临时授权不持久化。GitHub删除PAT或撤销OAuth授权可能同时删除其创建的部署密钥，不要假定撤销后镜像仍可同步。','secondary'));const input=aInput(form,'grant','可选的单仓库fine-grained授权','','password');input.autocomplete='off';aSubmit(form,'使用临时授权接入',async result=>{const token=input.value;input.value='';try{await api('/api/git-onboarding/authorize',{repo:id,grant:token});result.textContent='专属只读权限与真实Git对象已核对。';ws.signature=null;await refreshWorkspace(app.generation);}finally{input.value='';}});grant.append(form);row.append(grant);
   }
  }catch(e){row.append(el('p',e.message,'notice'));}
 }
 if(!Object.keys(ws.git?.repos||{}).length&&app.role==='reviewer')pButton(sec,'绑定项目仓库',()=>editGit('bind'));
}
const gitRenderBase=renderGit;renderGit=function(box){renderGitOnboarding(box);return gitRenderBase(box);};
