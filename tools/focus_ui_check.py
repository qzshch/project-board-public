"""Real HTTP/browser verification of the four bounded focus changes."""
import asyncio,json,os,subprocess,sys,tempfile,time
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.task_board.test_focus import FocusCase
from tools.owned_process import remove_owned_tree
from task_board import lifecycle
from playwright.async_api import async_playwright
E=ROOT/'evidence/focus-ui'/time.strftime('%Y%m%d-%H%M%S');E.mkdir(parents=True)
T=E/'temporary';T.mkdir();os.environ.update(TMP=str(T),TEMP=str(T),TMPDIR=str(T),PROJECT_BOARD_TEST_ROOT=str(E/'fixtures'));tempfile.tempdir=str(T)
report={'passed':False,'checks':[],'errors':[],'processes':[],'screens':[],'isolated_fixture':True}
def check(value,label):
    assert value,label
    report['checks'].append(label)
def capture():
    for p in psutil.Process().children(recursive=True):
        try:report['processes'].append({'pid':p.pid,'created':p.create_time(),'command':p.cmdline(),'purpose':'Owned headless focus UI fixture'})
        except psutil.NoSuchProcess:pass
async def main():
    c=FocusCase();c.setUp();page=None;original=asyncio.create_subprocess_exec
    async def hidden(*args,**kwargs):
        if os.name=='nt':kwargs['creationflags']=kwargs.get('creationflags',0)|subprocess.CREATE_NO_WINDOW
        return await original(*args,**kwargs)
    try:
        c.claimed();c.op('criteria_plan',c.plan());c.discussion('old');c.discussion('current')
        c.gov('knowledge',{'background':'背景与旧进展；'*120,'goals':'当前目标','non_goals':'范围以外','constraints':'执行约束必须完整保留','materials':[],'entries':[]})
        c.gov('resource_register',c.payload(information_role='snapshot',title='旧轮次状态报告'))
        asyncio.create_subprocess_exec=hidden
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--disable-gpu','--no-first-run'])
            try:
                capture();ctx=await browser.new_context(viewport={'width':1440,'height':960});page=await ctx.new_page();page.on('pageerror',lambda e:report['errors'].append(str(e)))
                ticket=c.hub.admin_store.create_ticket(c.hub.admin_store.authenticate(c.admin['token']));await ctx.request.post(c.url+'/api/session',data={'ticket':ticket});await page.goto(c.url+'/?project=alpha',wait_until='networkidle');await page.wait_for_selector('#current-state .workspace-grid')
                check('实时权威记录' in await page.locator('#current-state').inner_text(),'overview reads real project current endpoint')
                check(not await page.locator('[data-project-definition=full]').evaluate('(e)=>e.open') and '执行约束必须完整保留' in await page.locator('[data-project-definition=full]').text_content(),'long project definition folded with complete constraints retained')
                check(not await page.locator('#workspace-body details').first.evaluate('(e)=>e.open'),'project references folded by default')
                await page.evaluate("setView('active')");check(await page.locator('#task-list').get_by_role('button',name='alpha private task',exact=True).count()==0,'legacy planned structure excluded from current execution')
                await page.select_option('#record-view','structure');check(await page.locator('#task-list').get_by_role('button',name='alpha private task',exact=True).count()==1,'historical task remains available through explicit view')
                await page.evaluate("selectWorkspacePanel('assets')");await page.wait_for_selector('[name=resource-view]');check(await page.locator('[data-resource=research]').count()==0,'snapshot excluded from common references')
                await page.select_option('[name=resource-view]','history');await page.wait_for_selector('[data-resource=research]');check('历史快照' in await page.locator('[data-resource=research]').inner_text(),'snapshot explicitly labelled without claiming live state')
                await page.evaluate("selectWorkspacePanel('inbox')");await page.wait_for_selector('[data-inbox-group]');check(await page.locator('[data-inbox-group]').count()==1,'same-task reminders grouped into one current action')
                await page.evaluate("showDetail('new/one')");await page.wait_for_selector('[data-thread=old]');old=page.locator('[data-thread=old]');await old.get_by_text('此提醒已由其他讨论接续',exact=True).click();await old.get_by_role('button',name='确认接续依据',exact=True).click()
                await page.locator('#detail [name=summary]').fill('旧提醒由新讨论接续，同一问题不重复等待');await page.locator('#detail button[type=submit]').click();await page.wait_for_selector('[data-thread=current]');check(c.call('/api/projects/alpha/workflow',profile=c.admin)[1]['threads']['old']['superseded_by']=='current','SE discussion succession saved through actual form');await page.locator('#close-detail').click()
                actor=c.hub.store('alpha').authenticate(c.a['token']);ticket=c.hub.store('alpha').create_ticket(actor,allow_agent=True);wc=await browser.new_context(viewport={'width':1440,'height':960});worker=await wc.new_page();worker.on('pageerror',lambda e:report['errors'].append(str(e)));await worker.goto(c.url+'/?project=alpha&panel=tasks#access='+ticket,wait_until='networkidle');await worker.evaluate("showDetail('new/one')");await worker.wait_for_selector('#candidate-delivery')
                for name,value in {'summary':'限定成果及结论；工作记录见原件','implementation_commit':'c'*40,'tests':'真实fixture手工检查已通过','verification_reason':'范围明确，检查固定输入','evidence':'检查记录 | fixture/actual-review.txt | '+'b'*64,'remaining':'无'}.items():await worker.locator('#candidate-delivery [name='+name+']').fill(value)
                await worker.locator('#candidate-delivery input[type=checkbox]').check();await worker.select_option('#candidate-delivery [name=completeness]','full');await worker.select_option('#candidate-delivery [name=verification_status]','passed');await worker.locator('#candidate-delivery button[type=submit]').click();await worker.wait_for_function("() => document.querySelector('#detail-body').innerText.includes('候选成果已进入待评审队列')")
                task=c.hub.store('alpha').get('new/one');check(task['status']=='submitted','worker submits candidate before any SE criteria review');check(not c.call('/api/projects/alpha/workflow/task?task=new/one',profile=c.a)[1]['delivery_readiness']['ready_for_acceptance'],'missing criteria still blocks acceptance')
                await worker.locator('#close-detail').click();await worker.evaluate("selectWorkspacePanel('overview')");await worker.wait_for_selector('#current-state .workspace-grid')
                for width in (1440,390):
                    for theme in ('light','dark'):
                        await worker.set_viewport_size({'width':width,'height':960});await worker.evaluate('(v)=>{currentTheme=v;applyTheme();}',theme);await worker.wait_for_selector('#current-state .workspace-grid');await worker.wait_for_timeout(120)
                        check(await worker.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),f'{width} {theme} has no horizontal overflow')
                        file=E/f'overview-{width}-{theme}.png';await worker.screenshot(path=str(file),full_page=True);report['screens'].append(str(file))
                        await worker.evaluate("showDetail('new/one')");await worker.wait_for_selector('[data-thread=current]');file=E/f'task-{width}-{theme}.png';await worker.screenshot(path=str(file),full_page=True);report['screens'].append(str(file));check(await worker.locator('[data-thread=old]').evaluate('(e)=>e.closest("details").open') is False,f'{width} {theme} superseded thread folded as history');await worker.locator('#close-detail').click()
                await worker.locator('#theme-toggle').focus();await worker.keyboard.press('Tab');check(await worker.evaluate('document.activeElement!==document.body'),'keyboard navigation reachable');check(not report['errors'],'no browser runtime errors');report['passed']=True
            finally:await browser.close()
    except BaseException:
        if page:
            try:await page.screenshot(path=str(E/'FAILURE.png'),full_page=True)
            except Exception:pass
        raise
    finally:
        asyncio.create_subprocess_exec=original;c.tearDown();lifecycle.write(E/'RESULT.json',report);remove_owned_tree(T,E)
if __name__=='__main__':
    asyncio.run(main());print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'evidence':str(E)}))
