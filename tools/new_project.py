"""Local operator creates a project and a scoped owner; never prints keys."""
import argparse
import json
from pathlib import Path
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from task_board.lifecycle import DEFAULT_STATE, read, write
from task_board.projects import ProjectHub
from task_board.governance import Governance

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state',type=Path,default=DEFAULT_STATE);p.add_argument('--definition',type=Path,required=True);p.add_argument('--owner',required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if a.out.exists():p.error('身份文件已存在，拒绝覆盖')
    hub=ProjectHub(a.state);admin=read(a.state/'_private/admin.json');identity=hub.resolve(admin['token'])
    project=hub.create(identity,read(a.definition));profile=hub.invite(project['id'],a.owner)
    Governance(hub.store(project['id'])).apply(identity['actor'],{'request_id':str(uuid.uuid4()),'expected_revision':0,'action':'member','payload':{'actor':a.owner,'role':'owner','scope':'本项目总负责人；材料、原子任务、接口、资产、审核与交接'}})
    write(a.out,{**profile,'url':admin['url']})
    print(json.dumps({'project_id':project['id'],'owner':a.owner,'private_profile':str(a.out),'secret_printed':False}));return 0
if __name__=='__main__':raise SystemExit(main())
