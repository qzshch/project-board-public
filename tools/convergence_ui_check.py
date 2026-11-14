"""Actual isolated third-batch UI, roles and responsive rendering."""
import asyncio,json,os,subprocess,sys,tempfile,time
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from tests.task_board.test_convergence import ConvergenceCase
from task_board import lifecycle
from tools.owned_process import remove_owned_tree
from playwright.async_api import async_playwright
E=ROOT/'evidence/convergence-ui'/time.strftime('%Y%m%d-%H%M%S');E.mkdir(parents=True)
T=E/'temporary';T.mkdir();os.environ.update(TMP=str(T),TEMP=str(T),TMPDIR=str(T),PROJECT_BOARD_TEST_ROOT=str(E/'fixtures'));tempfile.tempdir=str(T)
report={'checks':[],'errors':[],'processes':[],'passed':False}
def check(value,label):
    assert value,label
    report['checks'].append(label);lifecycle.write(E/'PROGRESS.json',report)
def capture():
    for p in psutil.Process().children(recursive=True):
        try:
            if not any(x['pid']==p.pid and x['created']==p.create_time() for x in report['processes']):report['processes'].append({'pid':p.pid,'created':p.create_time(),'command':p.cmdline(),'purpose':'Isolated third batch browser acceptance'})
        except psutil.NoSuchProcess:pass
