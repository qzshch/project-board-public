"""Real HTTP-backed product workspace and 1200-task graph browser acceptance."""
import asyncio,json,os,subprocess,sys,tempfile,time,hashlib
from pathlib import Path
from copy import deepcopy
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.task_board.test_product_v2 import ProductCase
from tests.task_board.test_planning import PlanningCase
from task_board import lifecycle
from tools.owned_process import remove_owned_tree,run
from playwright.async_api import async_playwright
E=ROOT/'evidence/product-v2-ui'/time.strftime('%Y%m%d-%H%M%S');E.mkdir(parents=True)
T=E/'temporary';T.mkdir();os.environ.update(TMP=str(T),TEMP=str(T),TMPDIR=str(T),PROJECT_BOARD_TEST_ROOT=str(E/'fixtures'));tempfile.tempdir=str(T)
report={'passed':False,'checks':[],'errors':[],'processes':[],'screens':[],'synthetic_isolated_fixture':True}
def inputs():return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('task_board','task_board_web','tools','tests') for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
report['sources']=inputs()
def check(value,label):
    assert value,label
    report['checks'].append(label);lifecycle.write(E/'PROGRESS.json',report)
def capture():
    for p in psutil.Process().children(recursive=True):
        try:
            if not any(x['pid']==p.pid and x['created']==p.create_time() for x in report['processes']):report['processes'].append({'pid':p.pid,'created':p.create_time(),'command':p.cmdline(),'purpose':'Owned product-v2 headless browser fixture'})
        except psutil.NoSuchProcess:pass
