"""Locally authorized pull agent. Run: python -m tools.agent_node --config PRIVATE_JSON.

The local configuration is the authority for executable argv, environment,
projects, roots and SE profiles. The NAS can only choose within that set.
"""
import argparse,hashlib,json,os,re,secrets,signal,socket,threading,time,uuid
from pathlib import Path
from tools.task_board_client import Client,ClientError,read,save
from tools.agent_runtime import Runtime,ProtocolError,Busy,Uncertain

def authorize_config(path,profile_path):
    """A project SE declares only this machine's already-authorized local config."""
    config=read(path);profile=read(profile_path);pid=profile.get('project_id')
    if not pid or set(config['projects'])!={pid}:raise ValueError('SE自助接入配置只能包含身份所属的一个项目')
    if config['url'].rstrip('/')!=profile['url'].rstrip('/'):raise ValueError('项目身份与本机配置的公告板实例不一致')
    roles=config['projects'][pid]['roles']
    if type(roles) is not list or not roles or any(r not in ('se','worker') for r in roles) or len(roles)!=len(set(roles)):raise ValueError('本机角色需SE、Worker或两者')
    client=Client(config['url'],profile,config.get('connect_ip'),pid);me=client.call('/api/me')
    if me.get('global_admin') or me.get('project_role') not in ('owner','se','reviewer'):raise ValueError('自助接入使用本项目SE身份，不能使用Worker或实例管理员身份')
    prefix='pn-'+hashlib.sha256(pid.encode()).hexdigest()[:16]+'-';alias=config['id'][len(prefix):] if config['id'].startswith(prefix) else config['id']
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,69}',alias):raise ValueError('本机项目内名称需1～70位安全标识')
    config['id']=prefix+alias
    if 'se' in roles:
        current=config['projects'][pid].get('se_profile')
        if current and Path(current).resolve()!=Path(profile_path).resolve():raise ValueError('本机SE会话需沿用授权接入的项目SE身份')
        config['projects'][pid]['se_profile']=str(Path(profile_path).resolve())
    target=Path(config['state']).resolve()/'se-node-config.json'
    if os.name=='nt' and target.drive.upper()=='C:':raise ValueError('节点状态需放C盘外')
    if target.exists() and read(target)!=config:raise ValueError('本机已冻结其他节点配置；核对原接入端或使用新的状态目录')
    save(target,config)
    return target,client,{'alias':alias,'name':config.get('name') or socket.gethostname(),'roles':roles}

