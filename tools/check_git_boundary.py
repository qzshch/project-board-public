"""Check staged/index paths; never modify, add, remove, commit or push files."""
import argparse,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from task_board.storage_boundary import reason
from tools.owned_process import run


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,default=Path.cwd());p.add_argument('--policy',type=Path);p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    if os.name=='nt' and args.out.resolve().drive.casefold()=='c:':raise ValueError('证据目录须非C盘')
    policy=json.loads(args.policy.read_text('utf8')) if args.policy else {}
    code,out,err=run(['git','ls-files','-z'],cwd=args.repo,evidence=args.out.parent,purpose='Read-only check for local data mistakenly tracked by Git',timeout=20);assert code==0,'不是可读取的Git仓库'
    violations=[{'path':s,'reason':why} for s in out.decode('utf8').split('\0') if s and (why:=reason(s,policy.get('patterns',[]),policy.get('exceptions',{})))]
    result={'passed':not violations,'violations':violations,'meaning':'检查Git索引，包含已暂存的新文件；不自动修改索引或删除文件。排除规则不能移除既有Git历史。'};args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps({'passed':result['passed'],'violations':len(violations),'report':str(args.out)}));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
