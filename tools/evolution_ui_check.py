"""Real populated policy/time/test/asset workflows in isolated browser fixtures."""
import asyncio,json,os,subprocess,sys,tempfile,time
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.task_board.test_operations import OperationsCase
from tools.owned_process import remove_owned_tree
from playwright.async_api import async_playwright
E=ROOT/'evidence/evolution-ui'/time.strftime('%Y%m%d-%H%M%S');E.mkdir(parents=True)
T=E/'browser-temp';T.mkdir();os.environ.update(TMP=str(T),TEMP=str(T),TMPDIR=str(T),PROJECT_BOARD_TEST_ROOT=str(E/'fixtures'));tempfile.tempdir=str(T)
report={'checks':[],'errors':[],'processes':[],'passed':False}
def check(value,label):
    if not value:raise AssertionError(label)
    report['checks'].append(label)
def capture():
    for p in psutil.Process().children(recursive=True):
        try:
            if not any(r['pid']==p.pid and r['created']==p.create_time() for r in report['processes']):report['processes'].append({'pid':p.pid,'created':p.create_time(),'command':p.cmdline(),'purpose':'isolated complete product4 UI'})
        except psutil.NoSuchProcess:pass
async def main():
    c=OperationsCase();c.setUp();original=asyncio.create_subprocess_exec
    async def hidden(*args,**kw):kw['creationflags']=kw.get('creationflags',0)|subprocess.CREATE_NO_WINDOW;return await original(*args,**kw)
    asyncio.create_subprocess_exec=hidden
    try:
        c.test_real_runner_exports_fixed_commit_hashes_artifacts_and_cleans_scratch()
        import shutil
        for p in (c.state/'runner-fixture/output').rglob('*'):
            if p.is_file() and 'artifacts' not in p.parts:
                dest=E/'runner-evidence'/p.relative_to(c.state/'runner-fixture/output');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
        c.atomic('consume/one',['consumer/'],assets=['verified@1']);c.assess(tid='consume/one');c.event('consume/one','claim',{'summary':'Consume validated bytes'})
        c.gov('package',{'id':'internal','tasks':['new/one','consume/one'],'source':'Actual fixture atom mapping','unknown':'No unresolved boundary'})
        ticket=c.hub.admin_store.create_ticket(c.hub.admin_store.authenticate(c.admin['token']))
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--disable-gpu','--no-first-run'])
            try:
                capture();context=await browser.new_context(viewport={'width':1280,'height':960});page=await context.new_page();page.on('pageerror',lambda error:report['errors'].append(str(error)))
                await page.goto(c.url+'/?project=alpha&panel=policy#kind=admin&access='+ticket,wait_until='networkidle');await page.wait_for_selector('#workspace:not([hidden])')
                async def save(action,p,lose_reply=False):
                    if not await page.locator('#detail').is_visible():
                        if action=='asset_feedback':await page.get_by_role('button',name='管理资产沉淀').click()
                        else:await page.locator('#workspace-edit').click()
                    await page.locator('[name=op_action]').select_option(action)
                    for k,value in p.items():
                        field=page.locator('#detail [name='+k+']')
                        if await field.evaluate('(x)=>x.tagName')=='SELECT':await field.select_option(str(value).lower() if isinstance(value,bool) else value)
                        else:await field.fill('\n'.join(value) if isinstance(value,list) else str(value))
                    captured=[]
                    async def intercept(route):
                        if route.request.method!='POST':await route.continue_();return
                        captured.append(route.request.post_data_json)
                        if len(captured)==1:await route.fetch();await route.abort('failed')
                        else:await route.continue_()
                    if lose_reply:await page.route('**/api/projects/alpha/operations',intercept)
                    await page.locator('#detail button[type=submit]').click()
                    if lose_reply:
                        await page.wait_for_function('() => document.querySelector("#detail .form-message").textContent.length>0')
                        await page.locator('#detail button[type=submit]').click()
                    try:await page.locator('#detail').wait_for(state='hidden',timeout=12000)
                    except BaseException:
                        (E/'FAILED-DIALOG.txt').write_text(await page.locator('#detail').inner_text(),encoding='utf8');await page.screenshot(path=str(E/'failed-dialog.png'));raise
                    if lose_reply:
                        await page.unroute('**/api/projects/alpha/operations',intercept);check(len(captured)==2 and captured[0]==captured[1],'lost reply retries identical frozen request without duplicate operation')
                check('轻量' in await page.locator('#workspace-body').inner_text(),'effective tier visible')
                await save('assess_package',{'package':'internal','level':'light','flags':[],'reason':'Reviewed independent internal atoms'},lose_reply=True)
                check(c.ops()['package_assurance']['internal']['all_assessed'],'UI bulk assessment binds current package scopes')
                await page.locator('[data-panel=time]').click()
                await save('estimate',{'task':'new/one','low':10,'likely':20,'high':30,'due':'','size':'small','uncertainty':'low','context':'Fixture Python and fixed toolchain','reason':'Bounded behavior comparison'})
                check(len(c.ops()['estimates']['new/one'])==1,'UI saves estimate version')
                await save('time_change',{'task':'new/one','mode':'work','phase':'asset','reason':'Refine reusable input','rework':False})
                await save('time_change',{'task':'new/one','mode':'wait','phase':'review','reason':'Wait for independent review','rework':False})
                await save('time_change',{'task':'new/one','mode':'stop','phase':'review','reason':'Review ready','rework':False})
                await save('time_complete',{'task':'new/one','summary':'All explicit fixture sessions recorded'})
                check(c.ops()['time_report']['work_seconds']>0 and c.ops()['time_report']['wait_seconds']>0,'UI separates actual work and waiting')
                check('未知' in await page.locator('#workspace-body').inner_text(),'unrecorded historical effort remains unknown')
                await page.locator('[data-panel=quality]').click()
                await save('case',{'id':'manual-ui','version':'1','title':'实际人工界面核对','kind':'manual','priority':'normal','targets':['task:new/one'],'preconditions':'Fixed render','inputs':'Known viewport','steps':'Inspect outcome','expected':'No overflow and clear state','environment':'fixture','resources':[]})
                check('manual-ui@1' in c.ops()['cases'],'UI creates versioned testcase')
                statuses={r['status'] for r in c.ops()['runs'].values()};check({'passed','failed','timeout'}<=statuses,'UI fixture contains real success failure and timeout')
                check('failed' in await page.locator('#workspace-body').inner_text(),'failure remains visible beside success')
                await page.locator('[data-panel=assets]').click()
                check('promoted' in await page.locator('#workspace-body').inner_text(),'validated asset lifecycle visible')
                await save('asset_feedback',{'asset':'verified@1','task':'consume/one','outcome':'succeeded','integration_minutes':3,'estimated_saved_minutes':12,'issues':'Validated input matched; savings are an estimate'})
                check(c.ops()['usage'][0]['integration_minutes']==3,'UI records actual adoption cost separately from estimated savings')
                for panel in ('policy','time','quality','assets'):
                    await page.locator('[data-panel='+panel+']').click();check(await page.locator('#task-board').is_hidden(),panel+' has no delivery queue')
                    for width in (1280,375):
                        for theme in ('light','dark'):
                            await page.set_viewport_size({'width':width,'height':960 if width==1280 else 812});await page.emulate_media(color_scheme=theme)
                            check(await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'{panel} {width}/{theme} fits');await page.screenshot(path=str(E/f'{panel}-{width}-{theme}.png'),full_page=True)
                await page.locator('#project-select').select_option('beta');await page.wait_for_function('() => Boolean(ws.ops && Object.keys(ws.ops.candidates).length===0 && app.project==="beta")')
                check('Reusable tested bytes' not in await page.locator('#workspace-body').inner_text(),'switch clears private candidate details')
                actor=c.hub.resolve(c.a['token']);ticket2=c.hub.store('alpha').create_ticket(actor['actor'],allow_agent=True);ac=await browser.new_context();ap=await ac.new_page();await ap.goto(c.url+'/?project=alpha&panel=policy#access='+ticket2,wait_until='networkidle');await ap.wait_for_selector('#workspace:not([hidden])')
                check(await ap.locator('#workspace-edit').is_hidden(),'worker cannot edit governance policy');r=await ac.request.get(c.url+'/api/projects/beta/operations');check(r.status==404,'foreign operational records refused')
                check(not report['errors'],'no browser errors');capture();await ac.close();await context.close();report['passed']=True
            finally:await browser.close()
    except BaseException as error:report['failure']=repr(error);raise
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
        if not alive:remove_owned_tree(T,E)
        report['passed']=report['passed'] and not alive;(E/'RESULT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'evidence':str(E)}))
if __name__=='__main__':asyncio.run(main())