class Node:
    def __init__(self,path):
        self.path=Path(path).resolve();self.config=read(path);c=self.config
        self.home=Path(c['state']).resolve()
        if os.name=='nt' and self.home.drive.upper()=='C:':raise ValueError('节点状态、日志和项目根需放C盘外')
        self.home.mkdir(parents=True,exist_ok=True,mode=0o700);self.stop=threading.Event();self.drivers={};self.caps={};self.current=None;self.lock=threading.RLock();self.acknowledged_sessions={}
        if type(c['max_parallel']) is not int or not 1<=c['max_parallel']<=32:raise ValueError('max_parallel需1～32')
        for pid,project in c['projects'].items():
            for alias,root in project['roots'].items():
                p=Path(root).resolve()
                if not p.is_dir() or os.name=='nt' and p.drive.upper()=='C:':raise ValueError('项目根不存在或位于C盘')
        self.guard=(self.home/'running.lock').open('a+b')
        try:
            if os.name=='nt':
                import msvcrt
                self.guard.seek(0);self.guard.write(b'0');self.guard.flush();self.guard.seek(0);msvcrt.locking(self.guard.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.guard.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:self.guard.close();raise ValueError('同一节点状态已有运行实例') from None
        try:
            seed=self.home/'node-private.json'
            if not seed.exists():save(seed,{'id':c['id'],'token':'node.'+secrets.token_urlsafe(40)})
            self.seed=read(seed)
            if self.seed['id']!=c['id']:raise ValueError('节点ID不可替换已有身份')
            self.client=Client(c['url'],{'url':c['url'],'token':self.seed['token']},c.get('connect_ip'))
            from tools.usage_collector import Spool
            self.usage_spool=Spool(self.home/'usage');self.usage_clients={}
            # Pending usage outlives a runtime/job. Rebuild only clients whose
            # private profile and locally-owned binding still match this node.
            for receipt in (self.home/'bindings').glob('*.json'):
                identity=read(receipt).get('identity',{});project=c['projects'].get(identity.get('project'))
                if not project or identity.get('role') not in project['roles']:continue
                path=Path(project.get('se_profile','')) if identity['role']=='se' else self.home/'profiles'/(identity['id']+'.json')
                if not path.is_file():continue
                local=read(path)
                if local.get('actor')==identity.get('actor') and local.get('project_id')==identity.get('project'):self.usage_clients[identity['id']]=Client(c['url'],local,c.get('connect_ip'),identity['project'])
            for config in c['runtimes'].values():
                command=config['command']
                if type(command) is not list or not command or any(type(x) is not str for x in command):raise ValueError('运行时启动命令需本机固定argv数组')
                if Path(command[0]).name.lower() in ('cmd.exe','powershell.exe','pwsh.exe') or Path(command[0]).suffix.lower() in ('.cmd','.bat'):raise ValueError('请使用运行时实际可执行文件，避免另开控制台的Shell包装')
        except BaseException:self.guard.close();raise
    def enroll(self,pair_path):
        pair=read(pair_path)
        if pair['id']!=self.config['id']:raise ValueError('接入文件与节点ID不同')
        result=self.client.call('/api/node/enroll',{'id':pair['id'],'pair':pair['pair']});save(self.home/'enrollment.json',result);return result
    def probe(self):
        for kind,config in self.config['runtimes'].items():
            runtime=None;project=next(iter(self.config['projects'].values()));root=next(iter(project['roots'].values()))
            try:
                runtime=Runtime(kind,config,root,self.home/'probe'/kind,next(iter(config.get('models',[])),None));models=runtime.models()
                self.caps[kind]={'ready':bool(models),'version':getattr(runtime,'native_version',config['version']),'models':models,'roots':{pid:list(p['roots']) for pid,p in self.config['projects'].items()},'reason':'真实协议握手与模型路由核对；Zcode含连通检查；Antigravity模型发现不代表每个路由已实跑' if models else '未发现可派发模型'}
            except (OSError,ProtocolError,ValueError,KeyError) as exc:
                save(self.home/'probe'/kind/'failure.json',{'type':type(exc).__name__,'detail':str(exc),'at':time.time()})
                self.caps[kind]={'ready':False,'version':config.get('version','unknown'),'models':[],'roots':{},'reason':type(exc).__name__+'：探测未通过，详见本机私有probe报告'}
            finally:
                if runtime:runtime.close()
        save(self.home/'capabilities.json',self.caps);return self.caps
    def validate(self,b):
        p=self.config['projects'].get(b['project']);runtime=self.config['runtimes'].get(b['runtime'])
        if not p or b['root'] not in p['roots'] or not runtime or b['model'] not in self.caps.get(b['runtime'],{}).get('models',[]):raise ProtocolError('远端选择超出本机项目、根或模型授权')
        if b['role'] not in p['roles']:raise ProtocolError('本机未允许该项目角色')
        return p,runtime,Path(p['roots'][b['root']]).resolve()
    def occupied(self,driver):
        if not driver.ready_session:return False
        try:return driver.busy(driver.ready_session)
        except (ProtocolError,Uncertain):return True
    def profile(self,b,p):
        if b['role']=='se':
            path=Path(p['se_profile']).resolve();profile=read(path)
        else:
            path=self.home/'profiles'/(b['id']+'.json')
            if not path.exists():save(path,{**self.client.call('/api/node/profile',{'binding':b['id']}),'url':self.config['url']})
            profile=read(path)
        if profile.get('project_id')!=b['project'] or profile.get('actor')!=b['actor']:raise ProtocolError('本机会话身份与绑定项目/角色不匹配')
        client=Client(self.config['url'],profile,self.config.get('connect_ip'),b['project']);me=client.call('/api/me')
        if me.get('actor')!=b['actor']:raise ProtocolError('身份读回不匹配')
        if b['role']=='se' and me.get('project_role') not in ('owner','se','reviewer'):raise ProtocolError('本机SE身份已移交或失去管理权限')
        if b['role']=='worker' and me.get('project_role') not in ('worker','agent','tester','researcher','developer'):raise ProtocolError('本机Worker身份已失效或降为只读')
        if b['role']=='worker':
            task=client.task(b['task'])
            if task['scope_hash']!=b['scope'] or task['scope_version']!=b.get('scope_version'):raise ProtocolError('任务范围已变化，需SE明确确认后恢复原会话')
        return path,client
    def prompt(self,job,profile,client):
        b=job['binding'];body=job['body'];tid=body.get('task') or b['task'];url=self.config['url']+'/?project='+b['project']
        # Only references + current authorized context, never model keys or
        # another project's full snapshot. Raw output stays in the runtime.
        context=client.call('/api/convergence/context?task='+__import__('urllib.parse',fromlist=['quote']).quote(tid,safe='')) if tid else {'workbench':'/api/convergence','inbox':'/api/workflow/inbox'}
        rules=[rule['command'] for rule in self.config['runtimes'][b['runtime']].get('approved_commands',[]) if rule.get('project')==b['project'] and rule.get('role')==b['role'] and (not rule.get('binding') or rule['binding']==b['id']) and Path(rule['cwd']).resolve()==Path(self.config['projects'][b['project']]['roots'][b['root']]).resolve()]
        return '\n'.join(['你作为本项目'+('SE' if b['role']=='se' else 'Worker')+'工作。仅处理项目 '+b['project']+'，不得混用其他项目上下文。','公告板 '+url,'本机私有项目身份路径：'+str(profile)+'（仅工具读取，不输出内容/凭据）。','本机预先核准命令（仍逐次核对脚本哈希）：'+json.dumps(rules,ensure_ascii=False),'环境变量PROJECT_BOARD_PROFILE与PROJECT_BOARD_PROJECT只指向本会话身份及项目。','任务 '+(tid or 'SE工作台')+'；固定范围 '+b['scope'],'事件通知 '+json.dumps(body,ensure_ascii=False),'当前接手上下文 '+json.dumps(context,ensure_ascii=False),'Worker在线核对并自行领取指定任务；留言后自行决定是否等待，已有SE stop必须遵守。完成后提交成果、记录、结论、证据到待评审队列，不自行冒充验收。SE回复写回原评论；可按具体任务/动作委派独立复核，保留原门禁。','如果当前范围、依赖或权限不满足，登记真实卡点，不伪造历史PASS或改绑项目。'])
    def report(self,job,status,session,summary):
        payload={'job':job['job'],'lease':job['lease'],'status':status,'session':session,'summary':summary}
        path=self.home/'receipts'/(job['job']+'.report.json');save(path,payload)
        # Server binds lease and terminal result; retry only this frozen report.
        for attempt in range(3):
            try:
                result=self.client.call('/api/node/report',payload)
                if status=='accepted' and session:self.acknowledged_sessions[job['binding']['id']]=session
                return result
            except ClientError as exc:
                if exc.status not in (0,502,503,504) or attempt==2:raise
                self.stop.wait(.5*(attempt+1))
    def beat(self):
        while not self.stop.is_set():
            try:
                self.heartbeat()
                with self.lock:job=self.current
                if job:self.report(job,'heartbeat',job['binding'].get('session'),'准备/发送/等待阶段续租')
            except ClientError as exc:
                if exc.status in (401,403):self.stop.set()
            self.stop.wait(15)
    def heartbeat(self):
        # Infrastructure can report a native permission failure even when the
        # model cannot execute its board client. This is not a Worker comment
        # or permission approval, and never changes the task's result.
        observations=[]
        with self.lock:current=self.current
        for key,driver in list(self.drivers.items()):
            if current and current['binding']['id']==key:continue
            if driver.kind=='antigravity' and driver.ready_session:
                try:driver.busy(driver.ready_session)
                except (ProtocolError,Uncertain):
                    if self.acknowledged_sessions.get(key)==driver.ready_session:observations.append({'binding':key,'session':driver.ready_session,'status':'needs_recovery'})
                    continue
            if driver.ready_session and self.acknowledged_sessions.get(key)==driver.ready_session and any(e.get('method')=='approval_required' for e in driver.wire.events):observations.append({'binding':key,'session':driver.ready_session,'status':'approval_required'})
        return self.client.call('/api/node/heartbeat',{'capabilities':self.caps,'observations':observations})
    def execute(self,job):
        reserved={'CON','PRN','AUX','NUL',*('COM'+str(i) for i in range(1,10)),*('LPT'+str(i) for i in range(1,10))}
        if any(type(value) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}',value) or value.endswith('.') or value.split('.')[0].upper() in reserved for value in (job['job'],job['binding']['id'])):raise ProtocolError('工作单/绑定ID不是安全的本机收据标识')
        b=job['binding'];session=b.get('session');path=self.home/'receipts'/(job['job']+'.json');old=read(path) if path.exists() else None
        if old and old['status'] in ('attempting','needs_recovery'):
            self.report(job,'needs_recovery',old.get('session'),'本机存在未确认副作用；请SE核对原收据，禁止自动重放');return
        if old and old['status'] in ('accepted','failed'):
            self.report(job,old['status'],old.get('session'),old['summary']);return
        record={'job':job['job'],'binding':b['id'],'session':session,'started':time.time(),'status':'preparing'};save(path,record)
        try:
            p,config,root=self.validate(b);profile,client=self.profile(b,p);operation=job['body']['operation']
            self.usage_clients[b['id']]=client
            # A project SE may confirm an uncertain result, but cannot choose
            # some other local conversation. Only this node's pre-effect
            # binding receipt establishes session provenance.
            binding_path=self.home/'bindings'/(b['id']+'.json')
            identity={key:b[key] for key in ('id','project','actor','role','runtime','model','root')};identity.update(url=self.client.url,cwd=str(root))
            bound=read(binding_path) if binding_path.exists() else None
            if bound and bound['identity']!=identity:raise ProtocolError('本机绑定上下文不匹配，不能换项目、身份或工作根恢复')
            if session and (not bound or bound.get('session')!=session):raise ProtocolError('没有属于本机此绑定的会话收据，不能接管其他会话')
            if session:self.acknowledged_sessions[b['id']]=session
            if not bound:save(binding_path,{'identity':identity,'session':None,'created':time.time()})
            driver=self.drivers.get(b['id'])
            if driver and b['runtime']=='antigravity' and operation=='resume' and getattr(driver,'failure',None):
                driver.close();self.drivers.pop(b['id']);driver=None
            if not driver:
                active=sum(1 for d in self.drivers.values() if self.occupied(d))
                if active>=self.config['max_parallel']:raise Busy('达到本机并行上限，动作仍在原队列')
                if len(self.drivers)>=self.config['max_parallel']:
                    victim=next((key for key,d in self.drivers.items() if not self.occupied(d)),None)
                    if victim:removed=self.drivers.pop(victim);removed.close()
                local_config={**config,'_approval_context':{'project':b['project'],'role':b['role'],'binding':b['id']},'environment':{**config.get('environment',{}),'PROJECT_BOARD_PROFILE':str(profile),'PROJECT_BOARD_PROJECT':b['project']}}
                driver=Runtime(b['runtime'],local_config,root,self.home/'processes'/b['id']/uuid.uuid4().hex,b['model']);self.drivers[b['id']]=driver
            # The locally owned binding, never a remote frame, chooses project
            # and actor attribution. Existing sessions start with a baseline.
            driver.wire.usage_sink=lambda frame,b=dict(b),driver=driver:self.usage_spool.capture(frame,b,driver.ready_session or '',getattr(driver,'usage_created',False))
            if operation not in ('stop','create'):
                active=sum(1 for key,d in self.drivers.items() if key!=b['id'] and self.occupied(d))
                if active>=self.config['max_parallel']:raise Busy('达到本机模型并行上限，输入保留在原队列')
            content=self.prompt(job,profile,client) if operation!='stop' and operation!='create' else ''
            record.update(status='attempting');save(path,record)
            if operation=='create':
                session=driver.create('board-'+uuid.uuid5(uuid.NAMESPACE_URL,self.client.url+'|'+self.config['id']+'|'+b['project']+'|'+b['id']).hex,b['model']);driver.usage_created=True;save(binding_path,{'identity':identity,'session':session,'created':time.time()});record.update(session=session);save(path,record);summary='真实会话已创建；首条任务输入另有持久工作单'
            elif not session:raise ProtocolError('没有原会话，不能替换创建')
            elif operation=='stop':summary=driver.stop(session)
            else:
                driver.send(session,b['model'],content,job['job']);summary='ACP输入已写入原进程；逐轮结果待本机收据，任务尚未验收' if b['runtime']=='antigravity' else '原会话已接收输入；任务交付与验收尚待公告板真实记录'
            record.update(status='accepted',summary=summary)
        except Busy as exc:record.update(status='busy',summary=str(exc))
        except (Uncertain,TimeoutError) as exc:record.update(status='needs_recovery',summary=str(exc))
        except (ProtocolError,ClientError,OSError,ValueError,KeyError) as exc:
            # A known protocol rejection is different from a lost transport.
            record.update(status='failed',summary=type(exc).__name__+'：动作被拒绝，详见原节点私有收据',error_detail=str(exc))
        except BaseException:
            record.update(status='needs_recovery',summary='接入端意外中止，核对本机收据');save(path,record);raise
        finally:
            record.update(session=session,finished=time.time());save(path,record)
        self.report(job,record['status'],session,record['summary'])
    def run(self,once=False):
        self.probe();thread=threading.Thread(target=self.beat,daemon=True);thread.start()
        try:
            while not self.stop.is_set():
                try:
                    self.heartbeat();job=self.client.call('/api/node/poll',{})
                    self.usage_spool.flush(self.usage_clients)
                    if job['job']:
                        with self.lock:self.current=job
                        try:self.execute(job)
                        finally:
                            with self.lock:self.current=None
                    if once:break
                except ClientError as exc:
                    save(self.home/'last-error.json',{'status':exc.status,'error':str(exc),'at':time.time()})
                    if exc.status in (401,403) or once:raise
                self.stop.wait(2)
        finally:self.stop.set();thread.join(20);self.close()
    def close(self):
        errors=[]
        for key,driver in self.drivers.items():
            try:driver.close()
            except Exception as exc:errors.append({'binding':key,'error':type(exc).__name__})
        self.drivers.clear();self.guard.close()
        save(self.home/'cleanup.json',{'at':time.time(),'errors':errors,'owned_runtimes_closed':not errors})
        if errors:raise RuntimeError('部分本机运行时清理失败，核对私有cleanup.json中的具体归属')

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True);parser.add_argument('--enroll');parser.add_argument('--authorize-profile',help='Project SE self-service with this machine config; no instance credential');parser.add_argument('--probe',action='store_true');parser.add_argument('--once',action='store_true');args=parser.parse_args()
    if args.enroll and args.authorize_profile:parser.error('--enroll与--authorize-profile选择一种接入方式')
    local=args.config;authorization=None
    if args.authorize_profile:local,authority,authorization=authorize_config(local,args.authorize_profile)
    node=Node(local)
    try:
        if authorization:
            pending=node.home/'project-connect.request.json'
            payload={**authorization,'key_sha256':hashlib.sha256(node.seed['token'].encode()).hexdigest()}
            if pending.exists():
                request=read(pending)
                if {k:v for k,v in request.items() if k!='request_id'}!=payload:raise ValueError('原节点接入请求已冻结，先核对原配置')
            else:request={'request_id':uuid.uuid4().hex,**payload};save(pending,request)
            receipt=authority.call('/api/nodes/connect',request);save(node.home/'project-connect.receipt.json',receipt)
            if receipt['id']!=node.config['id']:raise ProtocolError('服务端节点ID与本机项目命名空间不匹配')
            print(json.dumps({'id':receipt['id'],'config':str(Path(local).resolve()),'status':'项目SE授权完成；实际探测后保持本机接入端运行方可消费工作单'},ensure_ascii=False),flush=True)
        if args.enroll:node.enroll(args.enroll)
        if args.probe:
            node.probe()
            if args.enroll or authorization:node.heartbeat()
        else:node.run(args.once)
    finally:node.close()
if __name__=='__main__':main()
