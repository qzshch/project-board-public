"""Bounded standalone cutover with stopped-state backups and real rollback.

Run only for an explicitly authorized deployment. No game code is modified.
Source remains a recovery point; never copy a live SQLite single file.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time
from urllib.request import Request, build_opener, ProxyHandler
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from task_board import lifecycle
from task_board.store import BoardError
from owned_process import run

ROOT=Path(__file__).resolve().parents[1]
def clone_stopped(source,target):
    source,target=Path(source).resolve(),Path(target).resolve()
    if source==target or target.is_relative_to(source) or source.is_relative_to(target):raise BoardError('备份路径不得互相包含')
    record=source/'service.json'
    if record.exists() and (lifecycle.exact_owner(lifecycle.read(record)) or not lifecycle.read(record).get('closed')):raise BoardError('必须确认源实例关闭，不能复制正在写入的状态',409)
    target.mkdir(parents=True,exist_ok=True);copied=[]
    for path in source.rglob('*'):
        if path.is_symlink():raise BoardError('状态备份拒绝跟随链接',409)
        if not path.is_file():continue
        rel=path.relative_to(source)
        if path.name.endswith(('-wal','-shm')) or path.name in ('operator.html','stop.flag','service.json','start.json'):continue
        dest=target/rel;dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.is_symlink() or not dest.resolve().is_relative_to(target):raise BoardError('备份目标越界',409)
        if path.suffix=='.sqlite':
            with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(dest) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise BoardError('备份完整性失败',409)
        else:shutil.copy2(path,dest)
        copied.append({'path':str(rel),'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'bytes':dest.stat().st_size})
    return copied

def api(state,path):
    settings=lifecycle.read(state/'_private/server.json');profile=lifecycle.read(state/'_private/admin.json')
    request=Request('http://127.0.0.1:'+str(settings['port'])+path,headers={'Authorization':'Bearer '+profile['token']})
    with build_opener(ProxyHandler({})).open(request,timeout=20) as response:return json.load(response)
def anchors(state):
    projects=api(state,'/api/projects')['projects'];result={}
    for project in projects:
        prefix='/api/projects/'+project['id'];snap=api(state,prefix+'/snapshot')
        result[project['id']]={'tasks':len(snap['tasks']),'head':snap['head'],'verified':api(state,prefix+'/verify')['passed']}
        if snap['tasks']:
            event=snap['tasks'][0]['last_event'];receipt=api(state,prefix+'/receipt?id='+event)
            result[project['id']]['receipt']={'id':event,'hash':receipt['event']['hash']}
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--target',type=Path,required=True);p.add_argument('--old-cli',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);a=p.parse_args()
    source,target,e=a.source.resolve(),a.target.resolve(),a.evidence.resolve();e.mkdir(parents=True,exist_ok=True)
    if target.exists():raise BoardError('首次切换目标须不存在，防止覆盖既有状态',409)
    before=lifecycle.read(source/'service.json')
    if not lifecycle.exact_owner(before) or str(a.old_cli.resolve()).casefold() not in [str(Path(x).resolve()).casefold() for x in before['command'] if x.endswith('.py')]:raise BoardError('原进程创建时间/完整命令不匹配',409)
    report={'source':str(source),'target':str(target),'old_owner':before,'before':anchors(source),'steps':[],'complete':False}
    backup=e/'_private/recovery';final=False;started_new=False
    def old(action):
        code,out,err=run([sys.executable,'-B','-X','utf8',a.old_cli,'--state',source,action],evidence=e,purpose='exact legacy board '+action,cwd=a.old_cli.parent.parent,timeout=50)
        if code:raise BoardError('旧公告板生命周期失败：'+err.decode('utf8',errors='replace')[:500])
        return json.loads(out)
    def settings(readonly):
        value=lifecycle.read(target/'_private/server.json');value.update(project_state=str(target),access_log=str(target/'access.jsonl'),maintenance_read_only=readonly);lifecycle.write(target/'_private/server.json',value)
        conn=lifecycle.read(target/'connection.json');conn.update(code_root=str(ROOT),client_script=str(ROOT/'tools/task_board_client.py'),state=str(target),product='project-board',governance_version=1);lifecycle.write(target/'connection.json',conn)
    try:
        old('stop');report['steps'].append('old stopped by exact identity')
        report['backup']=clone_stopped(source,backup)
        clone_stopped(backup,target);settings(True)
        lifecycle.start(target);started_new=True
        report['candidate']=anchors(target)
        if report['candidate']!=report['before']:raise BoardError('候选任务/事件/head/回执改变',409)
        lifecycle.stop(target);started_new=False
        old('start');report['rollback']=anchors(source)
        if report['rollback']!=report['before']:raise BoardError('回滚期间有新写入；保留原实例，重新核定迁移锚点',409)
        report['steps'].append('real rollback to original code/state passed')
        old('stop')
        # Re-read the entire stopped source after rollback. This retains any
        # sessions/audit updates, rather than copying only a SQLite main file.
        report['final_source_backup']=clone_stopped(source,e/'_private/final-source')
        clone_stopped(source,target);settings(False)
        lifecycle.start(target);started_new=True
        report['after']=anchors(target)
        if report['after']!=report['before']:raise BoardError('最终迁移锚点不一致',409)
        lifecycle.stop(target);started_new=False;lifecycle.start(target);started_new=True
        report['restart']=anchors(target)
        if report['restart']!=report['after']:raise BoardError('完整重启读回不一致',409)
        report['new_owner']=lifecycle.read(target/'service.json');report['complete']=True;final=True
        report['steps'].append('standalone final start and full restart passed')
    finally:
        if not final:
            if started_new:
                lifecycle.stop(target)
            if not lifecycle.exact_owner(lifecycle.read(source/'service.json')):old('start')
            report['recovered_source']=True
        report['finished']=time.time();lifecycle.write(e/'MIGRATION.json',report)
    print(json.dumps({'complete':report['complete'],'evidence':str(e),'heads':report['after'],'persistent_service':report['new_owner']['pid']},ensure_ascii=False))
if __name__=='__main__':main()
