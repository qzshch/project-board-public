"""Finite hidden child execution with exact process identity and finally cleanup."""
import json
import os
from pathlib import Path
import subprocess
import time
import psutil

def run(command, *, evidence, purpose, cwd=None, timeout=60, input_data=None, env=None):
    evidence=Path(evidence);evidence.mkdir(parents=True,exist_ok=True)
    startup=None
    if os.name=='nt':
        startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=subprocess.SW_HIDE
    child=subprocess.Popen([str(x) for x in command],cwd=cwd,stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,startupinfo=startup,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    record={'pid':child.pid,'command':[str(x) for x in command],'purpose':purpose,'started':time.time()}
    try:
        try:record['created']=psutil.Process(child.pid).create_time()
        except psutil.NoSuchProcess:record['already_exited']=True
        out,err=child.communicate(input_data,timeout=timeout)
        record['exit_code']=child.returncode
        return child.returncode,out,err
    finally:
        if child.poll() is None:
            # Only this exact owned child and its descendants are in scope.
            try:
                owner=psutil.Process(child.pid)
                descendants=owner.children(recursive=True) if abs(owner.create_time()-record['created'])<0.01 else []
                for proc in reversed(descendants):
                    try:proc.terminate()
                    except psutil.NoSuchProcess:pass
                child.kill();child.wait(5);psutil.wait_procs(descendants,timeout=5)
            except psutil.NoSuchProcess:pass
        record.update(finished=time.time(),waited=child.poll() is not None,exit_code=child.returncode)
        with (evidence/'processes.jsonl').open('a',encoding='utf8') as h:h.write(json.dumps(record,ensure_ascii=False)+'\n')
