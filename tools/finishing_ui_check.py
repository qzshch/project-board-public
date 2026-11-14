"""Actual isolated bounded finishing UI, roles and responsive rendering."""
import asyncio,json,os,subprocess,sys,tempfile,time
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from tests.task_board.test_finishing import FinishingCase as ConvergenceCase
from task_board import lifecycle
from tools.owned_process import remove_owned_tree
from playwright.async_api import async_playwright
E=ROOT/'evidence/finishing-ui'/time.strftime('%Y%m%d-%H%M%S');E.mkdir(parents=True)
T=E/'temporary';T.mkdir();os.environ.update(TMP=str(T),TEMP=str(T),TMPDIR=str(T),PROJECT_BOARD_TEST_ROOT=str(E/'fixtures'));tempfile.tempdir=str(T)
report={'checks':[],'errors':[],'processes':[],'passed':False}
def check(value,label):
    assert value,label
    report['checks'].append(label);lifecycle.write(E/'PROGRESS.json',report)
def capture():
    for p in psutil.Process().children(recursive=True):
        try:
            if not any(x['pid']==p.pid and x['created']==p.create_time() for x in report['processes']):report['processes'].append({'pid':p.pid,'created':p.create_time(),'command':p.cmdline(),'purpose':'Isolated bounded finishing browser acceptance'})
        except psutil.NoSuchProcess:pass