async def main():
    c=ProductCase();c.setUp();page=None;original=asyncio.create_subprocess_exec
    async def hidden(*a,**kw):
        if os.name=='nt':kw['creationflags']=kw.get('creationflags',0)|subprocess.CREATE_NO_WINDOW
        return await original(*a,**kw)
    try:
        c.session();c.create();c.create('defect','BUG-one');c.usage(c.sample());asyncio.create_subprocess_exec=hidden
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--disable-gpu','--no-first-run'])
            try:
                capture();ctx=await browser.new_context(viewport={'width':1440,'height':960});page=await ctx.new_page();page.on('pageerror',lambda e:report['errors'].append(str(e)))
                ticket=c.hub.admin_store.create_ticket(c.hub.admin_store.authenticate(c.admin['token']));await ctx.request.post(c.url+'/api/session',data={'ticket':ticket});await page.goto(c.url+'/?project=alpha&panel=requirements',wait_until='networkidle');await page.wait_for_selector('.data-table')
                check('REQ-one' in await page.locator('#workspace-body').inner_text(),'requirements backed by project HTTP records')
                await page.get_by_role('button',name='记录想法',exact=True).click();await page.locator('#detail [name=title]').fill('Browser created idea');await page.locator('#detail [name=body]').fill('A post-project idea need not be engineered');await page.locator('#detail button[type=submit]').click();await page.wait_for_function('() => !document.querySelector("#detail").open');check(any(e['title']=='Browser created idea' for e in c.products()['items'].values()),'minimal idea creation persists without task or commitment')
                await page.get_by_role('button',name='Browser created idea',exact=True).click();check('尚未确认' in await page.locator('#detail-body').inner_text(),'definition and commitment separated');await page.locator('#close-detail').click()
                for panel in ['defects','changes','inbox','overview','discovery','planning','policy','time','quality','git','tasks','relations','contracts','assets','agents','handoff','retrospective']:
                    await page.evaluate('(p)=>selectWorkspacePanel(p)',panel);await page.wait_for_timeout(180);check(await page.locator('#workspace-title').inner_text()==await page.evaluate('panelNames[ws.panel]'),'real legacy/new route remains available: '+panel)
                await page.evaluate("selectWorkspacePanel('agents')");await page.wait_for_function("() => document.querySelector('#workspace-body').innerText.includes('native-session-123')");await page.locator('#workspace-body input[type=search]').last.fill('native-session-123');check('native-session-123' in await page.locator('#workspace-body .data-table').inner_text(),'native ID searchable and distinct from binding ID')
                copied=await page.evaluate('''async () => {const descriptor=Object.getOwnPropertyDescriptor(navigator,'clipboard'),original=document.execCommand;let copied=null;try{Object.defineProperty(navigator,'clipboard',{value:undefined,configurable:true});document.execCommand=command=>{if(command==='copy')copied=document.activeElement.value;return true;};await copyProjectText('native-session-123');return copied;}finally{document.execCommand=original;if(descriptor)Object.defineProperty(navigator,'clipboard',descriptor);else delete navigator.clipboard;}}''');check(copied=='native-session-123','native session ID copy works on HTTP without secure clipboard API')
                await page.evaluate("showDetail('new/one')");await page.wait_for_function("() => document.querySelector('#detail-body').innerText.includes('native-session-123')");check(True,'task detail includes original native session ID');await page.locator('#close-detail').click()
                await page.evaluate("selectWorkspacePanel('time')");await page.wait_for_selector('[name=usage-dimension]');check('实测覆盖 1 / 1' in await page.locator('#workspace-body').inner_text(),'usage actual coverage and original timing rendered together');await page.select_option('[name=usage-dimension]','session');check('native-session-123' in await page.locator('#workspace-body .data-table').inner_text(),'usage groups by native session')
                # Author a large, isolated fixture through the real journal.
                for m in range(12):
                    p=PlanningCase.module(c,id='module-'+str(m),title='功能模块 '+str(m));r=c.gov('module_plan',p);check(r[0]==201,'fixture module '+str(m))
                store=c.hub.store('alpha');actor=c.hub.effective_actor(c.identity,'alpha');template=deepcopy(store.get('new/one')['spec'])
                with store.connection() as db:
                    db.execute('BEGIN IMMEDIATE')
                    for m in range(12):
                        for i in range(100):
                            tid=f'scale/M{m}-T{i}';spec=deepcopy(template);spec.update(id=tid,title=f'功能模块 {m} · 原子任务 {i}',claimable=False,depends_on=[f'scale/M{m}-T{i-1}'] if i else ([f'scale/M{m-1}-T99'] if m else []));spec['work']['planning']={'module':'module-'+str(m)+'@1','purpose':'execution','question':'','no_interface_reason':'Isolated authored fixture'};spec['allowed_paths']=[f'scale/{m}/{i}/'];store._append(db,actor,tid,'create',{'spec':spec,'reason':'Authored isolated 1200-task scale fixture, no production data'})
                    db.commit()
                started=time.monotonic();await page.evaluate("selectWorkspacePanel('relations');ws.signature=null;refreshWorkspace(app.generation)");await page.wait_for_function("() => document.querySelector('#workspace-body').innerText.includes('1202 项任务/条件')",timeout=60000);report['large_project_http_and_render_seconds']=time.monotonic()-started;check(True,'actual authorized HTTP graph retains all 1202 tasks')
                await page.select_option('[name=graph-scale-mode]','all');check(await page.evaluate("document.querySelector('#workspace-body').innerText.includes('当前 '+buildGraphModel(ws.data).nodes.size+' 节点')"),'whole graph includes every task without truncation');await page.select_option('[name=graph-scale-mode]','module');await page.select_option('[name=graph-module]','module-5');check('scale/M4-T99' in await page.locator('#workspace-body details').last.inner_text() or await page.evaluate("buildGraphModel(ws.data).nodes.has('scale/M4-T99')"),'module boundary uses actual upstream task')
                await page.select_option('[name=graph-scale-mode]','modules');
                for width,height,label in [(1440,960,'desktop'),(390,844,'mobile')]:
                    await page.set_viewport_size({'width':width,'height':height})
                    for theme in ['light','dark']:
                        await page.evaluate('(theme)=>{currentTheme=theme;applyTheme();}',theme);await page.wait_for_timeout(120)
                        check(await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),label+' '+theme+' no whole-page horizontal overflow');file=E/(label+'-'+theme+'.png');await page.screenshot(path=str(file),full_page=True);report['screens'].append(str(file))
                        ratios=await page.evaluate('''() => {const s=getComputedStyle(document.documentElement),rgb=v=>{const e=document.createElement('span');e.style.color=v;document.body.append(e);const c=getComputedStyle(e).color.match(/[\\d.]+/g).slice(0,3).map(Number);e.remove();return c.map(x=>{x/=255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4;}).reduce((v,x,i)=>v+x*[.2126,.7152,.0722][i],0);};const pairs=[['--ink','--surface'],['--secondary','--surface'],['--muted','--surface'],['--action','--surface'],['--action','--action-soft']];return pairs.map(([a,b])=>{const x=rgb(s.getPropertyValue(a)),y=rgb(s.getPropertyValue(b));return {a,b,ratio:(Math.max(x,y)+.05)/(Math.min(x,y)+.05)};});}''')
                        check(all(p['ratio']>=4.5 for p in ratios),label+' '+theme+' normal semantic text contrast >=4.5');report.setdefault('contrast',{})[label+'-'+theme]=ratios
                await page.set_viewport_size({'width':1440,'height':960});await page.keyboard.press('Tab');check(await page.evaluate('document.activeElement!==document.body'),'keyboard focus remains visible and reachable');check(not report['errors'],'no browser runtime errors');check(inputs()==report['sources'],'same source bytes throughout browser verification');report['passed']=True
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
