"""SE-local GitHub registration. Broad credentials never leave this computer.

Only fixed api.github.com repository/key endpoints are called. A registered
public key is reconciled before creation; NAS independently verifies capability.
Run from github-kit.zip. Profiles, subprocess audit and receipts stay outside Git.
"""
import argparse,json,os,shutil,sys,subprocess,re
from pathlib import Path
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
from urllib.parse import quote
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.task_board_client import Client,ClientError,read,save
from tools.owned_process import run

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*a,**k):return None

class GitHub:
    def __init__(self,source,evidence):
        self.source=source;self.evidence=evidence;self.secret=None
        self.env={**os.environ,'GH_HOST':'github.com','GH_PROMPT_DISABLED':'1','GIT_TERMINAL_PROMPT':'0','GCM_INTERACTIVE':'never','GIT_TRACE':'','GIT_TRACE_CURL':'','GIT_CURL_VERBOSE':''}
        # Reject diagnostic modes that could write Authorization headers.
        self.env.pop('GH_DEBUG',None)
    def command(self,args,data=None):
        try:return run(args,cwd=self.evidence,evidence=self.evidence,purpose='SE local GitHub API/credential operation; secret output kept in memory only',input_data=data,env=self.env,timeout=35)
        except (OSError,TimeoutError,subprocess.TimeoutExpired):raise ClientError('本机GitHub工具不可用或超时；没有向NAS发送GitHub凭据') from None
    def select(self,repository):
        if self.source in ('auto','gh') and shutil.which('gh'):
            code,out,err=self.command(['gh','api','--hostname','github.com','/user'])
            if code==0:self.source='gh';return
            if self.source=='gh':raise ClientError('本机gh未具备有效登录；不会自动弹出登录或创建token')
        if self.source=='gh':raise ClientError('未安装gh；可改用--credential-source git复用Git凭据')
        code,raw,err=self.command(['git','-c','credential.interactive=false','credential','fill'],('protocol=https\nhost=github.com\npath='+repository+'.git\n\n').encode())
        if code:raise ClientError('没有可复用的GitHub本机凭据；可手动在仓库设置登记NAS公钥，再在面板核验，无需给公告板token')
        credentials=dict(line.split('=',1) for line in raw.decode().splitlines() if '=' in line);self.secret=credentials.get('password');credentials.clear();raw=None
        if not self.secret:raise ClientError('本机Git凭据无可用授权')
        self.source='git'
    def call(self,method,path,body=None):
        if self.source=='gh':
            args=['gh','api','--hostname','github.com','--method',method,'-H','Accept: application/vnd.github+json','-H','X-GitHub-Api-Version: 2022-11-28',path]
            if body is not None:args+=['--input','-']
            code,out,err=self.command(args,json.dumps(body).encode() if body is not None else None)
            if code:raise ClientError('GitHub API拒绝或响应未知；检查本机账号的目标仓库管理权限，原样重试会先核对同一公钥')
            try:return json.loads(out)
            except ValueError:raise ClientError('GitHub API响应无效；不接受本地自报通过') from None
        req=Request('https://api.github.com'+path,method=method,data=json.dumps(body).encode() if body is not None else None,headers={'Authorization':'Bearer '+self.secret,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/json','User-Agent':'project-board-SE-local-onboarding'})
        try:
            with build_opener(NoRedirect).open(req,timeout=30) as response:
                raw=response.read(2*1024*1024)
                if len(raw)>=2*1024*1024:raise ClientError('GitHub响应超限')
                return json.loads(raw)
        except HTTPError as exc:raise ClientError('GitHub API拒绝，HTTP '+str(exc.code)+'；检查本机账号是否有本仓库部署密钥管理权限') from None
        except (URLError,ValueError):raise ClientError('GitHub响应未知；重试先按同一公钥核对，不重复建密钥') from None
    def close(self):self.secret=None

def connect(client,rid,evidence,source='auto'):
    if not client.project:raise ClientError('必须使用本项目SE身份，不接受无项目的管理员入口')
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,47}',rid):raise ClientError('仓库ID无效')
    evidence=Path(evidence).resolve()
    if os.name=='nt' and evidence.drive.casefold()=='c:':raise ClientError('请将接入证据放在C盘之外')
    evidence.mkdir(parents=True,exist_ok=True)
    base='/api/git-onboarding';state=client.call(base+'?repo='+rid)
    if state['stage']=='ready':return {'project':client.project,'repo':rid,'stage':'ready','existing_connection':True,'github_credential_sent_to_NAS':False}
    state=client.call(base+'/request',{'repo':rid},timeout=45);repository=state['repository'];public=state['public_key']
    # Repository comes from the authenticated server, never a CLI URL/command.
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository) or public.split()[0]!='ssh-ed25519':raise ClientError('服务端仓库或公钥无效')
    github=GitHub(source,evidence)
    try:
        github.select(repository);api='/repos/'+repository;meta=github.call('GET',api)
        if meta.get('full_name','').casefold()!=repository.casefold():raise ClientError('GitHub仓库与公告板绑定不符')
        entry=None
        for page in range(1,11):
            rows=github.call('GET',api+'/keys?per_page=100&page='+str(page))
            entry=next((x for x in rows if x.get('key','').split()[:2]==public.split()[:2]),entry)
            if len(rows)<100:break
        else:raise ClientError('密钥列表超限，需先核对，未创建密钥')
        if entry and entry.get('read_only') is not True:raise ClientError('同一公钥已有写权限；请在GitHub纠正，不自动删除或降权已有密钥')
        entry=entry or github.call('POST',api+'/keys',{'title':'project-board '+client.project+' '+rid,'key':public,'read_only':True})
        verified=github.call('GET',api+'/keys/'+str(entry['id']))
        if verified.get('read_only') is not True or verified.get('key','').split()[:2]!=public.split()[:2]:raise ClientError('GitHub未确认同一公钥只读，拒绝接入')
    finally:github.close()
    # The server accepts no client assertion/key ID as authorization evidence.
    result=client.call(base+'/complete',{'repo':rid,'repository':repository,'public_key':public},timeout=210)
    receipt={'project':client.project,'repo':rid,'repository':repository,'stage':result['stage'],'read_only':result.get('read_only'),'verification':result.get('verification'),'github_credential_sent_to_NAS':False}
    save(evidence/'github-connect-receipt.json',receipt);return receipt

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--profile',type=Path,required=True);p.add_argument('--repo',required=True);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--credential-source',choices=['auto','gh','git'],default='auto');args=p.parse_args()
    try:
        profile=read(args.profile);result=connect(Client(profile['url'],profile),args.repo,args.evidence,args.credential_source);print(json.dumps(result,ensure_ascii=False));return 0 if result['stage']=='ready' else 1
    except ClientError as e:print(json.dumps({'error':str(e),'secret_printed':False},ensure_ascii=False));return 1
if __name__=='__main__':raise SystemExit(main())
