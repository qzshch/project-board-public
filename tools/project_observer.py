"""Operator-approved read-only GitHub and local resource probes.

No command/URL/path is accepted from board records as execution authority.
Results attest observations under the registered project runner identity.
"""
import argparse,hashlib,json,re,sys,time,uuid
from pathlib import Path,PurePosixPath
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.parse import quote,urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.task_board_client import Client,suite_digest as digest
from tools.coordination_client import atomic_json

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('Redirects are not authorized')

def read_json(url,token='',method='GET'):
    headers={'Accept':'application/vnd.github+json','User-Agent':'project-board-observer/1','X-GitHub-Api-Version':'2026-03-10'}
    if token:headers['Authorization']='Bearer '+token
    with build_opener(NoRedirect).open(Request(url,headers=headers,method=method),timeout=15) as response:
        if method=='HEAD':return {'status':response.status}
        raw=response.read(4*1024*1024+1)
        if len(raw)>4*1024*1024:raise ValueError('Observation response exceeds 4MiB')
        return json.loads(raw)

def file_path(path):
    p=Path(path)
    if not p.is_absolute():raise ValueError('Use operator-approved absolute paths')
    for part in (p,*p.parents):
        if part.is_symlink() or hasattr(part,'is_junction') and part.is_junction():raise ValueError('Probe does not follow links')
    if any(x.casefold() in ('_private','.ssh','.git') or x.casefold().startswith('.env') for x in p.parts):raise ValueError('Credential/configuration paths are not probe inputs')
    return p

def file_sha(path,limit=256*1024*1024):
    path=file_path(path)
    if path.stat().st_size>limit:raise ValueError('Probe file exceeds bound')
    h=hashlib.sha256();size=0
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            size+=len(block)
            if size>limit:raise ValueError('Growing file exceeded probe bound')
            h.update(block)
    return h.hexdigest()

def probe_resource(entry,config):
    if config['entry_hash']!=digest(entry):raise ValueError('Locally approved entry changed')
    if config['mode']=='http':
        url=config['url']
        if not any(l['kind']=='http' and l['location']==url for l in entry['locations']):raise ValueError('Locally approved URL not in fixed entry')
        parsed=urlsplit(url)
        if parsed.scheme not in ('http','https') or parsed.username or parsed.password or parsed.query or parsed.fragment:raise ValueError('Stable HTTP(S) resource required')
        result=read_json(url,method='HEAD');return ('reachable','',result)
    path=file_path(config['path'])
    if not path.exists():return ('missing','',{'exists':False})
    if config['mode']=='directory':
        if not path.is_dir() or entry['integrity']['kind']!='none':raise ValueError('Directory reachability does not verify a file/manifest')
        return ('reachable','',{'exists':True,'kind':'directory'})
    if config['mode'] not in ('file','manifest') or entry['integrity']['kind']!=config['mode']:raise ValueError('Probe mode and entry integrity disagree')
    sha=file_sha(path);details={'sha256':sha}
    if sha!=entry['integrity']['sha256']:return ('mismatch',sha,details)
    if config['mode']=='manifest':
        if path.stat().st_size>1024*1024:raise ValueError('Manifest exceeds 1MiB')
        manifest=json.loads(path.read_text('utf8'));files=manifest['files']
        if type(files) is not dict or not 1<=len(files)<=512:raise ValueError('Manifest requires 1..512 exact relative files')
        total=0;results={}
        for rel,row in files.items():
            rp=PurePosixPath(rel)
            if rp.is_absolute() or '..' in rp.parts or '\\' in rel or ':' in rel or str(rp)!=rel:raise ValueError('Manifest path escapes approved root')
            item=file_path(path.parent/rel)
            if not item.resolve().is_relative_to(path.parent.resolve()):raise ValueError('Manifest escaped root')
            total+=item.stat().st_size
            if total>256*1024*1024:raise ValueError('Manifest bytes exceed limit')
            expected=row['sha256'] if type(row) is dict else row
            if type(expected) is not str or not re.fullmatch('[0-9a-f]{64}',expected):raise ValueError('Manifest digest invalid')
            results[rel]=file_sha(item)==expected
        details['files']=results
        if not all(results.values()):return ('mismatch',sha,details)
    return ('verified',sha,details)

