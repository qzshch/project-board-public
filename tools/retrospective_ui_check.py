"""Actual Worker draft/SE review UI and Antigravity binding over isolated HTTP."""
import asyncio,hashlib,json,os,secrets,subprocess,sys,tempfile,time
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.task_board.test_retrospective import RetrospectiveCase
from tools.owned_process import remove_owned_tree
from playwright.async_api import async_playwright
E=ROOT/'evidence/retrospective-ui'/time.strftime('%Y%m%d-%H%M%S');E.mkdir(parents=True);T=E/'temporary';T.mkdir()
os.environ.update(TMP=str(T),TEMP=str(T),TMPDIR=str(T),PROJECT_BOARD_TEST_ROOT=str(T/'fixtures'));tempfile.tempdir=str(T)
report={'passed':False,'checks':[],'errors':[],'screens':[],'processes':[],'isolated_fixture':True}
report['sources']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('task_board','task_board_web','tools','tests') for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
def check(value,label):
    assert value,label
    report['checks'].append(label)
async def main():
    c=RetrospectiveCase();c.setUp();original=asyncio.create_subprocess_exec
    async def hidden(*args,**kw):
        if os.name=='nt':kw['creationflags']=kw.get('creationflags',0)|subprocess.CREATE_NO_WINDOW
        return await original(*args,**kw)
    try:
        draft=c.draft();package=T/'package.json';package.write_text(json.dumps({'project_id':'alpha','draft':draft}),'utf8');asyncio.create_subprocess_exec=hidden
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--disable-gpu','--no-first-run'])
            try:
                for proc in psutil.Process().children(recursive=True):
                    try:report['processes'].append({'pid':proc.pid,'created':proc.create_time(),'command':proc.cmdline(),'purpose':'Owned hidden retrospective browser fixture'})
                    except psutil.NoSuchProcess:pass
                async def login(profile):
                    ctx=await browser.new_context(viewport={'width':1440,'height':960});ticket=c.call('/api/projects/alpha/access',{},profile)[1]['ticket'];r=await ctx.request.post(c.url+'/api/projects/alpha/session',data={'ticket':ticket});check(r.ok,'project-scoped browser session accepted');return ctx
                worker=await login(c.a);page=await worker.new_page();page.on('pageerror',lambda e:report['errors'].append(str(e)))
                await page.goto(c.url+'/?project=alpha&panel=time',wait_until='networkidle');await page.get_by_role('button',name='提交整理草案',exact=True).click();await page.locator('#detail input[type=file]').set_input_files(str(package));await page.get_by_role('button',name='提交待SE核定',exact=True).click();await page.wait_for_function('()=>!document.querySelector("#detail").open');await page.wait_for_selector('[data-retrospective=archive-one]')
                row=page.locator('[data-retrospective=archive-one]');await row.locator('summary').click();check(await row.get_by_role('button',name='核对并纳入统计').count()==0,'Worker cannot self approve');check(c.usage()['revision']==0,'pending browser draft does not change usage')
                se=await login(c.reviewer);sp=await se.new_page();sp.on('pageerror',lambda e:report['errors'].append(str(e)));await sp.goto(c.url+'/?project=alpha&panel=inbox',wait_until='networkidle');await sp.wait_for_selector('[data-inbox=retrospective]',state='attached');check(True,'SE existing workbench shows one current archive review')
                await sp.goto(c.url+'/?project=alpha&panel=time',wait_until='networkidle');await sp.locator('[data-retrospective=archive-one] summary').click();await sp.get_by_role('button',name='核对并纳入统计',exact=True).click();await sp.locator('#detail input[name=reason]').fill('Checked isolated source metadata, native session, effective work and non-overlap');await sp.get_by_role('button',name='确认本版本补录',exact=True).click();await sp.wait_for_function('()=>!document.querySelector("#detail").open');check(c.usage()['revision']==1,'SE browser review appends exactly one original ledger sample')
                for width,theme in [(1440,'light'),(1440,'dark'),(390,'light'),(390,'dark')]:
                    await sp.set_viewport_size({'width':width,'height':960});await sp.evaluate('(v)=>{currentTheme=v;applyTheme();}',theme);await sp.locator('[data-retrospective=archive-one]').evaluate('(e)=>e.open=true');f=E/f'time-{width}-{theme}.png';await sp.screenshot(path=str(f),full_page=True);report['screens'].append(str(f));report['overflow']=await sp.evaluate('Array.from(document.querySelectorAll("#workspace-body *")).filter(e=>e.getBoundingClientRect().right>innerWidth+1).slice(0,12).map(e=>({tag:e.tagName,cls:e.className,width:e.getBoundingClientRect().width,text:e.textContent.slice(0,80)}))');check(await sp.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),f'{width} {theme} no horizontal overflow')
                await sp.set_viewport_size({'width':1440,'height':960});await sp.goto(c.url+'/?project=alpha&panel=assets',wait_until='networkidle');await sp.locator('[name=resource-view]').select_option('history');await sp.locator('[name=resource-origin]').select_option('retrospective');await sp.wait_for_selector('[data-resource^=retro-]');check(True,'approved archive is discoverable through existing project assets')
                check((await se.request.get(c.url+'/retrospective-kit.zip')).ok,'separate retrospective toolkit downloads');check((await se.request.get(c.url+'/help/retrospective')).ok,'public worker guide reachable')
                pair=c.call('/api/nodes/pair',{'id':'fixture-agy','name':'Arbitrary Tailscale node','projects':['alpha']},c.admin)[1];node={'token':'node.'+secrets.token_urlsafe(40)};check(c.call('/api/node/enroll',{'id':'fixture-agy','pair':pair['pair']},node)[0]==201,'isolated arbitrary node can enroll')
                check(c.call('/api/node/heartbeat',{'capabilities':{'antigravity':{'ready':True,'version':'isolated fixture ACP1','models':['actual-route'],'roots':{'alpha':['workspace']},'reason':'Protocol fixture, no inference claim'}}},node)[0]==200,'Antigravity capability accepted by real server')
                await sp.goto(c.url+'/?project=alpha&panel=agents',wait_until='networkidle');await sp.locator('[name=runtime]').wait_for();check(await sp.locator('[name=runtime]').input_value()=='antigravity','UI offers Antigravity from node capabilities');await sp.locator('[name=role]').select_option('se');check(await sp.locator('select[name=task]').first.is_disabled(),'SE role has no Worker task assignment');await sp.get_by_role('button',name='创建并派发',exact=True).click();await sp.wait_for_function('()=>document.querySelector("#workspace-body").textContent.includes("实际创建与首条输入有独立回执")');check(True,'SE can queue Antigravity SE binding without global profile')
                check(not report['errors'],'no browser runtime errors');report['passed']=True
            finally:await browser.close()
    finally:
        asyncio.create_subprocess_exec=original;c.tearDown();(E/'RESULT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8');remove_owned_tree(T,E)
if __name__=='__main__':
    asyncio.run(main());print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'evidence':str(E)}))
