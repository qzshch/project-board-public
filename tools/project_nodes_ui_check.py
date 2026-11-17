"""Ordinary project SE authorizes/retries/revokes a node through actual HTTP UI."""
import asyncio,hashlib,json,os,subprocess,sys,tempfile,time
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.task_board.test_project_nodes import ProjectNodeCase
from tools.owned_process import remove_owned_tree
from playwright.async_api import async_playwright
E=ROOT/'evidence/project-nodes-ui'/time.strftime('%Y%m%d-%H%M%S');E.mkdir(parents=True);T=E/'temporary';T.mkdir()
os.environ.update(TMP=str(T),TEMP=str(T),TMPDIR=str(T),PROJECT_BOARD_TEST_ROOT=str(T/'fixtures'));tempfile.tempdir=str(T)
report={'passed':False,'checks':[],'errors':[],'screens':[],'processes':[],'isolated_fixture':True}
report['sources']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('task_board','task_board_web','tools','tests') for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
def check(value,label):
    assert value,label
    report['checks'].append(label)
async def main():
    c=ProjectNodeCase();c.setUp();original=asyncio.create_subprocess_exec
    async def hidden(*args,**kw):
        if os.name=='nt':kw['creationflags']=kw.get('creationflags',0)|subprocess.CREATE_NO_WINDOW
        return await original(*args,**kw)
    try:
        asyncio.create_subprocess_exec=hidden
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--disable-gpu','--no-first-run'])
            try:
                for proc in psutil.Process().children(recursive=True):
                    try:report['processes'].append({'pid':proc.pid,'created':proc.create_time(),'command':proc.cmdline(),'purpose':'Owned SE node bootstrap browser fixture'})
                    except psutil.NoSuchProcess:pass
                ctx=await browser.new_context(viewport={'width':1440,'height':960});page=await ctx.new_page();page.on('pageerror',lambda error:report['errors'].append(str(error)))
                ticket=c.call('/api/projects/alpha/access',{},c.reviewer)[1]['ticket'];await ctx.request.post(c.url+'/api/projects/alpha/session',data={'ticket':ticket})
                await page.goto(c.url+'/?project=alpha&panel=agents',wait_until='networkidle');await page.wait_for_selector('[data-project-node-pair=true]')
                check(await page.evaluate("app.role==='reviewer'&&!app.admin"),'ordinary project SE has no instance administrator authority')
                form=page.locator('[data-project-node-pair=true]');await form.locator('summary').click();await form.locator('[name=alias]').fill('local-se');await form.locator('[name=name]').fill('authorized-tailnet-host');await form.locator('[name=roles]').select_option('both')
                async with page.expect_download() as download:await form.get_by_role('button',name='生成本项目接入文件',exact=True).click()
                saved=T/'private-node-pair.json';await (await download.value).save_as(str(saved));pair=json.loads(saved.read_text('utf8'))
                check(pair['projects']==['alpha'] and set(pair['roles'])=={'se','worker'},'SE grant contains only own project and explicit SE/Worker roles')
                check(pair['id'].startswith('pn-'),'download carries actual project-namespaced stable ID')
                async with page.expect_download() as repeated:await form.get_by_role('button',name='生成本项目接入文件',exact=True).click()
                second=T/'private-node-pair-retry.json';await (await repeated.value).save_as(str(second));check(json.loads(second.read_text('utf8'))['pair']==pair['pair'],'UI retries exact frozen grant without rotating private pair')
                for width,theme in [(1440,'light'),(1440,'dark'),(390,'light'),(390,'dark')]:
                    await page.set_viewport_size({'width':width,'height':960});await page.evaluate('(v)=>{currentTheme=v;applyTheme();}',theme);check(await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),f'SE node form {width} {theme} no overflow');image=E/f'{width}-{theme}.png';await page.screenshot(path=str(image),full_page=True);report['screens'].append(str(image))
                await page.set_viewport_size({'width':1440,'height':960});await page.get_by_role('button',name='刷新接入状态',exact=True).click();revoke=page.locator('details').filter(has=page.locator('summary',has_text='撤销项目接入端 '+pair['id']));await revoke.locator('summary').click();await revoke.locator('[name=reason]').fill('SE retires own isolated project endpoint');await revoke.get_by_role('button',name='撤销本项目接入端',exact=True).click();await page.wait_for_function('()=>document.querySelector("#workspace-body").textContent.includes("已撤销控制面")')
                check(c.call('/api/projects/alpha/nodes',profile=c.reviewer)[1]['nodes'][0]['enabled']==False,'SE can revoke own node through actual browser')
                check((await ctx.request.get(c.url+'/api/projects/beta/nodes')).status==404,'SE browser cannot enumerate another project nodes')
                check(not report['errors'],'no browser runtime errors');report['passed']=True
            finally:await browser.close()
    finally:
        asyncio.create_subprocess_exec=original;c.tearDown();(E/'RESULT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8');remove_owned_tree(T,E)
if __name__=='__main__':
    asyncio.run(main());print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'evidence':str(E)}))
