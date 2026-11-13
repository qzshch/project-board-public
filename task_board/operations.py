"""Project-local operational records. No remote command execution in HTTP.

All actions serialize with task/governance writes in the project database. Old
projects keep their existing gates until the owner explicitly adopts a policy.
"""
from copy import deepcopy
import json
import time
from .store import BoardError, fields, text, integer, canonical, digest


def setup(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS operations_events(
      seq INTEGER PRIMARY KEY,actor TEXT NOT NULL,request_id TEXT NOT NULL,
      request_hash TEXT NOT NULL,payload TEXT NOT NULL,prev_hash TEXT NOT NULL,
      hash TEXT NOT NULL,UNIQUE(actor,request_id));
      CREATE TRIGGER IF NOT EXISTS operations_no_update BEFORE UPDATE ON operations_events
      BEGIN SELECT RAISE(ABORT,'append only'); END;
      CREATE TRIGGER IF NOT EXISTS operations_no_delete BEFORE DELETE ON operations_events
      BEGIN SELECT RAISE(ABORT,'append only'); END;''')


def load(db):
    row=db.execute('SELECT * FROM operations_events ORDER BY seq DESC LIMIT 1').fetchone()
    if row:return {'revision':row['seq'],'head':row['hash'],**json.loads(row['payload'])['state']}
    return {'revision':0,'head':'0'*64,'policy':{'enabled':False,'profile':'standard','reason':'历史行为，尚未采用分级策略'},
            **{k:{} for k in ('assessments','estimates','sessions','time_complete','benchmarks','cases','case_heads','case_status','suites','test_plans','runners','runs','candidates','candidate_heads')},'usage':[]}


def manager(role):
    if role not in ('owner','se','reviewer'):raise BoardError('需要本项目负责人/SE',403)


def task_at(db,p,key='task'):
    row=db.execute('SELECT state FROM tasks WHERE id=?',(text(p[key],'任务ID',160),)).fetchone()
    if not row:raise BoardError('本项目任务不存在',404)
    task=json.loads(row[0])
    if p.get('scope')!=task['scope_hash']:raise BoardError('任务范围已变化；重读后决定',409)
    return task


class Operations:
    def __init__(self,store):self.store=store

    def apply(self,actor,request):
        from .governance import role,load as governance_load,tasks
        fields(request,{'request_id','expected_revision','action','payload'},{'request_id','expected_revision','action','payload'})
        rid=text(request['request_id'],'请求ID',100);integer(request['expected_revision'],'操作版本')
        action=text(request['action'],'动作',80);p=request['payload']
        if not isinstance(p,dict):raise BoardError('payload需对象')
        for key in ('profile','level','mode','phase','size','uncertainty','outcome','sensitivity','kind','priority','ref','run','suite','actor','task','scope','input_anchor','session','lease'):
            if key in p and type(p[key]) is not str:raise BoardError(key+'需字符串')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            r=role(db,actor)
            if r in ('viewer','tracker'):raise BoardError('仅有读取权限',403)
            old=db.execute('SELECT * FROM operations_events WHERE actor=? AND request_id=?',(actor['id'],rid)).fetchone()
            if old:
                if old['request_hash']!=digest(request):raise BoardError('请求ID绑定其他内容',409)
                return {'revision':old['seq'],'hash':old['hash'],'replayed':True,**json.loads(old['payload'])['result']}
            v=load(db);seq=v.pop('revision');previous=v.pop('head')
            if seq!=request['expected_revision']:raise BoardError('操作记录已变化；重读后决定',409)
            if r=='runner' and action not in ('run_claim','run_heartbeat','run_finish'):raise BoardError('执行器只能领取、续租及回传测试',403)
            now=time.time();g=governance_load(db);all_tasks=tasks(db)
            if action in ('policy','assess','assess_package'):
                from .assurance import mutate
            elif action=='benchmark_import':
                from .timing import import_benchmark
                def mutate(*_):return import_benchmark(v,p,self.store.registry,actor,r,now)
            elif action in ('estimate','time_change','time_correct','time_close','time_complete'):
                from .timing import mutate
            elif action in ('case','case_retire','suite','test_plan','runner','run_request','run_claim','run_heartbeat','run_finish','run_cancel','manual_run'):
                from .quality import mutate
            elif action in ('candidate','candidate_refine','candidate_validate','candidate_promote','candidate_retire','asset_feedback'):
                from .learning import mutate
            else:raise BoardError('未知操作动作',404)
            result=mutate(v,db,actor,r,action,p,now,g,all_tasks) or {}
            event={'action':action,'payload':deepcopy(p),'state':v,'result':result,'at':now}
            hashed=digest({'seq':seq+1,'actor':actor['id'],'request_id':rid,'event':event,'previous':previous})
            db.execute('INSERT INTO operations_events VALUES(?,?,?,?,?,?,?)',(seq+1,actor['id'],rid,digest(request),canonical(event),previous,hashed));db.commit()
            return {'revision':seq+1,'hash':hashed,**result}

    def snapshot(self):
        from .governance import tasks,load as governance_load
        from .assurance import effective
        from .timing import report
        from .quality import suggestions
        with self.store.connection() as db:
            db.execute('BEGIN');v=load(db);ts=tasks(db);g=governance_load(db)
            v['effective']={k:effective(v,t,g) for k,t in ts.items()}
            for b in v['benchmarks'].values():
                try:
                    release=self.store.registry.get(b['release'],self.store.registry.project)
                    b['available']=release['sha256']==b['sha256']
                except BoardError:b['available']=False
            from .assurance import LEVELS
            v['package_assurance']={pid:{'level':max((v['effective'][t]['level'] for t in package['tasks']),key=LEVELS.get,default='light'),'tasks':package['tasks'],'all_assessed':all(v['effective'][t]['assessed'] for t in package['tasks'])} for pid,package in g['packages'].items()}
            v['time_report']=report(v,ts,time.time(),db)
            v['suggested_cases']={k:suggestions(v,t) for k,t in ts.items()}
            for ref,suite in v['suites'].items():suite['manifest_hash']=digest(suite)
            return v

    def verify(self):
        previous='0'*64
        with self.store.connection() as db:rows=list(db.execute('SELECT * FROM operations_events ORDER BY seq'))
        for seq,row in enumerate(rows,1):
            expected=digest({'seq':seq,'actor':row['actor'],'request_id':row['request_id'],'event':json.loads(row['payload']),'previous':previous})
            if row['seq']!=seq or row['prev_hash']!=previous or row['hash']!=expected:raise BoardError('操作审计链损坏',409)
            previous=expected
        return {'passed':True,'events':len(rows),'head':previous}
