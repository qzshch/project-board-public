"""Project SE read-only onboarding. Never journal the transient GitHub grant.

Prefer SE-local existing GitHub authority, followed by NAS capability proof.
A selected-repository fine-grained grant remains an optional path. No input
can choose a local path, host, command or remote. Unknown API effects reconcile
by key before another create. Existing operator mirrors remain compatible.
"""
import json, os, threading, uuid, time, subprocess
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from .store import BoardError, fields, text, canonical
from .git_tracking import Tracking, repo_id

LOCK=threading.RLock()
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def github(token,method,path,body=None):
    req=Request('https://api.github.com'+path,method=method,data=None if body is None else json.dumps(body).encode(),headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'project-board-readonly-broker','Content-Type':'application/json'})
    try:
        with build_opener(NoRedirect).open(req,timeout=25) as response:
            raw=response.read(2*1024*1024)
            if len(raw)>=2*1024*1024:raise BoardError('GitHub响应超限',502)
            return json.loads(raw)
    except HTTPError as exc:
        raise BoardError('GitHub授权被拒绝；请由仓库有权者提供仅此仓库的Administration读写临时授权，生成的部署密钥仅只读。HTTP '+str(exc.code),409) from None
    except (URLError,ValueError):raise BoardError('GitHub响应未知，重试会先按公钥核对，不能直接重复创建',502) from None

def atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temp.open('x',encoding='utf8') as f:os.chmod(temp,0o600);f.write(canonical(value));f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        if temp.exists():temp.unlink()