def probe_github(gate,config,fetch=read_json):
    if config['gate_hash']!=gate['gate_hash']:raise ValueError('Locally approved gate changed')
    repo=config['repository']
    if not re.fullmatch('[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):raise ValueError('Exact GitHub repository required')
    token=Path(config['token_file']).read_text('utf8').strip() if config.get('token_file') else ''
    commit=gate['input_anchor'][4:];url='https://api.github.com/repos/'+repo
    if gate['kind']=='github_pr':
        data=fetch(url+'/pulls/'+str(gate['pr']),token)
        # A merged PR can have an earlier head; exact input is either the
        # reviewed head or its explicit merge commit, never a branch name.
        passed=data.get('merged') is True and commit in (data.get('merge_commit_sha'),data.get('head',{}).get('sha')) and data.get('base',{}).get('repo',{}).get('full_name')==repo
        return ('passed' if passed else 'pending',{}, {'pr':gate['pr'],'merged':data.get('merged'),'head':data.get('head',{}).get('sha'),'merge_commit':data.get('merge_commit_sha')})
    app_id=gate['app_id']
    if type(app_id) is not int or app_id<=0 or config.get('app_id',app_id)!=app_id:raise ValueError('Exact approved GitHub App source required')
    runs=[]
    for page in range(1,6):
        data=fetch(url+'/commits/'+commit+'/check-runs?per_page=100&page='+str(page),token);chunk=data['check_runs'];runs+=chunk
        if len(chunk)<100:break
    else:raise ValueError('Check runs exceed bounded pages')
    states={};details={}
    for name in gate['checks']:
        candidates=[r for r in runs if r.get('name')==name and r.get('head_sha')==commit and r.get('app',{}).get('id')==app_id]
        item=max(candidates,key=lambda r:r['id'],default=None);states[name]='success' if item and item['status']=='completed' and item.get('conclusion')=='success' else 'failure' if item and item['status']=='completed' and item.get('conclusion') not in ('neutral','skipped',None) else 'pending'
        details[name]={k:item.get(k) for k in ('id','head_sha','status','conclusion')} if item else None
    return ('passed' if all(x=='success' for x in states.values()) else 'failed' if 'failure' in states.values() else 'pending',states,details)

def observe(client,config,target,output):
    if config['project_id']!=client.project:raise ValueError('Observer config belongs to another project')
    output=Path(output)/target;output.mkdir(parents=True,exist_ok=True);pending=output/'PENDING.json'
    if pending.exists():
        request=json.loads(pending.read_text('utf8'));result=client.call('/api/operations',request);pending.unlink();return result
    data=client.call('/api/coordination');now=time.time();ident=uuid.uuid4().hex
    if target in config.get('conditions',{}):
        gate=data['gates'][target];local=config['conditions'][target]
        # Gate repository mapping is checked against actual project binding.
        git=client.call('/api/git');assert git['repos'][gate['repo']]['repository']==local['repository'],'Repository binding differs from local approval'
        try:status,checks,details=probe_github(gate,local)
        except Exception as error:
            status='blocked';checks={name:'pending' for name in gate['checks']};details={'failure_class':type(error).__name__,'reason':'Approved GitHub observation unavailable; no success inferred'}
        p={'id':target,'gate_hash':gate['gate_hash'],'commit':gate['input_anchor'][4:],'checks':checks,'pr':gate['pr'],'status':status,'summary':'Exact fixed repository/input read-only GitHub observation','evidence':[]};action='condition_observe'
    else:
        local=config['resources'][target];entry=client.call('/api/resources/'+quote(target,safe=''))['entry']
        try:status,sha,details=probe_resource(entry,local)
        except Exception as error:
            status='blocked';sha='';details={'failure_class':type(error).__name__,'reason':'Approved local probe unavailable; original bytes and permissions unchanged'}
        p={'id':target,'entry_version':entry['entry_version'],'entry_hash':digest(entry),'status':status,'observed_sha256':sha,'ttl':local.get('ttl',3600),'summary':'Locally approved resource probe; original bytes were not uploaded','evidence':[]};action='resource_observe'
    log=output/(ident+'.json');atomic_json(log,{'target':target,'started':now,'finished':time.time(),'status':status,'details':details});p['evidence']=[{'path':str(log),'sha256':file_sha(log)}]
    state=client.call('/api/operations');request={'request_id':ident,'expected_revision':state['revision'],'action':action,'payload':p};atomic_json(pending,request);result=client.call('/api/operations',request);pending.unlink();atomic_json(output/(ident+'-receipt.json'),result);return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);p.add_argument('--config',required=True);p.add_argument('--target',required=True);p.add_argument('--output',required=True);p.add_argument('--connect-ip');a=p.parse_args();profile=json.loads(Path(a.profile).read_text('utf8'));config=json.loads(Path(a.config).read_text('utf8'));c=Client(profile['url'],profile,a.connect_ip)
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,99}',a.target):raise ValueError('Invalid target ID')
    print(json.dumps(observe(c,config,a.target,a.output)))
if __name__=='__main__':main()
