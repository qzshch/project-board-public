"""Real NAS URL, scoped browser sessions, actual legacy graph and tab checks."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import psutil
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from task_board import lifecycle
from task_board_client import Client
from owned_process import remove_owned_tree
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[1];E=ROOT/'evidence/nas-ui-20261113';PUBLIC='http://example-server.example-tailnet.ts.net:18785';STATE=Path('//example-owner/Project Workspace/project-board/state')
async def main():
    temp=E/'browser-temp';temp.mkdir();os.environ.update(TMP=str(temp),TEMP=str(temp),TMPDIR=str(temp));tempfile.tempdir=str(temp);report={'checks':[],'errors':[],'processes':[]};original=asyncio.create_subprocess_exec
    async def hidden(*args,**kwargs):kwargs['creationflags']=kwargs.get('creationflags',0)|subprocess.CREATE_NO_WINDOW;return await original(*args,**kwargs)
    def check(ok,label):
        if not ok:raise AssertionError(label)
        report['checks'].append(label)
    def capture():
        known={(p['pid'],p['created']) for p in report['processes']}
        for p in psutil.Process().children(recursive=True):
            try:
                if (p.pid,p.create_time()) not in known:report['processes'].append({'pid':p.pid,'created':p.create_time(),'command':p.cmdline(),'purpose':'NAS production browser verification'})
            except psutil.NoSuchProcess:pass
    admin=Client(PUBLIC,lifecycle.read(STATE/'_private/admin.json'),'100.64.0.10');owner=Client(PUBLIC,lifecycle.read(STATE/'_private/roles/board-se.json'),'100.64.0.10')
    check({p['id'] for p in admin.call('/api/projects')['projects']}=={'sampleapp','task-board'},'only two real projects remain')
    check(admin.call('/api/projects/task-board/shared')['releases']==[],'rehearsal shared releases removed from live visibility')
    check(admin.call('/api/projects/task-board/governance')['assets']=={},'rehearsal private assets removed')
    try:
        asyncio.create_subprocess_exec=hidden
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--disable-gpu','--no-first-run'])
            try:
                capture();context=await browser.new_context(viewport={'width':1280,'height':960});page=await context.new_page();page.on('pageerror',lambda error:report['errors'].append(str(error)))
                ticket=owner.call('/api/access',{})['ticket'];r=await context.request.post(PUBLIC+'/api/projects/task-board/session',data={'ticket':ticket});check(r.status==200,'scoped NAS owner session works')
                await page.goto(PUBLIC+'/?project=task-board',wait_until='networkidle');await page.wait_for_selector('#workspace:not([hidden])')
                check(await page.locator('#task-board').is_hidden(),'project overview excludes delivery queue')
                await page.locator('[data-panel=tasks]').click();check(await page.locator('#task-board').is_visible(),'task tab contains delivery queue')
                for panel in ('overview','relations','contracts','assets','handoff'):
                    await page.locator('[data-panel='+panel+']').click();check(await page.locator('#task-board').is_hidden(),panel+' tab excludes delivery queue')
                await page.locator('[data-panel=relations]').click();check(await page.locator('g[data-task]').count()==18,'board graph includes all real and historical task nodes')
                check(await page.locator('[data-edge-type=hard]').count()==21,'board graph draws the 21 actual prerequisite edges')
                tests_x=float(await page.locator('g[data-task="upgrade/M0.tests"] rect').get_attribute('x'));remote_x=float(await page.locator('g[data-task="upgrade/M0.remote"] rect').get_attribute('x'));code_x=float(await page.locator('g[data-task="upgrade/M0.code"] rect').get_attribute('x'))
                check(tests_x==remote_x,'real parallel sibling tasks occupy the same dependency layer')
                check(code_x<tests_x,'real predecessor is laid out before its consumers')
                for width in (1280,375):
                    for theme in ('light','dark'):
                        await page.set_viewport_size({'width':width,'height':960 if width==1280 else 812});await page.emulate_media(color_scheme=theme);check(await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'NAS {width}/{theme} graph stays inside viewport');await page.screenshot(path=str(E/f'board-graph-{width}-{theme}.png'),full_page=True)
                r=await context.request.get(PUBLIC+'/api/projects/sampleapp/graph');check(r.status==404,'NAS project session cannot read foreign graph')
                # A second project-bound session validates the user's current
                # sampleapp view, including old package nodes previously omitted.
                dc=await browser.new_context(viewport={'width':1280,'height':960});ticket=admin.call('/api/projects/sampleapp/access',{})['ticket'];await dc.request.post(PUBLIC+'/api/projects/sampleapp/session',data={'ticket':ticket});dp=await dc.new_page();dp.on('pageerror',lambda error:report['errors'].append(str(error)))
                await dp.goto(PUBLIC+'/?project=sampleapp&panel=relations',wait_until='networkidle');await dp.wait_for_selector('svg.dependency-graph')
                check(await dp.locator('g[data-task]').count()==330,'sampleapp graph draws all 330 historical task nodes')
                check(await dp.locator('[data-edge-type=hard]').count()==8,'sampleapp graph draws its 8 recorded hard dependencies')
                check(await dp.locator('[data-edge-type=containment]').count()==190,'sampleapp graph separately draws 190 package hierarchy links')
                check(await dp.locator('#task-board').is_hidden(),'sampleapp relationship view excludes delivery queue')
                await dp.screenshot(path=str(E/'sampleapp-graph-desktop.png'),full_page=True)
                await dp.locator('[name=graph-mode]').select_option('hard');check(await dp.locator('[data-edge-type=containment]').count()==0,'hard-only filter does not relabel hierarchy as prerequisites')
                await dp.locator('[name=graph-mode]').select_option('all');families=dp.locator('[name=graph-family] option');check(await families.count()>1,'historical task family filter available')
                family=await families.nth(1).get_attribute('value');await dp.locator('[name=graph-family]').select_option(family);check(0<await dp.locator('g[data-task]').count()<330,'family filter produces a focused relationship diagram')
                await dp.set_viewport_size({'width':375,'height':812});await dp.emulate_media(color_scheme='dark');check(await dp.evaluate('document.documentElement.scrollWidth<=innerWidth'),'historical graph mobile view does not overflow');await dp.screenshot(path=str(E/'sampleapp-family-mobile-dark.png'),full_page=True)
                check(not report['errors'],'no production JavaScript errors');capture();await dc.close();await context.close()
            finally:await browser.close()
    finally:
        asyncio.create_subprocess_exec=original;alive=[]
        for row in report['processes']:
            try:
                p=psutil.Process(row['pid'])
                if abs(p.create_time()-row['created'])<.01:alive.append(p)
            except psutil.NoSuchProcess:pass
        _,alive=psutil.wait_procs(alive,timeout=5)
        for p in alive:
            row=next(v for v in report['processes'] if v['pid']==p.pid)
            if abs(p.create_time()-row['created'])<.01:p.terminate()
        _,alive=psutil.wait_procs(alive,timeout=5);report['remaining']=[p.pid for p in alive];report['passed']=not alive and not report['errors'] and len(report['checks'])>=28
        if not alive:remove_owned_tree(temp,E)
        lifecycle.write(E/'UI-RESULT.json',report)
    print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'evidence':str(E)}))
if __name__=='__main__':asyncio.run(main())
