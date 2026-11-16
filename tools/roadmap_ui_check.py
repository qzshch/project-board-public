"""Real project-backed stage, priority and nested function-tree UI verification."""
import asyncio,json,os,subprocess,sys,tempfile,time,hashlib
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.task_board.test_roadmap import RoadmapCase
from tools.owned_process import remove_owned_tree
from task_board import lifecycle
from playwright.async_api import async_playwright
E=ROOT/'evidence/roadmap-ui'/time.strftime('%Y%m%d-%H%M%S');E.mkdir(parents=True)
T=E/'temporary';T.mkdir();os.environ.update(TMP=str(T),TEMP=str(T),TMPDIR=str(T),PROJECT_BOARD_TEST_ROOT=str(E/'fixtures'));tempfile.tempdir=str(T)
report={'passed':False,'checks':[],'errors':[],'processes':[],'screens':[],'isolated_fixture':True}
def sources():return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ['task_board','task_board_web','tests','tools'] for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
report['sources']=sources()
def check(v,label):
    assert v,label
    report['checks'].append(label)
async def main():
    c=RoadmapCase();c.setUp();page=None;original=asyncio.create_subprocess_exec
    async def hidden(*args,**kwargs):
        if os.name=='nt':kwargs['creationflags']=kwargs.get('creationflags',0)|subprocess.CREATE_NO_WINDOW
        return await original(*args,**kwargs)
    try:
        c.claimed();c.charter();c.gov('module_plan',c.module());c.review();c.atomic('extension/free',['extension/']);c.stage();c.gov('stage_focus',{'ref':'minimum@1','reason':'Core priority, independent work remains available'})
        p=c.tree();p['nodes'][1]['module_ids']=['core'];p['nodes'].append({'id':'extensions','title':'Independent extensions','parent':'product','description':'No implicit minimum dependency','module_ids':[],'task_ids':['extension/free']});c.gov('function_tree',p)
        before=c.hub.store('alpha').get('new/one');asyncio.create_subprocess_exec=hidden
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--disable-gpu','--no-first-run'])
            try:
                for proc in psutil.Process().children(recursive=True):
                    try:report['processes'].append({'pid':proc.pid,'created':proc.create_time(),'command':proc.cmdline(),'purpose':'Owned roadmap browser fixture'})
                    except psutil.NoSuchProcess:pass
                ctx=await browser.new_context(viewport={'width':1440,'height':960});page=await ctx.new_page();page.on('pageerror',lambda e:report['errors'].append(str(e)))
                ticket=c.hub.admin_store.create_ticket(c.hub.admin_store.authenticate(c.admin['token']));await ctx.request.post(c.url+'/api/session',data={'ticket':ticket});await page.goto(c.url+'/?project=alpha',wait_until='networkidle');await page.wait_for_selector('#project-stage-summary')
                check('Minimum usable result' in await page.locator('#project-stage-summary').inner_text(),'overview leads with actual current product goal')
                check('尚有交付条件待完成' in await page.locator('#project-stage-summary').inner_text(),'unfinished phase never inferred passed from historical records')
                await page.evaluate("selectWorkspacePanel('planning')");await page.wait_for_selector('#product-function-tree [data-function-node=function]')
                check(await page.locator('[data-function-node=function]').evaluate('(e)=>e.parentElement.closest("[data-function-node]").dataset.functionNode')=='product','function hierarchy genuinely nests child under parent')
                check(not await page.locator('#technical-planning').evaluate('(e)=>e.open'),'technical details retained but folded behind product view')
                check(await page.locator('#workspace-body').evaluate('(e)=>e.firstElementChild.id')=='project-stage-plans','stage goals precede technical draft tools')
                await page.locator('[data-function-node=function] > summary').click();c.gov('stage_focus',{'ref':'minimum@1','reason':'Fresh unrelated planning update'});await page.evaluate('refreshWorkspace(app.generation)');check(await page.locator('[data-function-node=function]').evaluate('(e)=>e.open'),'expanded function path survives live planning refresh')
                await page.get_by_role('button',name='编辑功能树',exact=True).click();await page.locator('#detail details').nth(1).locator('summary').click();await page.locator('#detail [name=title-1]').fill('Renamed capability');await page.locator('#detail [name=reason]').fill('Presentation-only classification refinement');await page.locator('#detail button[type=submit]').click();await page.wait_for_function("() => !document.querySelector('#detail').open")
                check(c.hub.store('alpha').get('new/one')==before,'real tree edit preserves task ID, scope, status and acceptance object')
                check(c.snap()['module_readiness']['core@1']['review_current'],'tree edit does not invalidate module approval')
                await page.get_by_role('button',name='新增阶段目标',exact=True).click()
                for key,value in {'id':'extension','title':'Independent expansion','goal':'Separate bounded feature','scope':'Only extension/free','non_goals':'Other features','reason':'Independent backlog item remains schedulable','criteria':'X | Actual extension scenario'}.items():await page.locator('#detail [name='+key+']').fill(value)
                await page.get_by_role('button',name='关联已有任务',exact=True).click();await page.select_option('#detail [name=task]','extension/free');await page.locator('#detail button[type=submit]').click();await page.wait_for_function("() => !document.querySelector('#detail').open")
                check('extension' in c.roadmap()['heads'],'phase field editor saves immutable plan with existing task association')
                actor=c.hub.store('alpha').authenticate(c.a['token']);ticket=c.hub.store('alpha').create_ticket(actor,allow_agent=True);wc=await browser.new_context(viewport={'width':1280,'height':960});worker=await wc.new_page();worker.on('pageerror',lambda e:report['errors'].append(str(e)));await worker.goto(c.url+'/?project=alpha&panel=tasks#access='+ticket,wait_until='networkidle');await worker.evaluate("showDetail('extension/free')");await worker.get_by_role('button',name='认领此任务',exact=True).click();await worker.wait_for_function("() => document.querySelector('#detail-body').innerText.includes('提交候选成果')")
                check(c.hub.store('alpha').get('extension/free')['status']=='active' and not c.roadmap()['stages']['minimum@1']['state']['passed'],'worker actually claims independent extension while minimum phase is unfinished')
                c.accepted();await page.locator('[data-product-stage="minimum@1"] > summary').click();await page.get_by_role('button',name='逐项核对阶段验收',exact=True).first.click();await page.select_option('#detail [name=check-PLAY]','pass');await page.locator('#detail [name=summary-PLAY]').fill('Actual fixed fixture end-to-end and restart evidence inspected');await page.select_option('#detail [name=result]','pass');await page.locator('#detail [name=summary]').fill('All minimum-scenario checks verified for this fixed artifact');await page.locator('#detail [name=evidence]').fill('fixture/review.txt | '+'b'*64);await page.locator('#detail button[type=submit]').click();await page.wait_for_function("() => !document.querySelector('#detail').open")
                check(c.roadmap()['stages']['minimum@1']['state']['passed'],'stage review saved through actual per-criterion form and fixed evidence')
                search=page.get_by_role('searchbox',name='搜索功能树');await search.fill('extension/free');check(await page.locator('[data-function-node=extensions]').evaluate('(e)=>e.open'),'task search expands matching product path');await search.fill('')
                for width in (1440,390):
                    for theme in ('light','dark'):
                        await page.set_viewport_size({'width':width,'height':960});await page.evaluate('(v)=>{currentTheme=v;applyTheme();}',theme);await page.wait_for_selector('#product-function-tree');check(await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),f'{width} {theme} product planning has no overflow')
                        await page.evaluate('scrollTo(0,0)');file=E/f'planning-{width}-{theme}.png';await page.screenshot(path=str(file),full_page=True);report['screens'].append(str(file))
                        await page.evaluate("selectWorkspacePanel('overview')");await page.wait_for_selector('#project-stage-summary');await page.evaluate('scrollTo(0,0)');file=E/f'overview-{width}-{theme}.png';await page.screenshot(path=str(file),full_page=True);report['screens'].append(str(file));await page.evaluate("selectWorkspacePanel('planning')")
                await page.locator('#theme-toggle').focus();await page.keyboard.press('Tab');check(await page.evaluate('document.activeElement!==document.body'),'keyboard navigation remains reachable');check(not report['errors'],'no browser runtime errors');check(sources()==report['sources'],'same source bytes throughout roadmap UI verification');report['passed']=True
            finally:await browser.close()
    except BaseException:
        if page:
            try:await page.screenshot(path=str(E/'FAILURE.png'),full_page=True)
            except Exception:pass
        raise
    finally:
        asyncio.create_subprocess_exec=original;c.tearDown();lifecycle.write(E/'RESULT.json',report);remove_owned_tree(T,E)
if __name__=='__main__':asyncio.run(main());print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'evidence':str(E)}))
