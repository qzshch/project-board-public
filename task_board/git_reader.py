"""Bounded Git plumbing over an operator-owned bare mirror; never a worktree."""
from datetime import datetime,timezone
import json,os,re,shutil,subprocess,threading
from pathlib import Path,PurePosixPath
from .store import BoardError
from .storage_boundary import reason

SHA=re.compile(r'[0-9a-f]{40}')
READ_SLOTS=threading.BoundedSemaphore(4)


def sha(value):
    if type(value) is not str or not SHA.fullmatch(value):raise BoardError('需要完整40位提交SHA')
    return value


def safe_path(value):
    if type(value) is not str or not value or len(value)>1000 or any(ord(c)<32 for c in value) or '\\' in value or ':' in value:
        raise BoardError('文件路径无效')
    p=PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or str(p)!=value:raise BoardError('文件路径不得越界')
    return value


class Reader:
    def __init__(self,path,policy=None):self.path=Path(path);self.policy=policy or {}

    def git(self,args,limit=8*1024*1024,input_data=None):
        if not READ_SLOTS.acquire(blocking=False):raise BoardError('Git查询繁忙，请稍后重试',503)
        try:return self._git(args,limit,input_data)
        finally:READ_SLOTS.release()

    def _git(self,args,limit=8*1024*1024,input_data=None):
        """Drain to a private file: output is capped without retaining huge blobs."""
        import tempfile,time,psutil
        from tools.runner_process import CommandGroup
        if not self.path.is_dir():raise BoardError('仓库尚未同步；请先配置NAS只读接入',409)
        executable=shutil.which('git')
        if not executable:
            candidate=Path(os.sys.executable).parent/('git.exe' if os.name=='nt' else 'git')
            if candidate.exists():executable=str(candidate)
        if not executable:raise BoardError('实例尚未安装Git',503)
        env={**os.environ,'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':os.devnull,'GIT_TERMINAL_PROMPT':'0','GIT_OPTIONAL_LOCKS':'0','GIT_NO_REPLACE_OBJECTS':'1','GIT_LITERAL_PATHSPECS':'1','GIT_PAGER':'cat','LC_ALL':'C.UTF-8'}
        command=[executable,'--no-pager','--git-dir='+str(self.path),'-c','core.hooksPath='+os.devnull,'-c','core.fsmonitor=false',*args]
        audit=self.path.parent/'audit';audit.mkdir(parents=True,exist_ok=True)
        group=CommandGroup();child=None;record={'command':command,'purpose':'Bounded read-only Git query','started':time.time()}
        try:
            with tempfile.TemporaryFile(dir=audit) as out,tempfile.TemporaryFile(dir=audit) as err:
                startup=None
                if os.name=='nt':startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=subprocess.SW_HIDE
                child=group.launch(command,cwd=self.path,env=env,stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,stdout=out,stderr=err,shell=False,startupinfo=startup,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                record.update(pid=child.pid,created=psutil.Process(child.pid).create_time())
                if input_data is not None:child.stdin.write(input_data);child.stdin.close()
                end=time.monotonic()+12
                while child.poll() is None:
                    if time.monotonic()>end or os.fstat(out.fileno()).st_size>limit or os.fstat(err.fileno()).st_size>65536:
                        raise BoardError('查询超出12秒或大小限制；请缩小范围',413)
                    time.sleep(.01)
                record['exit_code']=child.returncode
                if child.returncode:raise BoardError('Git对象或文件不存在，或查询不可用',404)
                if os.fstat(out.fileno()).st_size>limit:raise BoardError('结果过大；请缩小范围',413)
                out.seek(0);return out.read()
        finally:
            group.close()
            if child is not None:child.wait(5)
            record.update(finished=time.time(),exit_code=child.returncode if child else None)
            with (audit/'reads.jsonl').open('a',encoding='utf8') as h:h.write(json.dumps(record)+'\n')

    def commit(self,value):
        return self.commits([sha(value)])[0]

    def commits(self,values):
        """One length-framed batch instead of a process per timeline row."""
        if not values:return []
        raw=self.git(['cat-file','--batch'],limit=4*1024*1024,input_data=('\n'.join(sha(v) for v in values)+'\n').encode());offset=0;rows=[]
        for value in values:
            end=raw.find(b'\n',offset);header=raw[offset:end].decode().split()
            if len(header)!=3 or header[0]!=value or header[1]!='commit':raise BoardError('提交对象不存在',404)
            size=int(header[2]);offset=end+1
            if size>256*1024:raise BoardError('提交说明超出大小限制',413)
            data=raw[offset:offset+size];offset+=size+1;rows.append(self.metadata(value,data))
        return rows

    @staticmethod
    def metadata(value,raw):
        header,_,body=raw.partition(b'\n\n');meta={'sha':value,'parents':[],'message':body.decode('utf8','replace')[:16000]}
        for line in header.decode('utf8','replace').splitlines():
            if line.startswith('parent '):meta['parents'].append(line[7:])
            if line.startswith(('author ','committer ')):
                kind,s=line.split(' ',1);m=re.match(r'(.*) <.*> (\d+) ([+-]\d{4})$',s)
                meta[kind]=m[1] if m else '未知'
                try:meta[kind+'_date']=datetime.fromtimestamp(int(m[2]),timezone.utc).isoformat() if m else None
                except (ValueError,OverflowError,OSError):meta[kind+'_date']=None
        meta['subject']=meta['message'].split('\n',1)[0];return meta

    def resolve(self,value,refs):
        if value in refs:return refs[value]
        return self.commit(value)['sha']

    def log(self,head,offset=0,path='',query='',author=''):
        args=['log','--format=%H','--topo-order','--skip='+str(offset),'--max-count=51','--no-show-signature','--no-notes']
        if query:args+=['--fixed-strings','--regexp-ignore-case','--grep='+query]
        if author:args+=['--fixed-strings','--author='+author]
        if path:args+=['--follow']
        args+=[sha(head),'--']+([safe_path(path)] if path else [])
        ids=self.git(args).decode().splitlines();return {'commits':self.commits(ids[:50]),'next':offset+50 if len(ids)>50 else None,'anchor':head}

    def files(self,base,head):
        args=['diff','--no-ext-diff','--no-textconv','--no-renames','--numstat','-z',sha(base),sha(head),'--'] if base else ['diff-tree','--root','--no-commit-id','-r','--no-renames','--numstat','-z',sha(head),'--']
        raw=self.git(args).decode('utf8','replace');rows=[]
        for item in raw.split('\0'):
            if not item:continue
            a,d,path=item.split('\t',2)
            rows.append({'path':path,'additions':None if a=='-' else int(a),'deletions':None if d=='-' else int(d),'local_only':reason(path,self.policy.get('patterns',[]),self.policy.get('exceptions',{}))})
        return rows

    def tree(self,head,prefix=''):
        if prefix:safe_path(prefix)
        raw=self.git(['ls-tree','-r','-z','--full-tree',sha(head),'--']+([prefix] if prefix else []),limit=4*1024*1024);rows=[]
        for item in raw.split(b'\0'):
            if not item:continue
            meta,path=item.split(b'\t',1);mode,kind,oid=meta.decode().split();path=path.decode('utf8','replace')
            rows.append({'path':path,'mode':mode,'type':kind,'sha':oid,'local_only':reason(path,self.policy.get('patterns',[]),self.policy.get('exceptions',{}))})
        return rows

    def allowed(self,path):
        safe_path(path)
        if reason(path,self.policy.get('patterns',[]),self.policy.get('exceptions',{})):raise BoardError('该路径按策略留在本地/NAS；仅展示已误入Git的路径告警，不读取正文',403)

    def patch(self,base,head,path):
        self.allowed(path)
        args=['diff','--no-ext-diff','--no-textconv','--no-renames','--unified=3',sha(base),sha(head),'--',path] if base else ['show','--format=','--root','--no-ext-diff','--no-textconv','--no-renames','--unified=3',sha(head),'--',path]
        return self.git(args,limit=512*1024).decode('utf8','replace')

    def blame(self,head,path,start):
        self.allowed(path)
        found=[r for r in self.tree(head,path) if r['path']==path]
        if not found or found[0]['mode'] not in ('100644','100755'):raise BoardError('仅支持普通文本文件',400)
        size=int(self.git(['cat-file','-s',found[0]['sha']]))
        if size>512*1024:raise BoardError('文件超过512KiB，请在专用代码工具查看',413)
        content=self.git(['cat-file','blob',found[0]['sha']],limit=512*1024)
        if b'\0' in content:raise BoardError('二进制文件没有逐行溯源',400)
        count=len(content.splitlines())
        if start>count:return {'lines':[],'total_lines':count,'next':None}
        end=min(start+199,count);raw=self.git(['blame','--no-textconv','--line-porcelain','-L',str(start)+','+str(end),sha(head),'--',path]);lines=[];current={}
        for line in raw.decode('utf8','replace').splitlines():
            if re.match(r'^[0-9a-f]{40} \d+ \d+',line):
                p=line.split();current={'sha':p[0],'original_line':int(p[1]),'line':int(p[2])}
            elif line.startswith('author '):current['author']=line[7:]
            elif line.startswith('summary '):current['summary']=line[8:]
            elif line.startswith('filename '):current['original_path']=line[9:]
            elif line.startswith('\t'):lines.append({**current,'text':line[1:]})
        return {'lines':lines,'total_lines':count,'next':end+1 if end<count else None}
