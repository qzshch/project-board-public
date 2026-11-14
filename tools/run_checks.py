"""Run independent suite, preserve output including failures and source hashes."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import subprocess
from owned_process import run,remove_owned_tree

ROOT=Path(__file__).resolve().parents[1]
def main():
    target=ROOT/'evidence/checks'/time.strftime('%Y%m%d-%H%M%S');target.mkdir(parents=True)
    fixture=target/'fixtures';fixture.mkdir()
    try:
        # Actual Windows full run exceeded 180s after adding contained Git
        # reversal, standalone-kit and deployment-fallback fixtures. Individual
        # command bounds stay unchanged; allow 300s for the whole finite suite.
        code,out,err=run([sys.executable,'-B','-X','utf8','-m','unittest','discover','-s','tests','-t','.','-v'],cwd=ROOT,evidence=target,purpose='independent full behavioral regression',timeout=300,env={**os.environ,'PROJECT_BOARD_TEST_ROOT':str(fixture)},stdout_path=target/'stdout.log',stderr_path=target/'stderr.log')
    except subprocess.TimeoutExpired as error:
        code=124;out=(target/'stdout.log').read_bytes();err=(target/'stderr.log').read_bytes()+b'\nFull suite exceeded 300 seconds; owned processes were stopped.\n'
        # Only logs from these generated fixtures are retained, never profiles.
        import shutil
        for p in fixture.rglob('*.log'):
            if p.is_file() and not p.is_symlink():
                dest=target/'failure-fixture-logs'/p.relative_to(fixture);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
        try:remove_owned_tree(fixture,target);fixture.mkdir()
        except ValueError as cleanup:(target/'CLEANUP-BLOCKED.txt').write_text(str(cleanup),encoding='utf8')
    (target/'stdout.log').write_bytes(out);(target/'stderr.log').write_bytes(err)
    sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('task_board','tools','tests','task_board_web') for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    report={'passed':code==0,'exit_code':code,'sources':sources,'logs':['stdout.log','stderr.log'],'fixture_children_remaining':[str(p) for p in fixture.iterdir()],'historical_original_tests_counted':False}
    (target/'RESULT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'passed':report['passed'],'evidence':str(target),'summary':err.decode('utf8')[-160:]}));return code
if __name__=='__main__':raise SystemExit(main())
