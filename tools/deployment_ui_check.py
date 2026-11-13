"""Formal URL with a project-only browser session; no ticket in URL or output."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import psutil
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from task_board import lifecycle
from task_board.projects import ProjectHub
from owned_process import remove_owned_tree
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[1];STATE=ROOT/'state'
async def main():
    E=ROOT/'evidence/deployed-ui'/time.strftime('%Y%m%d-%H%M%S');E.mkdir(parents=True);temporary=E/'browser-temp';temporary.mkdir();os.environ.update(TMP=str(temporary),TEMP=str(temporary),TMPDIR=str(temporary));tempfile.tempdir=str(temporary)
    report={'checks':[],'processes':[],'errors':[]};original=asyncio.create_subprocess_exec
    async def hidden(*args,**kwargs):kwargs['creationflags']=kwargs.get('creationflags',0)|subprocess.CREATE_NO_WINDOW;return await original(*args,**kwargs)
    def capture():
        known={(x['pid'],x['created']) for x in report['processes']}
        for p in psutil.Process().children(recursive=True):
            try:
                if (p.pid,p.create_time()) not in known:report['processes'].append({'pid':p.pid,'created':p.create_time(),'command':p.cmdline(),'purpose':'formal URL headless UI verification'})
            except psutil.NoSuchProcess:pass
    def check(ok,label):
        if not ok:raise AssertionError(label)
        report['checks'].append(label)
    url=lifecycle.read(STATE/'_private/server.json')['public_url'];hub=ProjectHub(STATE);actor=hub.store('task-board').authenticate(lifecycle.read(STATE/'_private/roles/board-se.json')['token']);ticket=hub.store('task-board').create_ticket(actor,allow_agent=True)
    try:
        asyncio.create_subprocess_exec=hidden
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--disable-gpu','--no-first-run'])
            try:
                capture();context=await browser.new_context(viewport={'width':1280,'height':960});response=await context.request.post(url+'/api/projects/task-board/session',data={'ticket':ticket});check(response.status==200,'formal URL project-only session redeemed without URL secret')
                page=await context.new_page();page.on('pageerror',lambda err:report['errors'].append(str(err)));await page.goto(url+'/?project=task-board',wait_until='networkidle');await page.wait_for_selector('#workspace:not([hidden])')
                check(await page.locator('#project-select option').count()==1,'deployed owner session enumerates only its own project')
                check(not await page.locator('#workspace-edit').is_hidden(),'project owner can manage its own governance')
                for width in (1280,375):
                    for theme in ('light','dark'):
                        await page.set_viewport_size({'width':width,'height':960 if width==1280 else 812});await page.emulate_media(color_scheme=theme);check(await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'formal URL {width}/{theme} no horizontal overflow');await page.screenshot(path=str(E/f'board-{width}-{theme}.png'),full_page=True)
                await page.locator('[data-panel=relations]').click();await page.screenshot(path=str(E/'relationships-mobile-dark.png'),full_page=True)
                legacy=await context.request.get(url+'/api/snapshot?project=task-board');check(legacy.status==404,'project-only browser cannot use legacy path/query to read sampleapp')
                for suffix in ('graph','governance','shared','governance/export'):
                    r=await context.request.get(url+'/api/projects/sampleapp/'+suffix);check(r.status==404,'formal URL foreign '+suffix+' refused')
                for endpoint,file in [('/client.py','tools/task_board_client.py'),('/governance-docs.md','docs/API-GOVERNANCE.md')]:
                    r=await context.request.get(url+endpoint);check(r.status==200 and await r.body()==(ROOT/file).read_bytes(),'formal URL download matches independent source: '+endpoint)
                check(not report['errors'],'formal URL has no JavaScript page errors');capture();await context.close()
            finally:await browser.close()
    finally:
        asyncio.create_subprocess_exec=original;active=[]
        for row in report['processes']:
            try:
                p=psutil.Process(row['pid'])
                if abs(p.create_time()-row['created'])<.01:active.append(p)
            except psutil.NoSuchProcess:pass
        _,alive=psutil.wait_procs(active,timeout=5)
        for p in alive:
            row=next(x for x in report['processes'] if x['pid']==p.pid)
            if abs(p.create_time()-row['created'])<.01:p.terminate()
        _,alive=psutil.wait_procs(alive,timeout=5);report['remaining']=[p.pid for p in alive]
        report['passed']=not report['errors'] and not alive and len(report['checks'])>=15
        if not alive:remove_owned_tree(temporary,E)
        lifecycle.write(E/'RESULT.json',report)
    print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'evidence':str(E)}))
if __name__=='__main__':asyncio.run(main())
