"""Explicit, immutable shared releases; project-private metadata never indexed.

Release payloads contain only the reviewed public manifest and an explicitly
shared location. Consumer identities are filtered by the caller's project.
"""
import json
import time
from .store import BoardError, canonical, digest, fields, text, evidence
from .governance import load, role, MANAGERS

class Registry:
    def __init__(self, hub, project):
        self.hub,self.project=hub,project
        with hub.connection() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS releases(ref TEXT PRIMARY KEY,producer TEXT NOT NULL,payload TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS release_status(ref TEXT PRIMARY KEY,status TEXT NOT NULL,reason TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS consumption(project TEXT NOT NULL,alias TEXT NOT NULL,ref TEXT NOT NULL,
                PRIMARY KEY(project,alias));
              CREATE TABLE IF NOT EXISTS removed_releases(ref TEXT PRIMARY KEY,removed_at REAL NOT NULL,reason TEXT NOT NULL);
              CREATE TRIGGER IF NOT EXISTS releases_no_update BEFORE UPDATE ON releases
                BEGIN SELECT RAISE(ABORT,'immutable release'); END;
              CREATE TRIGGER IF NOT EXISTS releases_no_delete BEFORE DELETE ON releases
                BEGIN SELECT RAISE(ABORT,'immutable release'); END;
            ''')

    def get(self, ref, project, allow_withdrawn=False):
        with self.hub.connection() as db:
            row=db.execute('SELECT r.*,s.status FROM releases r JOIN release_status s USING(ref) WHERE ref=? AND NOT EXISTS(SELECT 1 FROM removed_releases d WHERE d.ref=r.ref)',(ref,)).fetchone()
        if not row:raise BoardError('共享版本不可用或未授权',404)
        value=json.loads(row['payload'])
        if project!=row['producer'] and project not in value['audience'] and '*' not in value['audience']:raise BoardError('共享版本不可用或未授权',404)
        if row['status']=='withdrawn' and not allow_withdrawn:raise BoardError('共享版本已撤回',409)
        return {**value,'ref':ref,'producer':row['producer'],'status':row['status']}

    def listing(self):
        with self.hub.connection() as db:refs=[r[0] for r in db.execute('SELECT ref FROM releases WHERE ref NOT IN(SELECT ref FROM removed_releases) ORDER BY ref')]
        result=[]
        for ref in refs:
            try:result.append(self.get(ref,self.project,True))
            except BoardError:pass
        return result

    def apply(self, actor, request):
        fields(request,{'action','payload','request_id'}, {'action','payload','request_id'})
        action=request['action'];p=request['payload'];text(request['request_id'],'请求ID',100)
        if type(p) is not dict:raise BoardError('payload需对象')
        store=self.hub.store(self.project)
        # Both project task writers and publication acquire the project lock
        # first, then catalog lock. There is no reverse lock acquisition.
        with store.connection() as local:
            local.execute('BEGIN IMMEDIATE')
            if role(local,actor) not in MANAGERS:raise BoardError('需本项目owner/SE审核',403)
            with self.hub.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                previous=db.execute("SELECT payload FROM audit ORDER BY seq DESC").fetchall()
                for row in previous:
                    event=json.loads(row[0]);d=event['detail']
                    if isinstance(d,dict) and d.get('request_id')==request['request_id'] and event['project']==self.project and event['actor']==actor['id'] and event['action']=='asset':
                        if d['request_hash']!=digest(request):raise BoardError('请求ID内容不一致',409)
                        return {**d['result'],'replayed':True}
                if action=='publish':
                    fields(p,{'asset','audience','shared_location','review','evidence'}, {'asset','audience','shared_location','review','evidence'})
                    asset=load(local)['assets'].get(p['asset'])
                    from .learning import publication_guard
                    publication_guard(local,p['asset'])
                    if not asset or not asset['shareable'] or asset['sensitivity']!='public' or asset['kind'] not in ('skill','methodology','infrastructure','test_case','test_data','test_tool') or asset['license'].lower() in ('unknown','private','none'):
                        raise BoardError('仅审核过的通用公开技能/方法/基建可发布；敏感或业务私有资产拒绝',403)
                    if type(p['audience']) is not list or not p['audience'] or any(type(x) is not str for x in p['audience']):raise BoardError('需显式共享受众')
                    for audience in p['audience']:
                        if audience!='*':self.hub.metadata(audience)
                    text(p['review'],'发布审核依据');text(p['shared_location'],'共享位置',2000);evidence(p['evidence'])
                    ref=self.project+'/'+p['asset']
                    if db.execute('SELECT 1 FROM releases WHERE ref=?',(ref,)).fetchone():raise BoardError('共享版本不可变；请发布新版本',409)
                    # Deliberately omit original private location, source paths,
                    # task IDs, evidence paths and all consumer identities.
                    manifest={k:asset[k] for k in ('id','version','kind','license','sha256')}
                    manifest.update(audience=p['audience'],location=p['shared_location'],review=p['review'],released_by=actor['id'])
                    db.execute('INSERT INTO releases VALUES(?,?,?)',(ref,self.project,canonical(manifest)))
                    db.execute('INSERT INTO release_status VALUES(?,?,?)',(ref,'published',p['review']))
                    result={'published':ref,'manifest_sha256':digest(manifest)}
                elif action in ('deprecate','withdraw'):
                    fields(p,{'ref','reason','migration','evidence'}, {'ref','reason','migration','evidence'})
                    row=db.execute('SELECT producer FROM releases WHERE ref=?',(p['ref'],)).fetchone()
                    if not row or row[0]!=self.project:raise BoardError('仅提供项目可弃用/撤回',403)
                    text(p['reason'],'原因');text(p['migration'],'影响与迁移计划',8000);evidence(p['evidence'])
                    current=db.execute('SELECT status FROM release_status WHERE ref=?',(p['ref'],)).fetchone()[0]
                    if current=='withdrawn':raise BoardError('撤回不可恢复；发布新版本',409)
                    db.execute('UPDATE release_status SET status=?,reason=? WHERE ref=?',('withdrawn' if action=='withdraw' else 'deprecated',p['reason'],p['ref']))
                    result={'ref':p['ref'],'status':'withdrawn' if action=='withdraw' else 'deprecated'}
                elif action in ('consume','upgrade'):
                    fields(p,{'ref','alias','reason','tests'}, {'ref','alias','reason','tests'})
                    release=self.get(p['ref'],self.project);text(p['alias'],'本项目引用ID',160);text(p['reason'],'消费/升级依据');text(p['tests'],'消费测试',8000)
                    old=db.execute('SELECT ref FROM consumption WHERE project=? AND alias=?',(self.project,p['alias'])).fetchone()
                    if (action=='consume' and old) or (action=='upgrade' and not old):raise BoardError('创建/升级引用状态不匹配',409)
                    db.execute('INSERT INTO consumption VALUES(?,?,?) ON CONFLICT(project,alias) DO UPDATE SET ref=excluded.ref',(self.project,p['alias'],p['ref']))
                    result={'alias':p['alias'],'ref':p['ref'],'sha256':release['sha256'],'previous':old[0] if old else None}
                else:raise BoardError('未知资产动作',404)
                self.hub.audit(db,'asset',self.project,actor['id'],{'request_id':request['request_id'],'request_hash':digest(request),'request':request,'result':result})
                db.commit()
            local.commit()
        return result

    def consumption(self):
        with self.hub.connection() as db:rows=list(db.execute('SELECT alias,ref FROM consumption WHERE project=?',(self.project,)))
        return {r['alias']:{'release':r['ref'],'shared':True,**self.get(r['ref'],self.project,True)} for r in rows}

    def impact(self, identity, ref):
        self.get(ref,self.project,True)
        with self.hub.connection() as db:rows=list(db.execute('SELECT project,alias FROM consumption WHERE ref=?',(ref,)))
        # Even producer SE does not gain access to consumer project identities.
        return [dict(r) for r in rows if identity['global_admin'] or r['project']==self.project]
