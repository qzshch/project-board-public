"""Real headless Edge rendering; isolated state, no live credentials or input."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.task_board.test_governance import GovernanceCase
from playwright.async_api import async_playwright

E=ROOT/'evidence/ui'/time.strftime('%Y%m%d-%H%M%S');E.mkdir(parents=True)
TEMP=E/'browser-temp';TEMP.mkdir();os.environ.update(TMP=str(TEMP),TEMP=str(TEMP),TMPDIR=str(TEMP),PROJECT_BOARD_TEST_ROOT=str(E/'fixtures'));tempfile.tempdir=str(TEMP)
report={'checks':[],'errors':[],'processes':[],'screens':[],'headless':True}
original=asyncio.create_subprocess_exec
async def hidden(*args,**kwargs):
    kwargs['creationflags']=kwargs.get('creationflags',0)|subprocess.CREATE_NO_WINDOW
    return await original(*args,**kwargs)
def capture():
    keys={(r['pid'],r['created']) for r in report['processes']}
    for p in psutil.Process().children(recursive=True):
        try:
            if (p.pid,p.create_time()) not in keys:report['processes'].append({'pid':p.pid,'created':p.create_time(),'command':p.cmdline(),'purpose':'headless UI render'})
        except psutil.NoSuchProcess:pass
def check(value,label):
    if not value:raise AssertionError(label)
    report['checks'].append(label)
async def main():
    c=GovernanceCase();c.setUp();asyncio.create_subprocess_exec=hidden
    try:
        c.member();c.atomic();second=c.atomic('new/two',['src/two/'],category='documentation',role='documenter');second['depends_on']=['new/one'];c.event('new/two','scope',{'spec':second,'reason':'record a real predecessor'},c.admin)
        c.gov('knowledge',{'background':'一个独立的研究与实现项目','goals':'多人协作时范围清楚、验收可追溯','non_goals':'不执行其他项目的业务流程','constraints':'所有代码、证据与缓存放在G盘；公共接口先冻结。','materials':[],'entries':[]})
        c.gov('milestone',{'id':'M1','goal':'研究与原型验收','acceptance':'产物哈希和真实行为检查','status':'active','evidence':[]})
        ticket=c.hub.admin_store.create_ticket(c.hub.admin_store.authenticate(c.admin['token']))
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--disable-gpu','--no-first-run'])
            try:
                capture();context=await browser.new_context(viewport={'width':1280,'height':960});page=await context.new_page();page.on('pageerror',lambda error:report['errors'].append(str(error)))
                await page.goto(c.url+'/?project=alpha#kind=admin&access='+ticket,wait_until='networkidle');await page.wait_for_selector('#workspace:not([hidden])')
                check('一个独立的研究' in await page.locator('#workspace-body').inner_text(),'overview displays project background')
                check(await page.locator('#task-board').is_hidden(),'overview has no task queue')
                await page.locator('[data-panel=tasks]').click();check(await page.locator('#task-board').is_visible(),'task tab owns the delivery queue');await page.locator('[data-panel=overview]').click()
                await page.locator('#workspace-edit').click();await page.locator('[name=background]').fill('界面实际保存的项目背景');await page.locator('#detail button[type=submit]').click();await page.wait_for_function("() => document.querySelector('#workspace-body').textContent.includes('界面实际保存')")
                check(c.hub.store('alpha').path.exists(),'UI saved through real HTTP')
                await page.locator('#create').click()
                check(await page.locator('[name=category] option').count()==12,'task form exposes all atomic categories')
                check(await page.locator('[name=work_role]').count()==1,'task form separates execution role from completion state')
                await page.locator('#close-detail').click()
                for width in (1280,375):
                    for theme in ('light','dark'):
                        await page.set_viewport_size({'width':width,'height':960 if width==1280 else 812});await page.emulate_media(color_scheme=theme)
                        check(await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'{width}/{theme} has no horizontal overflow')
                        name=f'overview-{width}-{theme}.png';await page.screenshot(path=str(E/name),full_page=True);report['screens'].append(name)
                await page.locator('[data-panel=relations]').click();check(await page.locator('svg.dependency-graph').count()==1,'real dependency graph rendered');check(await page.locator('[data-edge-type=hard]').count()==1,'recorded prerequisite is drawn as an arrow');check(await page.locator('g[data-task]').count()==3,'historical tasks are included');check(await page.locator('#task-board').is_hidden(),'relationship tab has no delivery queue');await page.screenshot(path=str(E/'relations-mobile-dark.png'),full_page=True)
                for panel in ('contracts','assets','handoff'):
                    await page.locator('[data-panel='+panel+']').click();check(await page.locator('#task-board').is_hidden(),panel+' tab excludes delivery queue');await page.locator('#workspace-edit').click();check(await page.locator('[name=operation]').count()==1,panel+' management form works');await page.locator('#close-detail').click()
                # A project switch must clear knowledge and graph as well as task rows.
                await page.locator('#project-select').select_option('beta');await page.wait_for_function("() => document.querySelector('#project-select').value==='beta' && !document.querySelector('#workspace-body').textContent.includes('界面实际保存')")
                check('界面实际保存' not in await page.locator('body').inner_text(),'project switching clears previous knowledge')
                agent=c.hub.resolve(c.a['token']);ticket2=c.hub.store('alpha').create_ticket(agent['actor'],allow_agent=True)
                ac=await browser.new_context(viewport={'width':375,'height':812});ap=await ac.new_page();await ap.goto(c.url+'/?project=alpha#access='+ticket2,wait_until='networkidle');await ap.wait_for_selector('#workspace:not([hidden])')
                check(await ap.locator('#workspace-edit').is_hidden(),'Agent has no management controls')
                check(await ap.locator('#project-select option').count()==1,'Agent only sees own project')
                result=await ap.evaluate("async()=>{const r=await fetch('/api/projects/beta/governance');return {status:r.status,body:await r.text()}}")
                check(result['status']==404,'browser foreign knowledge request is refused')
                await ap.screenshot(path=str(E/'agent-mobile.png'),full_page=True)
                c.hub.revoke(c.identity,'alpha',c.a['actor'],'UI acceptance complete')
                await ap.wait_for_function("() => document.querySelector('#identity').textContent==='未授权'",timeout=10000)
                check(await ap.locator('#workspace').is_hidden() and '界面实际保存' not in await ap.locator('body').inner_text(),'revocation clears knowledge and graph cache')
                check(not report['errors'],'no JavaScript page errors');capture();await ac.close();await context.close()
            finally:await browser.close()
    finally:
        asyncio.create_subprocess_exec=original;c.tearDown()
        alive=[]
        for row in report['processes']:
            try:
                p=psutil.Process(row['pid'])
                if abs(p.create_time()-row['created'])<.01:alive.append(p)
            except psutil.NoSuchProcess:pass
        _,remaining=psutil.wait_procs(alive,timeout=5)
        # All records came from this helper's own descendants. Exact identity is
        # checked before cleanup, never a broad process-name kill.
        for p in remaining:
            row=next(r for r in report['processes'] if r['pid']==p.pid)
            if abs(p.create_time()-row['created'])<.01:p.terminate()
        _,remaining=psutil.wait_procs(remaining,timeout=5)
        report['remaining']=[p.pid for p in remaining];report['passed']=not report['errors'] and not remaining and len(report['checks'])>=18
        if not remaining:
            assert TEMP.resolve().is_relative_to(E.resolve()) and not TEMP.is_symlink();shutil.rmtree(TEMP)
        (E/'RESULT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({'evidence':str(E),'checks':len(report['checks']),'passed':report['passed'],'remaining':report['remaining']},ensure_ascii=False))
if __name__=='__main__':asyncio.run(main())