class Onboarding:
    def __init__(self,store):self.tracking=Tracking(store);self.store=store
    def location(self,rid):return self.tracking.root/'_private/git-onboarding'/self.tracking.project/(repo_id(rid)+'.json')
    def status(self,rid):
        rid=repo_id(rid);repo=self.tracking.state()['repos'].get(rid)
        if not repo:raise BoardError('本项目仓库不存在',404)
        path=self.location(rid)
        data=json.loads(path.read_text('utf8')) if path.exists() else {'stage':'bound','next_owner':'project_SE','next':'申请专属只读公钥'}
        if not path.exists() and repo.get('synced_at') and repo.get('refs'):
            try:
                self.tracking.mirror(rid,repo);data={'stage':'ready','origin':'existing_verified_mirror','next_owner':'NAS_tracker','next':'已有接入可继续使用，保留原repo ID与审计链','synced_at':repo['synced_at']}
            except BoardError:pass
        if not repo['enabled']:data={**data,'stage':'disabled','next_owner':'project_SE','next':'仓库已停用；原始审计和镜像受控保留，新读取被拒绝'}
        if data.get('stage')=='awaiting_github_authorization':data={**data,'next':'优先用本机现有gh/Git管理授权登记NAS公钥，然后核验接入；也可手动登记，无需新建token。'}
        return {k:v for k,v in data.items() if k not in ('key','credential')}
    def request(self,actor,p):
        from .governance import role
        from .operations import manager
        fields(p,{'repo'},{'repo'});rid=repo_id(p['repo'])
        with self.store.connection() as db:manager(role(db,actor))
        with LOCK:
            repo=self.tracking.state()['repos'].get(rid)
            if not repo or not repo['enabled']:raise BoardError('项目仓库不存在或已停用',409)
            path=self.location(rid)
            root=path.parent;root.mkdir(parents=True,exist_ok=True,mode=0o700);key=root/(rid+'.ed25519')
            if path.exists():
                intent=json.loads(path.read_text('utf8'))
                if (intent.get('project'),intent.get('repo'),intent.get('repository'))!=(self.tracking.project,rid,repo['repository']):raise BoardError('接入收据归属不匹配',409)
                if intent.get('public_key'):return self.status(rid)
                if intent.get('stage')!='key_preparing':raise BoardError('生成结果待恢复核对',409)
            else:
                if key.exists():raise BoardError('发现未登记密钥，需恢复归属，不能覆盖',409)
                atomic(path,{'project':self.tracking.project,'repo':rid,'repository':repo['repository'],'actor':actor['id'],'stage':'key_preparing','at':time.time(),'next_owner':'NAS_broker','next':'生成或恢复同一专属公钥'})
            if key.is_symlink() or root.is_symlink():raise BoardError('私有接入目录不能为链接',409)
            from tools.owned_process import run
            if not key.exists():
                code,_,_=run(['ssh-keygen','-q','-t','ed25519','-N','','-C','project-board:'+self.tracking.project+':'+rid,'-f',str(key)],cwd=root,evidence=root/'audit',purpose='generate project repository read-only deploy key',timeout=15)
                if code:raise BoardError('NAS密钥生成失败',503)
            os.chmod(key,0o600)
            code,out,_=run(['ssh-keygen','-y','-f',str(key)],cwd=root,evidence=root/'audit',purpose='reconcile public key with pre-effect owned intent',timeout=15)
            if code:raise BoardError('专属密钥生成结果需恢复',409)
            public=out.decode('utf8').strip()
            data={'project':self.tracking.project,'repo':rid,'repository':repo['repository'],'stage':'awaiting_github_authorization','public_key':public,'key':str(key),'actor':actor['id'],'at':time.time(),'next_owner':'repository_authority','next':'SE优先用本机现有GitHub管理授权登记此公钥，再核验接入；也可手动登记或使用单仓库临时授权。'}
            atomic(path,data);return self.status(rid)
    def complete(self,actor,p):
        """Verify external registration using only the NAS key, never a receipt.

        Authentication binds the key to this repository. A no-input upload-pack
        handshake proves read access; GitHub must explicitly deny receive-pack
        as read-only. No ref update or pack is sent. All other failures reject.
        """
        fields(p,{'repo','repository','public_key'},{'repo','repository','public_key'})
        rid=repo_id(p['repo']);self.request(actor,{'repo':rid})
        with LOCK:
            path=self.location(rid);data=json.loads(path.read_text('utf8'));repo=self.tracking.state()['repos'][rid]
            if not repo['enabled'] or repo['repository']!=p['repository'] or data['repository']!=repo['repository'] or data['public_key']!=p['public_key']:raise BoardError('公钥或仓库绑定已变化；重读当前接入信息',409)
            from tools.owned_process import run
            key=Path(data['key']);private=self.tracking.root/'_private'
            if not key.resolve().is_relative_to(private.resolve()) or key.is_symlink() or not key.is_file():raise BoardError('专属私钥归属无效',409)
            args=['ssh','-F',os.devnull,'-i',str(key),'-o','UserKnownHostsFile="'+str(private/'github-known-hosts')+'"','-o','IdentitiesOnly=yes','-o','IdentityAgent=none','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=10','git@github.com']
            def probe(command):
                try:return run(args+command,cwd=self.tracking.root,evidence=path.parent/'audit',purpose='Verify fixed GitHub deployment-key capability without ref updates',input_data=b'',timeout=30)
                except (OSError,TimeoutError,subprocess.TimeoutExpired):raise BoardError('NAS GitHub核验超时或不可用；旧镜像保留，不能当作只读通过',502) from None
            try:
                code,out,err=probe(['-T'])
                expected="Hi "+repo['repository']+"! You've successfully authenticated, but GitHub does not provide shell access."
                if code!=1 or (out+err).decode(errors='replace').strip().casefold()!=expected.casefold():raise BoardError('GitHub未确认此公钥属于目标仓库部署密钥；检查本机登记及NAS网络/主机密钥',409)
                code,out,err=probe(["git-upload-pack '"+repo['repository']+".git'"])
                if code!=0 or len(out)<4 or out[:4].strip(b'0123456789abcdef'):raise BoardError('GitHub未确认目标仓库可读；不能启用镜像',409)
                code,out,err=probe(["git-receive-pack '"+repo['repository']+".git'"])
                if code!=1 or out or err.strip()!=b'ERROR: The key you are authenticating with has been marked as read only.':raise BoardError('GitHub未明确确认只读拒写；可写密钥及未知错误均不接入，请核对部署密钥未勾选写权限',409)
                # Recheck after external I/O; stopping a repo must win the race.
                latest=self.tracking.state()['repos'][rid]
                if not latest['enabled'] or latest['repository']!=repo['repository']:raise BoardError('核验期间仓库已停用或变化',409)
                config=private/'github.json';current=json.loads(config.read_text('utf8')) if config.exists() else {'projects':{}}
                entries=current.setdefault('projects',{}).setdefault(self.tracking.project,{})
                if rid in entries and (entries[rid].get('repository')!=repo['repository'] or entries[rid].get('key')!=str(key)):raise BoardError('已有接入绑定不匹配；不能静默替换',409)
                entries[rid]={'repository':repo['repository'],'key':str(key),'authorization':'github_verified_readonly_deploy_key'}
                atomic(config,current)
                data.update(stage='authorized',read_only=True,verification='github_ssh_repository_identity_read_and_explicit_readonly_denial',verified_at=time.time(),next_owner='NAS_broker',next='同步真实Git引用与对象')
                atomic(path,data)
            except BoardError as exc:
                data.update(stage='verification_failed',next_owner='project_SE',next=str(exc));atomic(path,data);raise
        return self.sync(actor,{'repo':rid})
    def authorize(self,actor,p):
        fields(p,{'repo','grant'},{'repo','grant'});rid=repo_id(p['repo']);token=p['grant']
        if type(token) is not str or not token.startswith('github_pat_') or not 40<len(token)<500:raise BoardError('仅接受所选单仓库短期fine-grained授权；不接受账号级classic PAT')
        self.request(actor,{'repo':rid})
        with LOCK:
            path=self.location(rid);data=json.loads(path.read_text('utf8'));repo=self.tracking.state()['repos'][rid]
            if repo['repository']!=data['repository'] or not repo['enabled']:raise BoardError('仓库授权范围已变化',409)
            api='/repos/'+repo['repository'];key=data['public_key'].split()[:2]
            try:
                # The external API, not a submitted receipt, proves authority.
                metadata=github(token,'GET',api)
                if metadata.get('full_name','').lower()!=repo['repository'].lower():raise BoardError('GitHub仓库身份不匹配',409)
                found=[]
                for page in range(1,11):
                    rows=github(token,'GET',api+'/keys?per_page=100&page='+str(page));found += rows
                    if len(rows)<100:break
                else:raise BoardError('部署密钥数量超限；需缩小治理范围',409)
                entry=next((x for x in found if x['key'].split()[:2]==key),None)
                if not entry:entry=github(token,'POST',api+'/keys',{'title':'project-board '+self.tracking.project+' '+rid,'key':data['public_key'],'read_only':True})
                verified=github(token,'GET',api+'/keys/'+str(entry['id']))
                if verified.get('read_only') is not True or verified.get('key','').split()[:2]!=key:raise BoardError('GitHub未确认专属只读密钥，拒绝启用',409)
                data.update(stage='authorized',github_key=verified['id'],read_only=True,verified_at=time.time(),next_owner='NAS_broker',next='同步并核对真实refs和Git对象')
                config=self.tracking.root/'_private/github.json';current=json.loads(config.read_text('utf8')) if config.exists() else {'projects':{}}
                entries=current.setdefault('projects',{}).setdefault(self.tracking.project,{})
                if rid in entries and entries[rid].get('repository')!=repo['repository']:raise BoardError('已有实例接入绑定不匹配',409)
                entries[rid]={'repository':repo['repository'],'key':data['key'],'authorization':'github_verified_readonly_deploy_key','github_key':verified['id']};atomic(config,current);atomic(path,data)
            except BoardError as exc:
                data.update(stage='authorization_failed',next_owner='repository_authority',next=str(exc));atomic(path,data);raise
            finally:token=None;p['grant']='[discarded]'
        return self.sync(actor,{'repo':rid})
    def sync(self,actor,p,stop_requested=lambda:False):
        from .governance import role
        from .operations import manager
        fields(p,{'repo'},{'repo'});rid=repo_id(p['repo'])
        with self.store.connection() as db:manager(role(db,actor))
        path=self.location(rid)
        if path.exists() and json.loads(path.read_text('utf8')).get('stage')=='verification_failed':raise BoardError('先重新核验只读接入；拉取成功不能代替只读核验，旧镜像保留',409)
        config=self.tracking.root/'_private/github.json'
        try:entry=json.loads(config.read_text('utf8'))['projects'][self.tracking.project][rid]
        except (FileNotFoundError,KeyError):raise BoardError('先完成GitHub单仓库授权',409)
        from tools.github_tracker import synchronize
        synchronize(self.tracking,actor,rid,entry,stop_requested)
        path=self.location(rid)
        if path.exists():
            data=json.loads(path.read_text('utf8'));repo=self.tracking.state()['repos'][rid]
            data.update(stage='sync_failed' if repo.get('sync_error') else 'ready',next_owner='project_SE' if repo.get('sync_error') else 'NAS_broker',next=repo.get('sync_error') or '只读镜像就绪；使用原Git证据核验门禁',synced_at=repo.get('synced_at'));atomic(path,data)
        return self.status(rid)
