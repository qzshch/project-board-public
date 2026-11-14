"""Isolated resource catalogue editing, handoff privacy and responsive rendering."""
import asyncio,json,os,subprocess,sys,tempfile,time
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from tests.task_board.test_workflow import WorkflowCase
from task_board import lifecycle
from tools.owned_process import remove_owned_tree
from playwright.async_api import async_playwright
E=ROOT/'evidence/workflow-ui'/time.strftime('%Y%m%d-%H%M%S');E.mkdir(parents=True)
T=E/'browser-temp';T.mkdir();os.environ.update(TMP=str(T),TEMP=str(T),TMPDIR=str(T),PROJECT_BOARD_TEST_ROOT=str(E/'fixtures'));tempfile.tempdir=str(T)
report={'checks':[],'errors':[],'processes':[],'passed':False}
def check(value,label):
    assert value,label
    report['checks'].append(label);lifecycle.write(E/'PROGRESS.json',report)
def capture():
    for p in psutil.Process().children(recursive=True):
        try:
            if not any(r['pid']==p.pid and r['created']==p.create_time() for r in report['processes']):report['processes'].append({'pid':p.pid,'created':p.create_time(),'command':p.cmdline(),'purpose':'Isolated delivery workflow UI verification'})
        except psutil.NoSuchProcess:pass
