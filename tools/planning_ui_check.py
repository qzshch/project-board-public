"""Actual desktop/mobile rendering and governance forms, isolated from NAS data."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.task_board.test_planning import PlanningCase
from playwright.async_api import async_playwright
from tools.owned_process import remove_owned_tree

E=ROOT/'evidence/planning-ui'/time.strftime('%Y%m%d-%H%M%S');E.mkdir(parents=True)
TEMP=E/'browser-temp';TEMP.mkdir();os.environ.update(TMP=str(TEMP),TEMP=str(TEMP),TMPDIR=str(TEMP),PROJECT_BOARD_TEST_ROOT=str(E/'fixtures'));tempfile.tempdir=str(TEMP)
report={'checks':[],'errors':[],'processes':[],'screens':[],'passed':False}
original=asyncio.create_subprocess_exec
async def hidden(*args,**kwargs):
    kwargs['creationflags']=kwargs.get('creationflags',0)|subprocess.CREATE_NO_WINDOW
    return await original(*args,**kwargs)
def capture():
    keys={(r['pid'],r['created']) for r in report['processes']}
    for p in psutil.Process().children(recursive=True):
        try:
            if (p.pid,p.create_time()) not in keys:report['processes'].append({'pid':p.pid,'created':p.create_time(),'command':p.cmdline(),'purpose':'isolated planning UI rendering'})
        except psutil.NoSuchProcess:pass
def check(value,label):
    if not value:raise AssertionError(label)
    report['checks'].append(label)

async def main():
    c=PlanningCase();c.setUp();asyncio.create_subprocess_exec=hidden
    try:
        c.charter();c.member();c.gov('planning_enable',{'reason':'Fixture rollout'})
        ticket=c.hub.admin_store.create_ticket(c.hub.admin_store.authenticate(c.admin['token']))
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--disable-gpu','--no-first-run'])
            try:
                capture();context=await browser.new_context(viewport={'width':1280,'height':960});page=await context.new_page();page.on('pageerror',lambda error:report['errors'].append(str(error)))
                await page.goto(c.url+'/?project=alpha&panel=planning#kind=admin&access='+ticket,wait_until='networkidle');await page.wait_for_selector('#workspace:not([hidden])')
                check('尚无项目框架' in await page.locator('#workspace-body').inner_text(),'planning empty state explains next action')
                check(await page.locator('#task-board').is_hidden(),'planning excludes delivery queue')
                async def save(action,p):
                    await page.locator('#workspace-edit').click();await page.locator('[name=operation]').select_option(action)
                    for k,v in p.items():
                        field=page.locator('#detail [name='+k+']')
                        if k in ('stage','result'):await field.select_option(v)
                        else:await field.fill('\n'.join(v) if isinstance(v,list) else v)
                    await page.locator('#detail button[type=submit]').click();await page.wait_for_selector('#detail',state='hidden')
                p=c.module();p['evidence']=[]
                await save('module_plan',p)
                check(c.snap()['module_heads']['core']=='core@1','module form creates immutable version through HTTP')
                await page.get_by_role('button',name='评审当前范围',exact=True).click()
                await page.locator('[name=summary]').fill('Reviewed bounded behavior and no shared interface')
                await page.locator('[name=evidence]').fill('G:/fixture/review.json | '+'b'*64)
                await page.locator('#detail button[type=submit]').click();await page.wait_for_selector('#detail',state='hidden')
                check(c.snap()['module_readiness']['core@1']['ready'],'review form approves current fingerprint')
                c.atomic(planning=c.binding());await page.reload(wait_until='networkidle')
                mp={'id':'M1','version':'1','goal':'A usable capability','path':'Implement and verify','entry':'Approved plan','modules':['core@1'],'tasks':['new/one'],'acceptance':'Examples work','method':'Actual integration test','threshold':'All specified checks pass','environment':'Isolated state','reviewer':'root','due':'Before release','risks':'Repair failures'}
                await save('milestone_plan',mp)
                check('阶段交付未验收' in await page.locator('[data-milestone="M1@1"]').inner_text(),'milestone exposes task blocker')
                c.complete('new/one');await page.reload(wait_until='networkidle')
                check(not c.snap()['milestone_readiness']['M1@1']['passed'],'task completion does not auto-pass stage')
                await page.get_by_role('button',name='记录阶段检验结果').click();await page.locator('[name=summary]').fill('Entry conditions and integration verified');await page.locator('[name=evidence]').fill('G:/fixture/stage.json | '+'c'*64);await page.locator('#detail button[type=submit]').click();await page.wait_for_selector('#detail',state='hidden')
                check(c.snap()['milestone_readiness']['M1@1']['passed'],'stage form records separate validation evidence')
                check(await page.locator('g[data-task="module:core@1"]').count()==1,'module node actually drawn')
                check(await page.locator('[data-edge-type=containment]').count()==1,'module to atom expansion actually drawn')
                for width in (1280,375):
                    for theme in ('light','dark'):
                        await page.set_viewport_size({'width':width,'height':960 if width==1280 else 812});await page.emulate_media(color_scheme=theme)
                        check(await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'{width}/{theme} planning fits viewport')
                        name=f'planning-{width}-{theme}.png';await page.screenshot(path=str(E/name),full_page=True);report['screens'].append(name)
                await page.locator('#new-project').click()
                for k,v in {'projectid':'fresh-ui','projectname':'New UI project','projectdescription':'No production data','init_background':'Purpose','init_goals':'Outcome','init_non_goals':'Other work','init_constraints':'NAS','init_history_notes':'New project','init_resource_notes':'Private resources'}.items():await page.locator('[name='+k+']').fill(v)
                await page.locator('#detail button[type=submit]').click();await page.wait_for_selector('#detail',state='hidden');await page.wait_for_function("document.querySelector('#project-select').value==='fresh-ui'")
                fresh=c.call('/api/projects/fresh-ui/governance',profile=c.admin)[1]
                check(fresh['planning_policy']['mode']=='enforced' and fresh['knowledge']['background']=='Purpose','new project UI saves charter and enforces planning')
                actor=c.hub.resolve(c.a['token']);ticket2=c.hub.store('alpha').create_ticket(actor['actor'],allow_agent=True)
                ac=await browser.new_context();ap=await ac.new_page();await ap.goto(c.url+'/?project=alpha&panel=planning#access='+ticket2,wait_until='networkidle');await ap.wait_for_selector('#workspace:not([hidden])')
                check(await ap.locator('#workspace-edit').is_hidden(),'agent cannot mutate planning')
                r=await ac.request.get(c.url+'/api/projects/beta/governance');check(r.status==404,'foreign planning refused at server')
                await page.locator('#project-select').select_option('beta');await page.wait_for_function("!document.querySelector('#workspace-body').textContent.includes('Core capability')")
                check(not report['errors'],'no JavaScript errors');capture();await ac.close();await context.close()
                report['passed']=True
            finally:await browser.close()
    except BaseException as error:
        report['failure']=repr(error);raise
    finally:
        asyncio.create_subprocess_exec=original;c.tearDown();alive=[]
        for row in report['processes']:
            try:
                p=psutil.Process(row['pid'])
                if abs(p.create_time()-row['created'])<.01:alive.append(p)
            except psutil.NoSuchProcess:pass
        _,alive=psutil.wait_procs(alive,timeout=5)
        for p in alive:
            row=next(r for r in report['processes'] if r['pid']==p.pid)
            if abs(p.create_time()-row['created'])<.01:p.terminate()
        _,alive=psutil.wait_procs(alive,timeout=5);report['remaining']=[p.pid for p in alive]
        if not alive:remove_owned_tree(TEMP,E)
        report['passed']=report['passed'] and not alive
        (E/'RESULT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'evidence':str(E)}))
if __name__=='__main__':asyncio.run(main())
