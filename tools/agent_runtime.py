"""Owned stdio transports for three deliberately different protocols.

Commands and provider environment come only from the local node configuration.
Remote jobs cannot supply arbitrary RPC or approval rules. Only exact commands
preapproved by the local operator may pass; other approvals remain blocked.
"""
import hashlib,json,os,queue,subprocess,threading,time,uuid
from pathlib import Path
from tools.runner_process import CommandGroup
from tools.task_board_client import save

class ProtocolError(Exception):pass
class Busy(ProtocolError):pass
class Uncertain(ProtocolError):pass

class Wire:
    def __init__(self,argv,cwd,env,evidence,runtime,approved_commands=None,approval_context=None):
        self.runtime=runtime;self.group=CommandGroup();self.lock=threading.RLock();self.waiters={};self.events=[];self.dead=False;self.sequence=0;self.closed=False
        evidence=Path(evidence);evidence.mkdir(parents=True,exist_ok=True,mode=0o700);self.audit_path=evidence/'process.json';self.approval_audit=evidence/'approvals.jsonl';self.err=(evidence/'stderr.log').open('ab');(evidence/'stderr.log').chmod(0o600)
        self.cwd=Path(cwd).resolve();self.approved_commands=approved_commands or [];self.approval_context=approval_context or {};self.sessions=set()
        try:
            self.process=self.group.launch(argv,cwd=cwd,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.err,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            save(evidence/'process.json',{'pid':self.process.pid,'created':self.group.created,'command':argv,'purpose':'locally authorized '+runtime+' board session adapter','started':time.time()})
            self.reader=threading.Thread(target=self.read,daemon=True);self.reader.start()
        except BaseException:self.close();raise
    def frame(self,value):
        with self.lock:
            if self.dead or self.process.poll() is not None:raise Uncertain('运行时已经退出，先核对本机收据')
            try:self.process.stdin.write((json.dumps(value,ensure_ascii=False)+'\n').encode('utf8'));self.process.stdin.flush()
            except OSError:raise Uncertain('传输已中断，先核对原会话及本机收据') from None
    def read(self):
        try:
            for line in self.process.stdout:
                if len(line)>8*1024*1024:continue
                try:frame=json.loads(line)
                except (ValueError,UnicodeError):continue
                if 'id' in frame and ('result' in frame or 'error' in frame):
                    with self.lock:q=self.waiters.get(frame['id'])
                    if q:q.put(frame)
                elif 'id' in frame and 'method' in frame:
                    # Native application permission/user-input requests remain
                    # denied/blocked. Receiving a board job is not permission
                    # to approve a shell command or disclose provider headers.
                    if self.runtime=='zcode' and frame['method']=='session/requestRuntimePreferences':
                        self.frame({'id':frame['id'],'result':{'additionalDirectories':[],'nativeSearchEnhancementsEnabled':False,'toolSearchMode':'off','subagentRuntimeConfigEnabled':False,'appControlEnabled':False,'memoryEnabled':False,'askUserQuestionAutoResolutionEnabled':False}})
                    else:
                        approval=self.approval(frame)
                        if approval is not None:
                            self.frame({'id':frame['id'],'result':approval,**({} if self.runtime=='zcode' else {'jsonrpc':'2.0'})});continue
                        self.events.append({'method':'approval_required' if any(word in frame['method'].lower() for word in ('permission','approval')) else 'unsupported_client_request','request_method':frame['method'],'at':time.time()})
                        response={'id':frame['id'],'error':{'code':-32000,'message':'Local operator approval required'}}
                        if self.runtime!='zcode':response['jsonrpc']='2.0'
                        self.frame(response)
                else:
                    self.events.append(frame)
                    if len(self.events)>2000:del self.events[:1000]
        finally:
            self.dead=True
            with self.lock:
                for q in self.waiters.values():q.put({'_transport_closed':True})
    def approval(self,frame):
        """Local operator's exact command + cwd + file digest, never remote policy."""
        p=frame.get('params',{});method=frame.get('method');command=None
        if self.runtime=='zcode' and method=='interaction/requestPermission' and p.get('toolName')=='Bash':
            value=p.get('input',{})
            if type(value) is dict and not set(value)-{'command','description','timeout','run_in_background'}:command=value.get('command')
            session=p.get('sessionId')
        elif self.runtime=='codex' and method=='item/commandExecution/requestApproval' and not any(p.get(k) for k in ('additionalPermissions','networkApprovalContext','proposedNetworkPolicyAmendment')):
            command=p.get('command');session=p.get('threadId')
        else:return None
        if type(command) is not str or type(session) is not str or session not in self.sessions:return None
        try:
            if p.get('cwd') and Path(p['cwd']).resolve()!=self.cwd:return None
            for rule in self.approved_commands:
                if not self.approval_context or any(rule.get(key)!=self.approval_context.get(key) for key in ('project','role')) or rule.get('binding') and rule['binding']!=self.approval_context.get('binding'):continue
                if rule.get('command')!=command or Path(rule['cwd']).resolve()!=self.cwd:continue
                script=Path(rule['script']).resolve()
                if not script.is_file() or hashlib.sha256(script.read_bytes()).hexdigest()!=rule['sha256']:continue
                audit={'method':'local_approval_granted','request_method':method,'session':session,'script_sha256':rule['sha256'],'command_sha256':hashlib.sha256(command.encode('utf8')).hexdigest(),'at':time.time()};self.events.append(audit)
                if getattr(self,'approval_audit',None):
                    with self.approval_audit.open('a',encoding='utf8') as handle:handle.write(json.dumps(audit)+'\n')
                    self.approval_audit.chmod(0o600)
                return {'decision':'allow','reason':'Local operator approved this exact command, cwd and script digest'} if self.runtime=='zcode' else {'decision':'accept'}
        except (OSError,KeyError,TypeError,ValueError):return None
        return None
    def call(self,method,params,timeout=45):
        with self.lock:
            self.sequence+=1;rid=self.sequence;q=queue.Queue();self.waiters[rid]=q
        value={'id':rid,'method':method,'params':params}
        if self.runtime!='zcode':value['jsonrpc']='2.0'
        try:
            self.frame(value)
            try:response=q.get(timeout=timeout)
            except queue.Empty:raise Uncertain('运行时响应超时；不能盲重放 '+method) from None
            if response.get('_transport_closed'):raise Uncertain('运行时退出，结果未知')
            if 'error' in response:raise ProtocolError(str(response['error'].get('message','协议拒绝'))[:1000])
            return response.get('result',{})
        finally:
            with self.lock:self.waiters.pop(rid,None)
    def notify(self,method,params):
        frame={'method':method,'params':params}
        if self.runtime!='zcode':frame['jsonrpc']='2.0'
        self.frame(frame)
    def close(self):
        if self.closed:return
        self.closed=True
        try:
            self.group.close()
            if hasattr(self,'reader'):self.reader.join(5)
        finally:
            if hasattr(self,'process'):
                for pipe in (self.process.stdin,self.process.stdout):
                    if pipe:pipe.close()
            self.err.close()
            if self.audit_path.is_file():
                record=json.loads(self.audit_path.read_text('utf8'));record.update(finished=time.time(),exit_code=self.process.poll(),process_stopped=self.process.poll() is not None);save(self.audit_path,record)

class Runtime:
    def __init__(self,kind,config,cwd,evidence,model=None):
        self.kind=kind;self.config=config;self.cwd=str(Path(cwd).resolve());self.model=model;self.active=None;self.ready_session=None;self.fresh=False
        self.workspace={'workspacePath':self.cwd,'workspaceKey':self.cwd}
        self.wire=Wire(config['command'],self.cwd,{**os.environ,**config.get('environment',{})},evidence,kind,config.get('approved_commands'),config.get('_approval_context'))
        try:
            if kind=='codex':
                self.wire.call('initialize',{'clientInfo':{'name':'project-board-node','version':'1.0'},'capabilities':{'experimentalApi':False}});self.wire.notify('initialized',{})
            elif kind=='zcode':self.wire.call('runtime/capabilities',{})
            elif kind=='deepseek':
                # Official SDK profile: connection model is fixed, sessions are
                # client-identified. Models are not treated as ACP options.
                if not model:raise ProtocolError('DeepSeek SDK连接需要本机固定provider/model')
                provider,modelid=model.split('/',1)
                self.wire.call('initialize',{'cwd':self.cwd,'provider':provider,'model':modelid,'approvalRequests':True,'capabilities':{'userQuestions':True},**({'reasoningEffort':config['reasoning_effort']} if config.get('reasoning_effort') else {})})
            else:raise ProtocolError('未知适配器')
        except BaseException:self.close();raise
    def models(self):
        if self.kind=='codex':
            out=[];cursor=None
            for _ in range(10):
                result=self.wire.call('model/list',{'limit':100,**({'cursor':cursor} if cursor else {})});out.extend(x['model'] for x in result['data']);cursor=result.get('nextCursor')
                if not cursor:break
            return out
        if self.kind=='zcode':
            result=[]
            for model in self.config.get('models',[]):
                self.wire.call('provider/testModelConnectivity',{'workspace':self.workspace,'selection':self.selection(model)},timeout=60);result.append(model)
            return result
        return [self.model]
    def selection(self,model):
        provider,mid=model.split('/',1);value={'providerId':provider,'modelId':mid};options=self.config.get('model_options',{}).get(model)
        if options:value['options']=options
        return value
    def create(self,stable_id,model):
        if self.kind=='codex':
            out=self.wire.call('thread/start',{'cwd':self.cwd,'model':model,'approvalPolicy':'on-request','sandbox':'workspace-write','ephemeral':False});session=out['thread']['id']
        elif self.kind=='zcode':
            out=self.wire.call('session/create',{'sessionId':stable_id,'workspace':self.workspace,'mode':'edit','model':self.selection(model),'titleGenerationEnabled':False});session=out['session']['sessionId']
        else:
            self.wire.call('session/working-directory/set',{'sessionId':stable_id,'path':self.cwd});session=stable_id
        self.wire.sessions.add(session);self.ready_session=session;self.fresh=True;return session
    def resume(self,session,model):
        if self.ready_session==session:return
        if self.kind=='codex':self.wire.call('thread/resume',{'threadId':session,'cwd':self.cwd,'model':model,'approvalPolicy':'on-request','sandbox':'workspace-write'})
        elif self.kind=='zcode':self.wire.call('session/resume',{'sessionId':session,'workspace':self.workspace})
        else:self.wire.call('session/resume',{'sessionId':session})
        self.wire.sessions.add(session);self.ready_session=session;self.fresh=False
    def busy(self,session):
        if self.wire.dead:raise Uncertain('原运行时已退出，需先核对原会话')
        if self.kind=='codex':
            if self.active:
                terminal=next((e for e in reversed(self.wire.events) if e.get('method')=='turn/completed' and e.get('params',{}).get('turn',{}).get('id')==self.active),None)
                if terminal:self.active=None;return False
                # A freshly accepted turn may precede rollout creation. It is
                # active until a matching terminal notification, not an error
                # just because thread/read briefly sees an empty rollout.
                return True
            if self.fresh:return False
            thread=self.wire.call('thread/read',{'threadId':session,'includeTurns':False})['thread'];status=thread.get('status',{})
            return status.get('type')=='active' if isinstance(status,dict) else status=='active'
        if self.kind=='zcode':
            value=self.wire.call('session/read',{'sessionId':session})
            # An unrecognized status is conservative; the protocol test fixes
            # the supported shape, version changes must be re-probed.
            state=value.get('session',{});status=state.get('status')
            if status is None:raise ProtocolError('该Zcode版本未提供可识别忙碌状态，需接入检测')
            return status not in ('idle','ready','completed','stopped')
        if not self.active:return False
        for e in reversed(self.wire.events):
            if e.get('method')=='session.status' and e.get('params',{}).get('sessionId')==session:return e['params'].get('status') not in ('idle','completed','stopped')
        return True
    def send(self,session,model,content,job):
        self.resume(session,model)
        if self.busy(session):raise Busy('原会话仍忙碌，通知留队，不打断或重建')
        self.wire.events[:]=[e for e in self.wire.events if e.get('method')!='approval_required']
        if self.kind=='codex':
            out=self.wire.call('turn/start',{'threadId':session,'input':[{'type':'text','text':content}],'model':model,'clientUserMessageId':job});self.active=out['turn']['id'];self.fresh=False
        elif self.kind=='zcode':
            try:self.wire.call('session/send',{'sessionId':session,'content':content,'inputId':job,'modelSelection':self.selection(model)})
            except ProtocolError as exc:
                if 'A prompt is already running for this session' in str(exc):raise Busy('原会话刚进入运行，保留输入等空闲') from None
                raise
            self.active=job
        else:self.wire.call('session/prompt',{'sessionId':session,'contentBlocks':[{'type':'text','text':content}]});self.active=job
    def stop(self,session):
        if self.kind=='codex':
            data=self.wire.call('thread/read',{'threadId':session,'includeTurns':True})['thread'];turn=next((x for x in reversed(data.get('turns',[])) if x.get('status')=='inProgress'),None)
            if turn:self.wire.call('turn/interrupt',{'threadId':session,'turnId':turn['id']})
        elif self.kind=='zcode':self.wire.call('session/stop',{'sessionId':session})
        else:raise ProtocolError('该DeepSeek SDK版本没有单会话停止方法；请在本机核对，不能假称已停止或关闭其他会话')
        return '已提交原会话停止请求，停止完成以运行时状态读回为准'
    def close(self):self.wire.close()
