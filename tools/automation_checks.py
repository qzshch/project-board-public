"""Stable regression artifacts for the approved project-board runner suite."""
import hashlib,json,os,re,sys,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.owned_process import run
from task_board.help import runner_kit

def main():
    e=ROOT/'evidence/automation-regression';e.mkdir(parents=True,exist_ok=True)
    try:code,out,err=run([sys.executable,'-B','-X','utf8','-m','unittest','discover','-s','tests','-t','.','-v'],cwd=ROOT,evidence=e,purpose='Approved fixed-input complete regression',timeout=300,stdout_path=e/'stdout.log',stderr_path=e/'stderr.log')
    except subprocess.TimeoutExpired as failure:code=124;out=(e/'stdout.log').read_bytes();err=(e/'stderr.log').read_bytes()+b'\nRegression timed out; partial logs retained.\n'
    (e/'stdout.log').write_bytes(out);(e/'stderr.log').write_bytes(err)
    found=re.search(rb'Ran (\d+) tests?',err);count=int(found[1]) if found else 0
    (ROOT/'project-runner.zip').write_bytes(runner_kit())
    (ROOT/'rollback-runner.zip').write_bytes(runner_kit(True))
    result={'passed':code==0 and count>0,'tests':count,'exit_code':code,'logs':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in e.glob('*.log')},'runner_kit_sha256':hashlib.sha256((ROOT/'project-runner.zip').read_bytes()).hexdigest(),'source_files':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('task_board','tools','tests','task_board_web') for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}}
    result['rollback_kit_sha256']=hashlib.sha256((ROOT/'rollback-runner.zip').read_bytes()).hexdigest()
    (ROOT/'automation-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps({'passed':result['passed'],'tests':count}));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
