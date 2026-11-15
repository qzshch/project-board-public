'use strict';
const byId=id=>document.getElementById(id),form=byId('human-form'),submit=byId('human-submit'),message=byId('login-error');
let setup=new URLSearchParams(location.hash.slice(1)).get('setup'),changing=new URLSearchParams(location.search).get('mode')==='password';
// Remove private initialization material before any further navigation or request.
if(location.hash)history.replaceState(null,'',location.pathname+location.search);
const suppliedNext=new URLSearchParams(location.search).get('next'),next=suppliedNext&&suppliedNext.startsWith('/')&&!suppliedNext.startsWith('//')&&!suppliedNext.includes('\\')?suppliedNext:'/';
async function request(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,credentials:'same-origin',cache:'no-store'});const d=await r.json();if(!r.ok)throw new Error(d.error||'请求失败');return d;}
async function initialize(){
 try{const state=await request('/api/human/status');
  if(!state.configured&&!setup){byId('setup-notice').hidden=false;byId('setup-notice').textContent='此实例尚未设置人类所有者。请打开部署时保存在私有目录中的一次性初始化入口，再设置账号密码。';form.hidden=true;return;}
  if(changing){const identity=await request('/api/me');if(identity.principal_kind!=='human')throw new Error('请先使用人类账号登录');}
  if(setup||changing){byId('login-title').textContent=changing?'修改登录密码':'设置人类所有者';byId('login-intro').textContent=changing?'新密码生效后，其他已有的人类会话将退出。':'此账号可以查看所有项目并管理实例。初始化入口仅使用一次。';byId('confirm-group').hidden=false;form.elements.confirmation.required=true;form.elements.password.minLength=12;form.elements.password.autocomplete='new-password';byId('password-label').textContent='新密码（至少12个字符）';submit.textContent=changing?'保存新密码':'设置账号并进入';}
  if(changing){byId('username-group').hidden=true;form.elements.username.required=false;byId('current-group').hidden=false;form.elements.current_password.required=true;}
 }catch(e){message.textContent=e.message;submit.disabled=true;}
}
form.onsubmit=async e=>{e.preventDefault();submit.disabled=true;message.textContent='';try{
 const pwd=form.elements.password.value;if((setup||changing)&&pwd!==form.elements.confirmation.value)throw new Error('两次输入的新密码不一致');
 const body=changing?{current_password:form.elements.current_password.value,password:pwd}:{username:form.elements.username.value.trim(),password:pwd,...(setup?{setup}:{})};
 await request(changing?'/api/human/password':setup?'/api/human/setup':'/api/human/login',body);setup=null;form.reset();location.replace(next);
 }catch(error){message.textContent=error.message;}finally{submit.disabled=false;}};
initialize();
