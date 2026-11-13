"""Offline, manifest-bounded removal of this session's rehearsal workspaces.

User-authorized cleanup removes live projects, grants, enrollment files, private
workspace DBs, current assets/consumption and published visibility. Append-only
audit chains retain only historical records; immutable IDs cannot be reused.
"""
import argparse
import json
from pathlib import Path
import sys
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from task_board import lifecycle
from task_board.projects import ProjectHub
from task_board.governance import Governance
from task_board.store import BoardError
if __package__:
    from .owned_process import remove_owned_tree
else:
    from owned_process import remove_owned_tree

def cleanup(state, manifest):
    state=Path(state).resolve()
    if (state/'service.json').exists() and lifecycle.exact_owner(lifecycle.read(state/'service.json')):raise BoardError('先停止此实例，禁止清理活动工作区',409)
    hub=ProjectHub(state);identity=hub.resolve(lifecycle.read(state/'_private/admin.json')['token']);rows=manifest['projects'];ids={p['id'] for p in rows}
    if not ids or any(not p.startswith('onboarding-20261113-') for p in ids):raise BoardError('清理清单越出本次演练范围')
    with hub.connection() as db:
        for value in rows:
            row=db.execute('SELECT id,name,description FROM projects WHERE id=?',(value['id'],)).fetchone()
            if not row or dict(row)!=value:raise BoardError('演练身份/来源已变化，拒绝清理',409)
        all_ids=[r[0] for r in db.execute('SELECT id FROM projects')]
    real=[p for p in all_ids if p not in ids];before={p:hub.store(p).head() for p in real}
    assets=Governance(hub.store('task-board')).snapshot()['assets']
    asset_refs=[ref for ref in assets if any(ref.startswith('brief-method-'+p.removeprefix('onboarding-')+'@') for p in ids)]
    release_refs={'task-board/'+ref for ref in asset_refs}
    for project in real:
        for t in hub.store(project).snapshot()['tasks']:
            w=t['spec'].get('work',{})
            if any(v['release'] in release_refs for v in w.get('asset_locks',{}).values()):raise BoardError('真实任务仍固定演练资产，需先迁移',409)
        for v in hub.store(project).registry.consumption().values():
            if v['release'] in release_refs:raise BoardError('真实项目仍消费演练资产，需先迁移',409)
    # Validate every path before changing catalog visibility or deleting files.
    directories=[];files=[]
    for project in ids:
        path=state/'projects'/project
        if not path.resolve().is_relative_to(state/'projects') or path.is_symlink() or any(p.is_symlink() for p in path.rglob('*')):raise BoardError('演练目录存在链接或越界')
        directories.append(path);files.append(state/'_private/enrollment'/(project+'.json'));files.append(state/'_private/roles'/('demo-owner-'+project.removeprefix('onboarding-')+'.json'))
    with hub.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        for project in sorted(ids):
            db.execute('DELETE FROM credentials WHERE project=?',(project,));db.execute('DELETE FROM consumption WHERE project=?',(project,));db.execute('DELETE FROM projects WHERE id=?',(project,));db.execute('INSERT INTO removed_projects VALUES(?,?)',(project,time.time()))
            hub.audit(db,'remove-rehearsal',project,identity['actor']['id'],{'reason':manifest['reason'],'live_data_removed':True})
        for ref in sorted(release_refs):
            db.execute('INSERT INTO removed_releases VALUES(?,?,?)',(ref,time.time(),manifest['reason']))
        db.commit()
    if asset_refs:
        g=Governance(hub.store('task-board'));g.apply(identity['actor'],{'request_id':uuid.uuid4().hex,'expected_revision':g.snapshot()['revision'],'action':'asset_remove','payload':{'refs':asset_refs,'reason':manifest['reason']}})
    for path in directories:remove_owned_tree(path,state/'projects')
    for path in files:
        if path.exists():
            if path.is_symlink() or not path.resolve().is_relative_to(state/'_private'):raise BoardError('私有清理路径越界')
            path.unlink()
    after={p:hub.store(p).head() for p in real}
    if before!=after:raise BoardError('真实项目任务/事件head被改变',409)
    return {'passed':True,'removed_projects':sorted(ids),'removed_private_asset_versions':len(asset_refs),'hidden_shared_versions':len(release_refs),'preserved_heads':after,'catalog':hub.verify(),'remaining_projects':[p['id'] for p in hub.list_projects(identity)]}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();result=cleanup(a.state,json.loads(a.manifest.read_text('utf8')));lifecycle.write(a.out,result);print(json.dumps({'passed':True,'remaining_projects':result['remaining_projects'],'removed_projects':len(result['removed_projects'])}))
