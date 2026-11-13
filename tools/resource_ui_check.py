"""Isolated resource catalogue editing, handoff privacy and responsive rendering."""
import asyncio,json,os,subprocess,sys,tempfile,time
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from tests.task_board.test_resources import ResourcesCase
from task_board import lifecycle
from tools.owned_process import remove_owned_tree
from playwright.async_api import async_playwright
E=ROOT/'evidence/resource-ui'/time.strftime('%Y%m%d-%H%M%S');E.mkdir(parents=True)
T=E/'browser-temp';T.mkdir();os.environ.update(TMP=str(T),TEMP=str(T),TMPDIR=str(T),PROJECT_BOARD_TEST_ROOT=str(E/'fixtures'));tempfile.tempdir=str(T)
report={'checks':[],'errors':[],'processes':[],'passed':False}
def check(value,label):
    assert value,label
    report['checks'].append(label);lifecycle.write(E/'PROGRESS.json',report)
def capture():
    for p in psutil.Process().children(recursive=True):
        try:
            if not any(r['pid']==p.pid and r['created']==p.create_time() for r in report['processes']):report['processes'].append({'pid':p.pid,'created':p.create_time(),'command':p.cmdline(),'purpose':'Isolated resource UI verification'})
        except psutil.NoSuchProcess:pass
