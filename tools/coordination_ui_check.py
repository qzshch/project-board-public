"""Real isolated browser workflow for the complete second-batch path."""
import asyncio,json,os,subprocess,sys,tempfile,time
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from tests.task_board.test_coordination import CoordinationCase
from task_board import lifecycle
from tools.owned_process import remove_owned_tree
from playwright.async_api import async_playwright
E=ROOT/'evidence/coordination-ui'/time.strftime('%Y%m%d-%H%M%S');E.mkdir(parents=True)
T=E/'browser-temp';T.mkdir();os.environ.update(TMP=str(T),TEMP=str(T),TMPDIR=str(T),PROJECT_BOARD_TEST_ROOT=str(E/'fixtures'));tempfile.tempdir=str(T)
report={'checks':[],'errors':[],'processes':[],'passed':False}
def check(v,label):
    assert v,label
    report['checks'].append(label);lifecycle.write(E/'PROGRESS.json',report)
def capture():
    for p in psutil.Process().children(recursive=True):
        try:
            if not any(x['pid']==p.pid and x['created']==p.create_time() for x in report['processes']):report['processes'].append({'pid':p.pid,'created':p.create_time(),'command':p.cmdline(),'purpose':'Isolated second-batch UI acceptance'})
        except psutil.NoSuchProcess:pass
