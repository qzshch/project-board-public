"""Project SE read-only onboarding. Never journal the transient GitHub grant.

A selected-repository fine-grained grant authorizes GitHub's deploy-key API.
Only the generated repository-specific read-only key remains on NAS. No input
can choose a local path, host, command or remote. Unknown API effects reconcile
by key before another create. Existing operator mirrors remain compatible.
"""
import json, os, threading, uuid, time
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
            data={'project':self.tracking.project,'repo':rid,'repository':repo['repository'],'stage':'awaiting_github_authorization','public_key':public,'key':str(key),'actor':actor['id'],'at':time.time(),'next_owner':'repository_authority','next':'SE使用所选单仓库短期fine-grained授权完成外部登记；只保存NAS专属只读密钥'}
            atomic(path,data);return self.status(rid)
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