async def main():
    c=ResourcesCase();c.setUp();original=asyncio.create_subprocess_exec
    async def hidden(*a,**kw):kw['creationflags']=kw.get('creationflags',0)|subprocess.CREATE_NO_WINDOW;return await original(*a,**kw)
    try:
        c.atomic();c.atomic('second',['second/'])
        for category in ('cache','research','art','archive','test_records','logs','runtime','documentation'):
            value=c.payload(category.replace('_','-'),category=category,title='Fixture '+category);value['locations'][0]['location']='/nas/alpha/'+category
            check(c.gov('resource_register',value)[0]==201,'fixture '+category+' registered')
        check(c.gov('resource_register',c.payload('managed',visibility='managers',title='Manager-only source'))[0]==201,'manager fixture registered')
        check(c.gov('resource_register',c.payload('operator-state',visibility='operator',title='Operator-only state'))[0]==201,'operator fixture registered')
        asyncio.create_subprocess_exec=hidden
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--disable-gpu','--no-first-run'])
            try:
                capture();context=await browser.new_context(viewport={'width':1280,'height':960});page=await context.new_page();page.on('pageerror',lambda e:report['errors'].append(str(e)))
                ticket=c.hub.admin_store.create_ticket(c.hub.admin_store.authenticate(c.admin['token']))
                response=await context.request.post(c.url+'/api/session',data={'ticket':ticket});check(response.status==200,'existing admin cookie accepted')
                async def delayed(route):await asyncio.sleep(.35);await route.continue_()
                await page.route('**/resources.js',delayed)
                await page.goto(c.url+'/?project=alpha&panel=assets',wait_until='networkidle');await page.wait_for_selector('#resource-directory [data-resource="research"]');await page.unroute('**/resources.js',delayed)
                check(await page.locator('#resource-directory [data-resource]').count()==10,'cold cookie startup renders every authorized category')
                check(await page.locator('#task-board').is_hidden(),'asset page excludes repeated delivery queue')
                for width in (1280,375):
                    for theme in ('light','dark'):
                        await page.set_viewport_size({'width':width,'height':960 if width==1280 else 812});await page.emulate_media(color_scheme=theme)
                        await page.screenshot(path=str(E/f'catalogue-{width}-{theme}.png'),full_page=True)
                        check(await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'catalogue {width}/{theme} fits')
                await page.set_viewport_size({'width':1280,'height':960})
                await page.locator('[name=resource-category]').select_option('art');await page.wait_for_function('() => document.querySelectorAll("[data-resource]").length===1')
                check('/nas/alpha/art' in await page.locator('#resource-directory').inner_text(),'category filter exposes actual location')
                await page.locator('[name=resource-category]').select_option('');await page.wait_for_selector('#resource-directory [data-resource="research"]')
                await page.get_by_role('button',name='登记资源入口',exact=True).click();await page.wait_for_selector('#detail [name=id]')
                values={'id':'ui-entry','title':'UI retained files','description':'Actual fixture directory, no upload','owner':'root','version':'live','retention':'Keep originals and stop recommending metadata only','usage_notes':'Fixture authorization only','tasks':'new/one','reason':'UI editing and exact retry verification'}
                for key,value in values.items():await page.locator('#detail [name='+key+']').fill(value)
                for key,value in {'machine':'fixture host','location':'/nas/alpha/ui-retained','access':'Project scoped OS authorization from SE'}.items():await page.locator('#detail [data-location-field='+key+']').fill(value)
                captured=[]
                async def intercept(route):
                    if route.request.method!='POST':await route.continue_();return
                    captured.append(route.request.post_data_json)
                    if len(captured)==1:await route.fetch();await route.abort('failed')
                    else:await route.continue_()
                await page.route('**/api/projects/alpha/governance',intercept);await page.locator('#detail button[type=submit]').click();await page.wait_for_function('() => document.querySelector("#detail .form-message").textContent.length>0')
                await page.locator('#detail [name=title]').fill('Changed after lost reply, must not mutate retry')
                await page.locator('#detail button[type=submit]').click();await page.locator('#detail').wait_for(state='hidden');await page.unroute('**/api/projects/alpha/governance',intercept)
                check(len(captured)==2 and captured[0]==captured[1],'lost reply retries original complete frozen request')
                await page.wait_for_selector('#resource-directory [data-resource="ui-entry"]');row=page.locator('#resource-directory [data-resource="ui-entry"]')
                check('UI retained files' in await row.inner_text(),'retry preserves original registered title')
                await row.get_by_role('button',name='更新登记',exact=True).click();await page.wait_for_selector('#detail [name=id]');check(await page.locator('#detail [name=id]').get_attribute('readonly') is not None,'entry ID immutable on edit')
                await page.locator('#detail [name=title]').fill('Updated actual entry');await page.locator('#detail [name=reason]').fill('Supplement handoff detail');await page.locator('#detail button[type=submit]').click();await page.locator('#detail').wait_for(state='hidden');await page.wait_for_selector('#resource-directory [data-resource="ui-entry"]')
                check('v2' in await page.locator('#resource-directory [data-resource="ui-entry"]').inner_text(),'edit appends metadata version')
                await page.locator('#resource-directory [data-resource="ui-entry"]').get_by_role('button',name='位置版本历史').click();await page.wait_for_function('() => document.querySelectorAll("#detail [data-resource]").length===2');check(True,'authorized metadata history displayed');await page.locator('#close-detail').click()
                await page.locator('[name=resource-task]').select_option('second');await page.wait_for_function('() => !document.querySelector("#resource-directory [data-resource=ui-entry]")');check(True,'task filter excludes unrelated task-specific files')
                await page.locator('[name=resource-task]').select_option('new/one');await page.wait_for_selector('#resource-directory [data-resource="ui-entry"]');check(True,'matching task includes its resource')
                await page.locator('#resource-directory [data-resource="ui-entry"]').get_by_role('button',name='停止推荐此入口').click();await page.locator('#detail [name=reason]').fill('Retained original, no longer recommended');await page.locator('#detail button[type=submit]').click();await page.locator('#detail').wait_for(state='hidden');await page.wait_for_function('() => !document.querySelector("#resource-directory [data-resource=ui-entry]")');check(True,'retired metadata removed from active catalogue')
                await page.locator('[name=resource-status]').select_option('all');await page.wait_for_selector('#resource-directory [data-resource="ui-entry"]');check('已停止推荐' in await page.locator('#resource-directory [data-resource="ui-entry"]').inner_text(),'retired metadata explicitly available with history filter')
                await page.locator('#project-select').select_option('beta');await page.wait_for_function('() => app.project==="beta" && document.querySelector("#resource-directory .empty")')
                check('/nas/alpha' not in await page.locator('body').inner_text(),'project switch removes prior resource locations')
                actor=c.hub.store('alpha').authenticate(c.a['token']);ticket=c.hub.store('alpha').create_ticket(actor,allow_agent=True);worker=await browser.new_context();wp=await worker.new_page();wp.on('pageerror',lambda e:report['errors'].append(str(e)))
                await wp.goto(c.url+'/?project=alpha&panel=assets#access='+ticket,wait_until='networkidle');await wp.wait_for_selector('[data-resource="research"]')
                text=await wp.locator('#resource-directory').inner_text();check('Manager-only source' not in text and 'Operator-only state' not in text,'ordinary Agent cannot see management or instance resource metadata')
                check(await wp.get_by_role('button',name='登记资源入口',exact=True).count()==0,'ordinary Agent has no catalogue mutation form')
                response=await worker.request.get(c.url+'/api/projects/beta/resources');check(response.status==404,'project identity cannot enumerate another project directory')
                response=await worker.request.get(c.url+'/help/resources');check(response.status==200,'external role can read resource handoff guide')
                response=await worker.request.get(c.url+'/templates/resource-entry.json');check(response.status==200,'resource template downloadable without global identity')
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
        report['passed']=report['passed'] and not alive and not report['errors'] and len(report['checks'])>=30;lifecycle.write(E/'RESULT.json',report)
    print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'evidence':str(E)}))
if __name__=='__main__':asyncio.run(main())
