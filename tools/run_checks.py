"""Run independent suite, preserve output including failures and source hashes."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from owned_process import run

ROOT=Path(__file__).resolve().parents[1]
def main():
    target=ROOT/'evidence/checks'/time.strftime('%Y%m%d-%H%M%S');target.mkdir(parents=True)
    fixture=target/'fixtures';fixture.mkdir()
    code,out,err=run([sys.executable,'-B','-X','utf8','-m','unittest','discover','-s','tests','-t','.','-v'],cwd=ROOT,evidence=target,purpose='independent full behavioral regression',timeout=120,env={**os.environ,'PROJECT_BOARD_TEST_ROOT':str(fixture)})
    (target/'stdout.log').write_bytes(out);(target/'stderr.log').write_bytes(err)
    sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('task_board','tools','tests','task_board_web') for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    report={'passed':code==0,'exit_code':code,'sources':sources,'logs':['stdout.log','stderr.log'],'fixture_children_remaining':[str(p) for p in fixture.iterdir()],'historical_original_tests_counted':False}
    (target/'RESULT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'passed':report['passed'],'evidence':str(target),'summary':err.decode('utf8')[-160:]}));return code
if __name__=='__main__':raise SystemExit(main())