async def main():
    c=ConvergenceCase();c.setUp();original=asyncio.create_subprocess_exec;page=None
    async def hidden(*a,**kw):
        if os.name=='nt':kw['creationflags']=kw.get('creationflags',0)|subprocess.CREATE_NO_WINDOW
        return await original(*a,**kw)
    try:
        c.participants();c.charter()
        c.ok('criteria_plan',{**c.scope(),'id':'ui-accept','items':[{'id':'A','deliverable':'D1','expected':'Behavior A','method':'manual'},{'id':'B','deliverable':'D1','expected':'Boundary B','method':'inspection'}],'defaults':'','git_required':False,'repo':'','reason':'Actual scoped fixture criteria'})
        c.ok('condition_gate',c.gate());asyncio.create_subprocess_exec=hidden
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--disable-gpu','--no-first-run'])
            try:
                capture();contexts=[]
                async def login(profile,admin=False):
                    ctx=await browser.new_context(viewport={'width':1280,'height':960});pg=await ctx.new_page();pg.on('pageerror',lambda e:report['errors'].append(str(e)));contexts.append(ctx)
                    if admin:
                        ticket=c.hub.admin_store.create_ticket(c.hub.admin_store.authenticate(profile['token']));await ctx.request.post(c.url+'/api/session',data={'ticket':ticket});await pg.goto(c.url+'/?project=alpha&panel=inbox',wait_until='networkidle')
                    else:
                        actor=c.hub.store('alpha').authenticate(profile['token']);ticket=c.hub.store('alpha').create_ticket(actor,allow_agent=True);await pg.goto(c.url+'/?project=alpha&panel=inbox#access='+ticket,wait_until='networkidle')
                    await pg.wait_for_function('() => document.querySelector("#workspace-body").textContent.includes("当前下一步")');return ctx,pg
                ctx,page=await login(c.admin,True);owner,ap=await login(c.a);worker,bp=await login(c.other)
                async def task(pg):
                    if await pg.locator('#detail').evaluate('(e)=>e.open'):await pg.locator('#close-detail').click()
                    await pg.locator('[data-panel=inbox]').click()
                    mine=pg.get_by_role('button',name='one atom · new/one',exact=True)
                    if await mine.count():await mine.click()
                    else:
                        await pg.locator('[data-panel=tasks]').click();await pg.locator('[data-view=all]').click();await pg.get_by_role('button',name='one atom',exact=True).first.click()
                    await pg.wait_for_selector('#task-convergence')
                async def fill(pg,values):
                    for name,value in values.items():
                        field=pg.locator('#detail [name="'+name+'"]')
                        if await field.evaluate('(e)=>e.tagName')=='SELECT':await field.select_option(str(value).lower() if isinstance(value,bool) else str(value))
                        else:await field.fill(str(value))
                async def save(pg,detail=True):
                    await pg.locator('#detail button[type=submit]').last.click()
                    if detail:await pg.wait_for_selector('#task-convergence');await pg.wait_for_function('() => !document.querySelector("#detail .resource-dialog form")')
                    else:await pg.wait_for_function('() => !document.querySelector("#detail").open')
                await task(bp);check(await bp.get_by_role('button',name='启用尝试与租约',exact=True).count()==0,'participant cannot grant policy')
                await bp.get_by_role('button',name='保存执行检查点',exact=True).click();check(not await bp.locator('#detail [name=attempt_lease]').is_visible(),'lease proof is filled and folded')
                await fill(bp,{'id':'ui-b-point','input_anchor':'git:'+'c'*40,'completed':'Bounded worker result','remaining':'Independent review','tests':'Current boundary inspected','obstacles':'Need fixed input','next_step':'Read SE response','recheck':'Scope and own active attempt','session':'fixture-b-session'});await save(bp)
                await bp.wait_for_function('() => document.querySelector("#task-continuation")?.textContent.includes("ui-b-point")');check('ui-b-point' in await bp.locator('#task-continuation').inner_text(),'different authorized participant saves own checkpoint')
                await bp.get_by_role('button',name='发起讨论 / 阻塞 / 偏离说明',exact=True).click();await fill(bp,{'id':'ui-b-block','kind':'blocker','title':'Participant input missing','body':'Need exact boundary before continuing','pause':True});await save(bp);check(c.co(c.other,'new/one')[1]['resume']['checkpoint']['id']=='ui-b-point','participant checkpoint survives collaboration')
                await task(page);await page.locator('[data-thread=ui-b-block]').get_by_role('button',name='SE记录决策',exact=True).click();await fill(page,{'summary':'Fixed input supplied within current scope'});await save(page)
                await bp.wait_for_function('() => document.querySelector("[data-thread=ui-b-block]")?.textContent.includes("待执行者确认")');await bp.locator('[data-thread=ui-b-block]').get_by_role('button',name='确认障碍已解决',exact=True).click();await fill(bp,{'summary':'Read SE decision and current fixed input'});await save(bp);check(c.call('/api/projects/alpha/workflow/task?task=new/one',profile=c.admin)[1]['threads']['ui-b-block']['status']=='resolved','participant acknowledges SE decision without taking ownership')
                await task(ap);await ap.get_by_role('button',name='批量声明验证结果',exact=True).click();await fill(ap,{'input_anchor':'git:'+'c'*40,'evidence':'fixture/ui.txt | '+'b'*64,'summary-A':'Observed behavior A','summary-B':'Observed boundary B'});await ap.locator('[data-batch-criterion=A]').check();await ap.locator('[data-batch-criterion=B]').check()
                captured=[]
                async def lost(route):
                    if route.request.method!='POST':await route.continue_();return
                    captured.append(route.request.post_data_json)
                    if len(captured)==1:await route.fetch();await route.abort('failed')
                    else:await route.continue_()
                await ap.route('**/api/projects/alpha/operations',lost);await ap.locator('#detail button[type=submit]').last.click();await ap.wait_for_function('() => document.querySelector("#detail .form-message").textContent.length>0');await save(ap);await ap.unroute('**/api/projects/alpha/operations',lost);check(len(captured)==2 and captured[0]==captured[1],'lost batch receipt replays exact request')
                await page.wait_for_selector('[data-criterion=A]');await page.get_by_role('button',name='批量审核所选标准',exact=True).click();await fill(page,{'summary-A':'SE inspected A on exact input','summary-B':'SE inspected B on exact input','evidence':'fixture/ui.txt | '+'b'*64});await page.locator('[data-batch-criterion=A]').check();await page.locator('[data-batch-criterion=B]').check();await save(page);check(len(c.call('/api/projects/alpha/workflow/task?task=new/one',profile=c.admin)[1]['verdicts'])==2,'batch keeps two explicit reviewed conclusions')
                await page.locator('#close-detail').click();await page.locator('[data-panel=relations]').click();await page.locator('[name=graph-mode]').select_option('condition');await page.wait_for_selector('[data-edge-type=condition]',state='attached');check(await page.locator('[data-edge-type=condition]').count()==1,'condition appears as distinct graph edge');await page.locator('[data-task="gate:external"]').click();await page.wait_for_selector('#task-convergence');check(True,'condition opens related task instead of fake task ID')
                await page.locator('#close-detail').click();await page.locator('[data-panel=planning]').click();await page.get_by_role('button',name='保存关联规划草案',exact=True).click();await fill(page,{'id':'lean-fields','title':'Guided original scope','reason':'Bounded integration only','evidence':'fixture/ui.txt | '+'b'*64});await page.get_by_role('button',name='加入一项',exact=True).click();await page.wait_for_selector('[data-path=id]')
                for key,value in {'id':'lean','title':'Lean module','goal':'Bounded usable result','scope':'Only local documentation','non_goals':'No interface or production changes'}.items():await page.locator('#detail [data-path="'+key+'"]').fill(value)
                check(not await page.locator('#detail [name=cv-payload-0]').is_visible(),'JSON is optional advanced view');await save(page,False);draft=c.cv()[1]['drafts']['lean-fields@1'];check(draft['items'][0]['payload']['id']=='lean','guided fields store real typed planning payload')
                await page.locator('[data-draft="lean-fields@1"]').get_by_role('button',name='预览并选择本批批准项',exact=True).click();await fill(page,{'approve_modules':'lean@1'});await save(page,False);await page.locator('[data-draft="lean-fields@1"]').get_by_role('button',name='批准并原子发布',exact=True).click();await fill(page,{'reason':'SE reviewed guided module boundaries','evidence':'fixture/ui.txt | '+'b'*64});await save(page,False);check(c.call('/api/projects/alpha/governance',profile=c.admin)[1]['module_readiness']['lean@1']['ready'],'guided module preview and approval use original validators')
                c.ok('intake_open',{'id':'guided-intake','kind':'improvement','title':'Bounded guided task','body':'Original scope follow-up','sources':[{'kind':'task','id':'new/one'}]});c.ok('intake_decide',{'id':'guided-intake','expected_version':1,'status':'approved','reason':'Finite fixture task','duplicate':'','tasks':[],'modules':[]})
                await page.locator('[data-panel=discovery]').click();await page.wait_for_selector('[data-intake=guided-intake]');await page.locator('[data-intake=guided-intake]').get_by_role('button',name='从需求建立任务',exact=True).click();await fill(page,{'reason':'Create bounded task from fields'})
                values={'id':'new/from-fields','title':'Guided task result','description':'Finite local document','deliverables':'D1 | Actual document','allowed_paths':'docs/','work.inputs':'fixture input','work.outputs':'fixture doc','work.baseline':'a'*40,'work.acceptance':'Actual bounded document','work.planning.module':'lean@1','work.planning.no_interface_reason':'No interface changes'}
                for key,value in values.items():await page.locator('#detail [data-path="'+key+'"]').fill(value)
                await page.locator('#detail [data-path="work.inputs_known"]').select_option('true');check(not await page.locator('#detail [name=spec]').is_visible(),'task conversion defaults to fields');await save(page,False);check(c.hub.store('alpha').get('new/from-fields')['status']=='planned','guided conversion creates bounded task without JSON')
                from tests.task_board import test_workflow as wf
                c.ok('rollback_plan',wf.WorkflowCase.rollback(c));c.ok('rollback_cancel',{'id':'restore','summary':'Fixture cancelled plan retained in history'})
                await page.locator('[data-panel=inbox]').click();await page.get_by_text('已结束回退历史',exact=True).wait_for();check(not await page.locator('[data-rollback=restore]').is_visible(),'completed rollback is folded history')
                for panel in ('inbox','relations','planning','task'):
                    if panel=='task':await task(page)
                    else:await page.locator('[data-panel='+panel+']').click()
                    for width in (1280,375):
                        for theme in ('light','dark'):
                            await page.set_viewport_size({'width':width,'height':960 if width==1280 else 812});await page.emulate_media(color_scheme=theme);await page.screenshot(path=str(E/f'{panel}-{width}-{theme}.png'),full_page=True);check(await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'{panel} {width}/{theme} fits')
                    if panel=='task':await page.locator('#close-detail').click()
                check((await worker.request.get(c.url+'/api/projects/beta/convergence')).status==404,'participant cannot cross project')
                c.member('same-agent','se');await ap.reload(wait_until='networkidle');await task(ap);await ap.wait_for_selector('#task-continuation');check(await ap.get_by_role('button',name='提交实施计划',exact=True).count()==1,'SE task owner sees exactly one implementation-plan action')
                check(not report['errors'],'no JavaScript errors');report['passed']=True;capture()
                for ctx in contexts:await ctx.close()
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