async def main():
    c=CoordinationCase();c.setUp();original=asyncio.create_subprocess_exec
    async def hidden(*a,**kw):kw['creationflags']=kw.get('creationflags',0)|subprocess.CREATE_NO_WINDOW;return await original(*a,**kw)
    try:
        c.repository();c.member();c.atomic(paths=['feature.py'],baseline=c.first);c.event('new/one','claim',{'summary':'Current bounded implementation'})
        asyncio.create_subprocess_exec=hidden
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--disable-gpu','--no-first-run'])
            try:
                capture();context=await browser.new_context(viewport={'width':1280,'height':960});page=await context.new_page();page.on('pageerror',lambda e:report['errors'].append(str(e)))
                ticket=c.hub.admin_store.create_ticket(c.hub.admin_store.authenticate(c.admin['token']));await context.request.post(c.url+'/api/session',data={'ticket':ticket})
                async def delay(route):await asyncio.sleep(.4);await route.continue_()
                await page.route('**/coordination.js',delay);await page.goto(c.url+'/?project=alpha&panel=discovery',wait_until='networkidle');await page.wait_for_selector('[name=co-search]');await page.unroute('**/coordination.js',delay)
                check('尚无需求或发现' in await page.locator('#workspace-body').inner_text(),'empty discovery and delayed-module boot render safely')
                actor=c.hub.store('alpha').authenticate(c.a['token']);ticket=c.hub.store('alpha').create_ticket(actor,allow_agent=True);worker=await browser.new_context(viewport={'width':1280,'height':960});wp=await worker.new_page();wp.on('pageerror',lambda e:report['errors'].append(str(e)))
                await wp.goto(c.url+'/?project=alpha&panel=tasks#access='+ticket,wait_until='networkidle');await wp.locator('[data-view=all]').click();await wp.get_by_role('button',name='one atom',exact=True).click();await wp.wait_for_selector('#task-continuation')
                check(await wp.get_by_role('button',name='选择实施评审要求',exact=True).count()==0,'worker cannot choose SE plan policy')
                async def fill(pg,**values):
                    for k,v in values.items():await pg.locator('#detail [name='+k+']').fill(str(v))
                async def save(pg,task=False):
                    await pg.locator('#detail button[type=submit]').last.click()
                    if task:await pg.wait_for_selector('#task-continuation');await pg.wait_for_function('() => !document.querySelector("#detail .resource-dialog form")')
                    else:await pg.wait_for_function('() => !document.querySelector("#detail").open')
                await wp.get_by_role('button',name='登记需求 / 发现',exact=True).click();await fill(wp,id='observed',title='Boundary <img src=x onerror=alert(1)>',body='Actual separate defect, keep original scope bounded')
                captured=[]
                async def lost(route):
                    if route.request.method!='POST':await route.continue_();return
                    captured.append(route.request.post_data_json)
                    if len(captured)==1:await route.fetch();await route.abort('failed')
                    else:await route.continue_()
                await wp.route('**/api/projects/alpha/operations',lost);await wp.locator('#detail button[type=submit]').last.click();await wp.wait_for_function('() => document.querySelector("#detail .form-message").textContent.length>0');await save(wp);await wp.unroute('**/api/projects/alpha/operations',lost)
                check(len(captured)==2 and captured[0]==captured[1],'lost intake response replays identical request')
                await page.wait_for_selector('[data-intake=observed]');check(await page.locator('[data-intake=observed] img').count()==0,'intake content cannot inject markup')
                await page.locator('[data-intake=observed]').get_by_role('button',name='SE分诊',exact=True).click();await page.locator('#detail [name=status]').select_option('approved');await fill(page,reason='Create separate approved repair');await save(page)
                check(c.co()[1]['intakes']['observed']['status']=='approved','SE triage is stored without starting work')
                await page.locator('[data-intake=observed]').get_by_role('button',name='从需求建立任务',exact=True).click();spec=dict(c.hub.store('alpha').get('new/one')['spec']);spec.update(id='new/discovered',title='Discovered repair',allowed_paths=['repair/']);await fill(page,spec=json.dumps(spec),reason='Bounded repair with explicit source');await save(page)
                check(c.hub.store('alpha').get('new/discovered')['status']=='planned','GUI conversion creates task atomically with provenance')
                await wp.locator('[data-panel=tasks]').click();await wp.locator('[data-view=all]').click();await wp.get_by_role('button',name='one atom',exact=True).first.click();await wp.wait_for_selector('#task-continuation')
                await wp.get_by_role('button',name='保存执行检查点',exact=True).click();await fill(wp,id='ui-checkpoint',input_anchor='git:'+c.feature,completed='Implemented fixed source',remaining='Await independent review',tests='Actual fixture behavior checked',obstacles='Review pending',next_step='Read review and exact input',recheck='Scope, contracts and runtime ownership',session='ui-worker');await save(wp,True)
                check('ui-checkpoint' in await wp.locator('#task-continuation').inner_text(),'durable worker checkpoint renders continuation')
                await wp.get_by_role('button',name='读取检查点之后的变化',exact=True).click();await wp.wait_for_function('() => [...document.querySelectorAll("#task-continuation pre")].some(e=>e.textContent.includes("has_more"))');await wp.locator('#task-continuation details').last.locator('summary').click();check(True,'checkpoint incremental feed can be read')
                await page.locator('[data-panel=tasks]').click();await page.locator('[data-view=all]').click();await page.get_by_role('button',name='one atom',exact=True).first.click();await page.wait_for_selector('#task-continuation')
                await page.get_by_role('button',name='选择实施评审要求',exact=True).click();await fill(page,reason='SE selects current task plan review');await save(page,True)
                await wp.get_by_role('button',name='提交实施计划',exact=True).click();await fill(wp,id='ui-plan',steps='Review exact feature input\nVerify boundary behavior',validation='Current input positive and negative cases',risks='Boundary interpretation',stop_conditions='Stop on shared interface change');await save(wp,True)
                await page.wait_for_selector('[data-execution-plan=ui-plan]');await page.get_by_role('button',name='评审实施计划',exact=True).click();await fill(page,reason='Reviewed bounded implementation and tests');await save(page,True);check('已批准' in await page.locator('[data-execution-plan=ui-plan]').inner_text(),'distinct SE approves current implementation plan')
                await page.get_by_role('button',name='查看差异并批量评审',exact=True).click();await fill(page,target=c.feature);await page.get_by_role('button',name='读取固定差异',exact=True).click();await page.get_by_role('button',name='查看 feature.py',exact=True).click();await page.get_by_role('button',name='评论 right:1',exact=True).click();await page.locator('#detail input[name^=comment-]').fill('Verify missing boundary case');await page.get_by_role('button',name='加入本批',exact=True).click();await page.get_by_role('button',name='整理本批发现',exact=True).click();await fill(page,id='ui-batch',summary='Demonstrate actual positive and negative fixture cases');await save(page,True)
                check('ui-batch-1' in c.call('/api/projects/alpha/workflow/task?task=new/one',profile=c.admin)[1]['findings'],'inline diff review creates independently tracked finding')
                await page.get_by_role('button',name='核定返工根因',exact=True).click();await fill(page,finding='ui-batch-1',reason='Confirmed missing negative-case coverage');await page.locator('#detail [name=category]').select_option('test_gap');await save(page,True)
                await page.get_by_role('button',name='登记外部条件门',exact=True).click();await fill(page,id='ui-human',input_anchor='git:'+c.feature,reason='Exact reviewed implementation input');await page.locator('#detail [name=kind]').select_option('human');await save(page,True)
                await page.get_by_role('button',name='确认人工条件',exact=True).click();await fill(page,reason='Authorized SE confirms actual fixed input');await save(page,True);check(c.co()[1]['gates']['ui-human']['satisfied'],'authorized manual condition passes only its fixed gate')
                # Reconcile the specific finding under separate worker/reviewer identities.
                c.op('review_disposition',{**c.scope(),'finding':'ui-batch-1','status':'rejected','input_anchor':'git:'+c.feature,'summary':'Concrete fixture counterexample establishes expected behavior','runs':[],'evidence':[]},c.a)
                wf=c.call('/api/projects/alpha/workflow/task?task=new/one',profile=c.admin)[1];c.op('review_resolve',{**c.scope(),'finding':'ui-batch-1','disposition':wf['findings']['ui-batch-1']['disposition']['id'],'result':'dismissed','summary':'SE verified counterexample','evidence':[]})
                check(c.submit(c.feature)[0]==201,'current plan, reviewed finding and exact gate permit original submission')
                await page.locator('#close-detail').click();await page.locator('[data-panel=time]').click();await page.wait_for_function('() => document.querySelector("#workspace-body").textContent.includes("不是申报工时")');await page.locator('#workspace-body summary').filter(has_text='根因核定').click();check('测试遗漏' in await page.locator('#workspace-body').inner_text(),'flow and root-cause measures appear with correct meaning')
                await page.locator('[data-panel=quality]').click();await page.wait_for_function('() => document.querySelector("#workspace-body").textContent.includes("验收项、测试运行")');check(True,'quality page exposes acceptance-run-case-finding coverage')
                await page.locator('[data-panel=discovery]').click();await page.wait_for_selector('[data-intake=observed]');check(await page.locator('#task-board').is_hidden(),'discovery does not repeat delivery queue')
                for width in (1280,375):
                    for theme in ('light','dark'):
                        await page.set_viewport_size({'width':width,'height':960 if width==1280 else 812});await page.emulate_media(color_scheme=theme);await page.screenshot(path=str(E/f'discovery-{width}-{theme}.png'),full_page=True);check(await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'discovery {width}/{theme} fits')
                await page.set_viewport_size({'width':1280,'height':960});await page.locator('[data-panel=tasks]').click();await page.locator('[data-view=all]').click();await page.get_by_role('button',name='one atom',exact=True).first.click();await page.wait_for_selector('#task-continuation');await page.locator('#task-continuation h3').first.scroll_into_view_if_needed();await page.screenshot(path=str(E/'continuation-desktop.png'),full_page=True);await page.set_viewport_size({'width':375,'height':812});await page.locator('#task-continuation h3').first.scroll_into_view_if_needed();await page.screenshot(path=str(E/'continuation-mobile.png'),full_page=True);check(await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),'continuation dialog mobile fits')
                await page.locator('#close-detail').click();await page.locator('#project-select').select_option('beta');await page.wait_for_function('() => app.project==="beta"');await page.locator('[data-panel=discovery]').click();await page.wait_for_selector('[name=co-search]');check('Boundary <img' not in await page.locator('body').inner_text(),'project switch clears discovery and continuation data')
                check((await worker.request.get(c.url+'/api/projects/beta/coordination/feed')).status==404,'foreign project feed denied')
                anon=await browser.new_context()
                for path in ('/help/coordination','/templates/coordination-checkpoint.json','/observer-kit.zip'):
                    check((await anon.request.get(c.url+path)).status==200,'external collaborator reads '+path)
                check(not report['errors'],'no browser script errors');report['passed']=True;capture();await anon.close();await worker.close();await context.close()
            finally:
                if not report['passed']:
                    try:
                        report['failure_view']=await page.locator('body').inner_text();await page.screenshot(path=str(E/'FAILURE.png'),full_page=True)
                    except Exception:pass
                await browser.close()
    except BaseException as error:
        report['failure']=repr(error);capture()
        try:
            report['visible_failure']=await page.locator('body').inner_text();await page.screenshot(path=str(E/'FAILURE.png'),full_page=True)
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