async def main():
    c=ConvergenceCase();c.setUp();original=asyncio.create_subprocess_exec;page=None
    async def hidden(*a,**kw):
        if os.name=='nt':kw['creationflags']=kw.get('creationflags',0)|subprocess.CREATE_NO_WINDOW
        return await original(*a,**kw)
    try:
        c.prepared();c.event('new/one','claim',{'summary':'Actual bounded worker'});asyncio.create_subprocess_exec=hidden
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--disable-gpu','--no-first-run'])
            try:
                capture();ctx=await browser.new_context(viewport={'width':1280,'height':960});page=await ctx.new_page();page.on('pageerror',lambda e:report['errors'].append(str(e)))
                ticket=c.hub.admin_store.create_ticket(c.hub.admin_store.authenticate(c.admin['token']));await ctx.request.post(c.url+'/api/session',data={'ticket':ticket});await page.goto(c.url+'/?project=alpha&panel=planning',wait_until='networkidle');await page.wait_for_selector('#project-templates')
                check('关联规划草案' in await page.locator('#workspace-body').inner_text(),'planning shows a single batch entry')
                async def fill(pg,values):
                    for k,v in values.items():
                        field=pg.locator('#detail [name="'+k+'"]')
                        if await field.evaluate('(e)=>e.tagName')=='SELECT':await field.select_option(str(v).lower() if isinstance(v,bool) else str(v))
                        else:await field.fill(json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else str(v))
                async def save(pg,task=False):
                    await pg.locator('#detail button[type=submit]').last.click()
                    if task:await pg.wait_for_selector('#task-convergence');await pg.wait_for_function('() => !document.querySelector("#detail .resource-dialog form")')
                    else:await pg.wait_for_function('() => !document.querySelector("#detail").open')
                await page.get_by_role('button',name='保存关联规划草案',exact=True).click();await fill(page,{'id':'ui-batch','version':'1','title':'UI bounded planning','reason':'Original four groups only','evidence':'fixture/ui-review.txt | '+'b'*64})
                await page.get_by_role('button',name='加入一项',exact=True).click();await fill(page,{'cv-key-0':'module','cv-payload-0':c.module(id='aux',outputs=['aux-result'],knowledge_refs=[])})
                await save(page);await page.wait_for_selector('[data-draft="ui-batch@1"]');check(c.cv()[1]['drafts']['ui-batch@1']['status']=='draft','worker style batch editor stores immutable draft')
                await page.locator('[data-draft="ui-batch@1"]').get_by_role('button',name='预览并选择本批批准项',exact=True).click();await fill(page,{'approve_modules':'aux@1'});await save(page);await page.wait_for_selector('[data-draft="ui-batch@1"]');check('预览实际影响' in await page.locator('[data-draft="ui-batch@1"]').inner_text(),'preview displays effects and ordering before publish');check('aux@1' not in c.call('/api/projects/alpha/governance',profile=c.admin)[1]['modules'],'browser preview leaves no governance writes')
                await page.locator('[data-draft="ui-batch@1"]').get_by_role('button',name='批准并原子发布',exact=True).click();await fill(page,{'reason':'SE checked complete UI effects','evidence':'fixture/ui-review.txt | '+'b'*64});await save(page);check(c.cv()[1]['drafts']['ui-batch@1']['status']=='published','GUI atomically publishes chosen version')
                # Existing task remains on core@1, so a new head intentionally
                # requires explicit migration. Reuse test uses its approved v1.
                await page.locator('[data-panel=policy]').click();await page.get_by_role('button',name='登记治理规则版本',exact=True).click();r=c.rule();await fill(page,{k:v for k,v in r.items() if k not in ('evidence','paths','categories','contracts','default_items','cases')});await fill(page,{'paths':'src/one/','categories':'documentation','default_items':'Keep original scope','evidence':'fixture/ui-review.txt | '+'b'*64});await save(page);await page.wait_for_selector('[data-rule="internal@1"]');await page.locator('[data-rule="internal@1"]').get_by_role('button',name='核定规则边界',exact=True).click();await fill(page,{'reason':'SE checked fixed rule','evidence':'fixture/ui-review.txt | '+'b'*64});await save(page);check(c.cv()[1]['rules']['internal@1']['readiness']['valid'],'GUI approves exact rule context')
                await page.locator('[data-panel=planning]').click();await page.get_by_role('button',name='登记流程模板版本',exact=True).click();t=c.template();await fill(page,{k:v for k,v in t.items() if k not in ('items','parameters','resource_categories')});await fill(page,{'parameters':'owner','resource_categories':'research'});await page.get_by_role('button',name='加入一项',exact=True).click();await fill(page,{'cv-key-0':'module','cv-payload-0':t['items'][0]['payload']});await save(page);await page.wait_for_selector('[data-template="starter@1"]');await page.locator('[data-template="starter@1"]').get_by_role('button',name='核定模板',exact=True).click();await fill(page,{'reason':'Portable parameterized definition checked'});await save(page);await page.locator('[data-template="starter@1"]').get_by_role('button',name='实例化为待审草案',exact=True).click();await fill(page,{'id':'ui-instance','parameters':{'owner':'root'},'reason':'New bounded draft','evidence':'fixture/ui-review.txt | '+'b'*64});await save(page);check(c.cv()[1]['drafts']['ui-instance@1']['status']=='draft','template instantiation remains an unapproved draft')
                await page.locator('[data-template="starter@1"]').get_by_role('button',name='导出审核后的精确定义',exact=True).click();await page.wait_for_function('() => [...document.querySelectorAll("[data-template] pre")].some(e=>e.textContent.includes("document"))');check(True,'template export exposes exact content and SHA')
                actor=c.hub.store('alpha').authenticate(c.a['token']);ticket=c.hub.store('alpha').create_ticket(actor,allow_agent=True);wc=await browser.new_context(viewport={'width':1280,'height':960});wp=await wc.new_page();wp.on('pageerror',lambda e:report['errors'].append(str(e)));await wp.goto(c.url+'/?project=alpha&panel=tasks#access='+ticket,wait_until='networkidle')
                async def open_task(pg):
                    if await pg.locator('#detail').evaluate('(e)=>e.open'):await pg.locator('#close-detail').click()
                    await pg.locator('[data-panel=tasks]').click();await pg.locator('[data-view=all]').click();await pg.get_by_role('button',name='one atom',exact=True).first.click();await pg.wait_for_selector('#task-convergence')
                await open_task(wp);check(await wp.get_by_role('button',name='启用尝试与租约',exact=True).count()==0,'worker cannot authorize leases');await wp.get_by_role('button',name='沿用批准规则',exact=True).click();await fill(wp,{'ref':'internal@1','reason':'Task matches exact v1 boundary'});await save(wp,True);check(c.cv()[1]['bindings']['new/one']['readiness']['valid'],'worker reuses SE rule in task detail')
                await open_task(page);await page.get_by_role('button',name='授权工作区入口',exact=True).click();await fill(page,{'id':'ui-ws','location':'G:/fixture/isolated','machine':'fixture','branch':'codex/ui','reason':'Actual fixture scope only'});await save(page,True);await page.get_by_role('button',name='启用尝试与租约',exact=True).click();await fill(page,{'actors':'same-agent','workspaces':'ui-ws','lease_seconds':300,'reason':'Opt in bounded continuation'});await save(page,True);check('new/one' in c.cv()[1]['attempt_policies'],'SE authorizes finite task attempt policy')
                await wp.wait_for_function('() => document.querySelector("#task-convergence")?.textContent.includes("已启用执行尝试")');await wp.get_by_role('button',name='开始执行尝试',exact=True).click();await fill(wp,{'id':'ui-try','workspace':'ui-ws','reason':'First actual fixture approach'});await save(wp,True);check(c.cv()[1]['attempts']['ui-try']['status']=='running','authorized worker opens own attempt')
                await wp.get_by_role('button',name='关联接续会话',exact=True).click();await fill(wp,{'id':'ui-session','session':'fixture-session','tool':'codex','machine':'fixture','reason':'Continue current reviewed task'});await save(wp,True);check(c.cv()[1]['sessions']['ui-session']['attempt']=='ui-try','session reference stays under stable attempt')
                await wp.get_by_role('button',name='续租当前尝试',exact=True).click();await save(wp,True);check(True,'worker renews fenced attempt')
                await wp.get_by_role('button',name='记录尝试结果',exact=True).click();await fill(wp,{'input_anchor':'git:'+'c'*40,'stopped':True,'summary':'Exact fixture stopped, workspace and resources released','evidence':'fixture/ui-review.txt | '+'b'*64});await save(wp,True);await page.wait_for_selector('[data-attempt=ui-try]');await page.wait_for_function('() => document.querySelector("[data-attempt=ui-try]")?.textContent.includes("candidate")');await page.get_by_role('button',name='选择候选交付',exact=True).click();await fill(page,{'reason':'SE chooses exact bounded result','evidence':'fixture/ui-review.txt | '+'b'*64});await save(page,True);check(c.cv()[1]['selections']['new/one']['attempt']=='ui-try','SE selects candidate with fixed receipt')
                await wp.get_by_role('button',name='读取当前任务接手包',exact=True).click();await wp.wait_for_selector('[data-context-pack]');check('SHA256' in await wp.locator('[data-context-pack]').inner_text(),'handoff package renders source hashes')
                for pg,label in ((page,'se'),(wp,'worker')):
                    if await pg.locator('#detail').evaluate('(e)=>e.open'):await pg.locator('#close-detail').click()
                    await pg.locator('[data-panel=inbox]').click();await pg.wait_for_function('() => document.querySelector("#workspace-body").textContent.includes("当前下一步")');check(await pg.locator('#workspace-body').get_by_text('规划与接续待办',exact=True).count()==0,label+' has one consolidated workbench')
                    for width in (1280,375):
                        for theme in ('light','dark'):
                            await pg.set_viewport_size({'width':width,'height':960 if width==1280 else 812});await pg.emulate_media(color_scheme=theme);await pg.screenshot(path=str(E/f'{label}-{width}-{theme}.png'),full_page=True);check(await pg.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'{label} {width}/{theme} fits')
                for panel in ('planning','policy','task'):
                    if panel=='task':await open_task(page)
                    else:
                        await page.locator('[data-panel='+panel+']').click()
                        await page.wait_for_selector('#project-templates' if panel=='planning' else '[data-rule]')
                    for width in (1280,375):
                        for theme in ('light','dark'):
                            await page.set_viewport_size({'width':width,'height':960 if width==1280 else 812});await page.emulate_media(color_scheme=theme);await page.screenshot(path=str(E/f'{panel}-{width}-{theme}.png'),full_page=True);check(await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'{panel} {width}/{theme} fits')
                    if panel=='task':await page.locator('#close-detail').click()
                await page.locator('#project-select').select_option('beta');await page.wait_for_function('() => app.project==="beta" && !document.body.textContent.includes("UI bounded planning")');check(True,'project switch clears all third batch data');check((await wc.request.get(c.url+'/api/projects/beta/convergence')).status==404,'worker cannot access foreign convergence')
                for path in ('/help/convergence','/templates/convergence-draft.json','/templates/convergence-rule.json','/templates/convergence-attempt.json','/templates/convergence-template.json','/observer-kit.zip'):
                    check((await ctx.request.get(c.url+path)).status==200,'public read '+path)
                check(not report['errors'],'no browser JavaScript errors');report['passed']=True;capture();await wc.close();await ctx.close()
            finally:await browser.close()
    except BaseException as error:
        report['failure']=repr(error);capture()
        if page:
            try:report['visible_failure']=await page.locator('body').inner_text();await page.screenshot(path=str(E/'FAILURE.png'),full_page=True)
            except Exception:pass
        raise
    finally:
        asyncio.create_subprocess_exec=original;c.tearDown();alive=[]
        for row in report['processes']:
            try:
                p=psutil.Process(row['pid'])
                if abs(p.create_time()-row['created'])<.01:alive.append(p)
            except psutil.NoSuchProcess:pass
        _,alive=psutil.wait_procs(alive,timeout=5)
        for p in alive:
            row=next(x for x in report['processes'] if x['pid']==p.pid)
            if abs(p.create_time()-row['created'])<.01:p.terminate()
        _,alive=psutil.wait_procs(alive,timeout=5);report['remaining']=[p.pid for p in alive]
        if not alive:remove_owned_tree(T,E)
        report['passed']=report['passed'] and not alive and not report['errors'];lifecycle.write(E/'RESULT.json',report)
    print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'evidence':str(E)}))
if __name__=='__main__':asyncio.run(main())
