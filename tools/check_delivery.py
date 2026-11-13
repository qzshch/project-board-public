"""Generic receipt/scope/path gate, with no business adapter dependency."""
import argparse
import json
from pathlib import Path, PurePosixPath
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from task_board.store import BoardError

def validate(task,record,receipt,manifest,changed_files):
    spec=task['spec'];work=spec.get('work');event=record['event']
    if not work or not spec['registered']:raise BoardError('需已核定的原子任务')
    if manifest.get('project_id')!=record.get('project_id') or receipt.get('project_id')!=record.get('project_id'):raise BoardError('项目不一致')
    if manifest.get('task_id')!=spec['id'] or event['task_id']!=spec['id']:raise BoardError('任务不一致')
    if event['kind']!='submit' or record['current_submission_id']!=event['id'] or record['current_status']=='changes_requested':raise BoardError('需当前有效提交')
    if receipt['event_id']!=event['id'] or receipt['event_hash']!=event['hash']:raise BoardError('回执哈希不一致')
    if manifest.get('scope_version')!=task['scope_version'] or manifest.get('scope_hash')!=task['scope_hash'] or manifest.get('baseline')!=work['baseline']:raise BoardError('基线/范围已变化')
    if event['actor']!=task['owner'] or manifest.get('actor')!=task['owner']:raise BoardError('非当前执行者')
    if event['payload']['implementation_commit']!=manifest.get('implementation_commit'):raise BoardError('实现提交不一致')
    for key in ('contracts','assets'):
        if manifest.get(key)!=work[key]:raise BoardError('固定接口/资产版本不一致')
    if work.get('asset_locks') and manifest.get('asset_locks')!=work['asset_locks']:raise BoardError('每任务资产版本/哈希锁不一致')
    for raw in changed_files:
        p=PurePosixPath(raw)
        if p.is_absolute() or '..' in p.parts or ':' in raw or '\\' in raw or not any(raw.casefold()==x.rstrip('/').casefold() or raw.casefold().startswith(x.rstrip('/').casefold()+'/') for x in spec['allowed_paths']):raise BoardError('改动超出允许目录：'+raw)
    return {'passed':True,'project_id':manifest['project_id'],'task_id':spec['id'],'event_id':event['id'],'scope_hash':task['scope_hash'],'changed_files':len(changed_files)}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('task','record','receipt','manifest','changed'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();read=lambda f:json.loads(f.read_text('utf8'))
    try:result=validate(read(a.task),read(a.record),read(a.receipt),read(a.manifest),read(a.changed))
    except BoardError as e:print(json.dumps({'passed':False,'error':str(e)},ensure_ascii=False));return 2
    print(json.dumps(result));return 0
if __name__=='__main__':raise SystemExit(main())