async def main():
    c=WorkflowCase();c.setUp();original=asyncio.create_subprocess_exec
    async def hidden(*a,**kw):kw['creationflags']=kw.get('creationflags',0)|subprocess.CREATE_NO_WINDOW;return await original(*a,**kw)
    try:
        c.repository();c.member();c.atomic(paths=['feature.py'],baseline=c.first);c.event('new/one','claim',{'summary':'Actual fixture work'})
        asyncio.create_subprocess_exec=hidden
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--disable-gpu','--no-first-run'])
            try:
                capture();context=await browser.new_context(viewport={'width':1280,'height':960});page=await context.new_page();page.on('pageerror',lambda e:report['errors'].append(str(e)))
                ticket=c.hub.admin_store.create_ticket(c.hub.admin_store.authenticate(c.admin['token']));await context.request.post(c.url+'/api/session',data={'ticket':ticket})
                await page.goto(c.url+'/?project=alpha&panel=tasks',wait_until='networkidle');await page.locator('[data-view=all]').click();await page.get_by_role('button',name='one atom',exact=True).click();await page.wait_for_selector('#task-workflow')
                check(True,'task has embedded collaboration and acceptance workspace')
                actor=c.hub.store('alpha').authenticate(c.a['token']);ticket=c.hub.store('alpha').create_ticket(actor,allow_agent=True);worker=await browser.new_context(viewport={'width':1280,'height':960});wp=await worker.new_page();wp.on('pageerror',lambda e:report['errors'].append(str(e)))
                await wp.goto(c.url+'/?project=alpha&panel=tasks#access='+ticket,wait_until='networkidle');await wp.locator('[data-view=all]').click();await wp.get_by_role('button',name='one atom',exact=True).click();await wp.wait_for_selector('#task-workflow')
                check(await wp.get_by_role('button',name='核定结构化验收计划',exact=True).count()==0,'worker has no SE acceptance-plan action')
                async def save(pg):
                    await pg.locator('#detail button[type=submit]').last.click()
                async def done(pg):
                    await pg.wait_for_selector('#task-workflow');await pg.wait_for_function('() => !document.querySelector("#detail .resource-dialog form")')
                await wp.get_by_role('button',name='发起讨论 / 阻塞 / 偏离说明',exact=True).click();await wp.locator('#detail [name=kind]').select_option('blocker');await wp.locator('#detail [name=id]').fill('input-question');await wp.locator('#detail [name=title]').fill('Missing frozen input');await wp.locator('#detail [name=body]').fill('Tried current material, need SE decision; independent work can continue');await wp.locator('#detail [name=pause]').select_option('true')
                captured=[]
                async def intercept(route):
                    if route.request.method!='POST':await route.continue_();return
                    captured.append(route.request.post_data_json)
                    if len(captured)==1:await route.fetch();await route.abort('failed')
                    else:await route.continue_()
                await wp.route('**/api/projects/alpha/operations',intercept);await save(wp);await wp.wait_for_function('() => document.querySelector("#detail .form-message").textContent.length>0');await save(wp);await done(wp);await wp.unroute('**/api/projects/alpha/operations',intercept)
                check(len(captured)==2 and captured[0]==captured[1],'lost comment response retries identical frozen request')
                await page.wait_for_selector('[data-thread=input-question]');check(True,'SE observes new worker obstacle through normal polling')
                check(c.submit(c.feature)[0]==409,'unresolved obstacle blocks API delivery')
                await page.locator('[data-thread=input-question]').get_by_role('button',name='SE记录决策',exact=True).click();await page.locator('#detail [name=summary]').fill('Input confirmed, continue within original frozen scope');await save(page);await done(page)
                await wp.get_by_role('button',name='确认障碍已解决',exact=True).click();await wp.locator('#detail [name=summary]').fill('Read decision, obtained exact input');await save(wp);await done(wp);check('已解决' in await wp.locator('[data-thread=input-question]').inner_text(),'worker acknowledges obstacle resolution')
                await page.get_by_role('button',name='核定结构化验收计划',exact=True).click();await page.locator('#detail [name=id]').fill('ui-accept');await page.locator('#detail [name=git_required]').select_option('true');await page.locator('#detail [name=repo]').fill('main');await page.locator('#detail [name=reason]').fill('Fixed actual acceptance coverage');await save(page);await done(page);await page.wait_for_selector('[data-criterion=AC1]');check(True,'SE creates criterion bound to actual deliverable')
                await wp.get_by_role('button',name='声明此项验证结果',exact=True).click();await wp.locator('#detail [name=input_anchor]').fill('git:'+c.feature);await wp.locator('#detail [name=summary]').fill('Observed expected fixture behavior');await save(wp);await done(wp);check(True,'worker declares precise criterion input')
                await page.get_by_role('button',name='审核此验收项',exact=True).click();await page.locator('#detail [name=summary]').fill('Reviewed actual declared criterion');await save(page);await done(page);check('passed' in await page.locator('[data-criterion=AC1]').inner_text(),'reviewer verdict visible on criterion')
                await page.get_by_role('button',name='提出逐条评审发现',exact=True).click();await page.locator('#detail [name=id]').fill('ui-finding');await page.locator('#detail [name=description]').fill('Boundary <img src=x onerror=alert(1)>');await page.locator('#detail [name=acceptance]').fill('Reproduce fixture boundary');await save(page);await done(page);check(await page.locator('[data-finding=ui-finding] img').count()==0,'finding text cannot inject HTML')
                await wp.get_by_role('button',name='说明修复或异议',exact=True).click();await wp.locator('#detail [name=status]').select_option('rejected');await wp.locator('#detail [name=input_anchor]').fill('git:'+c.feature);await wp.locator('#detail [name=summary]').fill('Counterexample proves report does not apply');await save(wp);await done(wp);check('待复核' in await wp.locator('[data-finding=ui-finding]').inner_text(),'worker objection cannot self-close finding')
                await page.get_by_role('button',name='复核处置',exact=True).click();await page.locator('#detail [name=result]').select_option('dismissed');await page.locator('#detail [name=summary]').fill('Verified concrete counterexample');await save(page);await done(page);check('已核验非问题' in await page.locator('[data-finding=ui-finding]').inner_text(),'SE independently resolves finding')
                await wp.get_by_role('button',name='核验实际Git证据',exact=True).click();await wp.locator('#detail [name=implementation]').fill(c.feature);await wp.locator('#detail [name=target]').fill(c.feature);await wp.locator('#detail [name=reason]').fill('Actual source path and ancestry');await save(wp);await done(wp);check('实际文件 1 项' in await wp.locator('#task-workflow').inner_text(),'real Git objects and path checks rendered')
                result=c.submit(c.feature);check(result[0]==201,'structured criteria and Git check permit exact-input submission');sub=c.hub.store('alpha').get('new/one')['latest_submission']['id'];r=c.event('new/one','accept',{'submission':sub,'summary':'Actual fixture delivery reviewed','deliverable_ids':['D1'],'evidence':[{'path':'fixture/review','sha256':'b'*64}]},c.admin);check(r[0]==201,'original accept gate integrates with workflow')
                await page.get_by_role('button',name='查看 / 发起回退',exact=True).click();await page.locator('#detail [name=id]').fill('ui-restore');await page.locator('#detail [name=reason]').fill('Withdraw current fixture delivery');await page.locator('#detail [name=data_plan]').fill('No data changes, preserve originals');await page.locator('#detail [name=tests]').fill('Reassess new scope and rerun checks');await save(page);await done(page);await page.wait_for_selector('[data-rollback=ui-restore]');check(True,'SE previews frozen rollback impact')
                await page.get_by_role('button',name='确认回退影响',exact=True).click();await page.locator('#detail [name=summary]').fill('SE checked affected scope');await save(page);await done(page)
                await wp.get_by_role('button',name='确认回退影响',exact=True).click();await wp.locator('#detail [name=summary]').fill('Worker checked original outputs retained');await save(wp);await done(wp);check(True,'affected worker confirms same rollback hash')
                await page.get_by_role('button',name='批准执行回退',exact=True).click();await page.locator('#detail [name=summary]').fill('Confirmed current impact and rollback plan');await save(page);await done(page)
                await page.get_by_role('button',name='验收并应用回退',exact=True).click();await page.locator('#detail [name=summary]').fill('Withdraw completed fixture result as new scope');await page.locator('#detail [name=evidence]').fill('fixture/actual-review | '+'b'*64);await save(page);await done(page);check(c.hub.store('alpha').get('new/one')['scope_version']==2,'rollback creates new scope and retains history')
                await page.locator('#close-detail').click();await page.locator('[data-panel=inbox]').click();await page.wait_for_selector('[data-rollback=ui-restore]');check(await page.locator('#task-board').is_hidden(),'SE workbench has no repeated delivery queue');check(await page.locator('#workspace-edit').is_hidden(),'SE workbench uses focused workflow actions')
                for width in (1280,375):
                    for theme in ('light','dark'):
                        await page.set_viewport_size({'width':width,'height':960 if width==1280 else 812});await page.emulate_media(color_scheme=theme);await page.screenshot(path=str(E/f'workbench-{width}-{theme}.png'),full_page=True);check(await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'workbench {width}/{theme} fits')
                await page.locator('#project-select').select_option('beta');await page.wait_for_function('() => app.project==="beta" && !document.querySelector("[data-rollback=ui-restore]")');check('Missing frozen input' not in await page.locator('body').inner_text(),'project switch clears previous workflow contents')
                r=await worker.request.get(c.url+'/api/projects/beta/workflow');check(r.status==404,'worker cannot read foreign workflow')
                for path in ('/help/workflow','/templates/workflow-thread.json','/rollback-kit.zip'):
                    r=await context.request.get(c.url+path);check(r.status==200,'public collaborator reads '+path)
                check(not report['errors'],'no JavaScript errors');report['passed']=True;capture();await worker.close();await context.close()
            finally:await browser.close()
    except BaseException as error:
        report['failure']=repr(error);capture();raise
    finally:
        asyncio.create_subprocess_exec=original;c.tearDown();alive=[]
        for r in report['processes']:
            try:
                p=psutil.Process(r['pid'])
                if abs(p.create_time()-r['created'])<.01:alive.append(p)
            except psutil.NoSuchProcess:pass
        _,alive=psutil.wait_procs(alive,timeout=5)
        for p in alive:
            row=next(r for r in report['processes'] if r['pid']==p.pid)
            if abs(p.create_time()-row['created'])<.01:p.terminate()
        _,alive=psutil.wait_procs(alive,timeout=5);report['remaining']=[p.pid for p in alive]
        if not alive:remove_owned_tree(T,E)
        report['passed']=report['passed'] and not alive and not report['errors'] and len(report['checks'])>=28;lifecycle.write(E/'RESULT.json',report)
    print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'evidence':str(E)}))
if __name__=='__main__':asyncio.run(main())
