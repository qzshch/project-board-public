"""Isolated real Git graph, UI workflows, data boundary and role rendering."""
import asyncio,json,os,subprocess,sys,tempfile,time
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from tests.task_board.test_git_tracking import GitCase
from task_board import lifecycle
from tools.owned_process import remove_owned_tree
from playwright.async_api import async_playwright
E=ROOT/'evidence/git-ui'/time.strftime('%Y%m%d-%H%M%S');E.mkdir(parents=True)
T=E/'browser-temp';T.mkdir();os.environ.update(TMP=str(T),TEMP=str(T),TMPDIR=str(T),PROJECT_BOARD_TEST_ROOT=str(E/'fixtures'));tempfile.tempdir=str(T)
report={'checks':[],'errors':[],'processes':[],'passed':False}
def check(value,label):
    assert value,label
    report['checks'].append(label)
def capture():
    for p in psutil.Process().children(recursive=True):
        try:
            if not any(r['pid']==p.pid and r['created']==p.create_time() for r in report['processes']):report['processes'].append({'pid':p.pid,'created':p.create_time(),'command':p.cmdline(),'purpose':'Isolated Git UI verification'})
        except psutil.NoSuchProcess:pass
async def main():
    c=GitCase();c.setUp();original=asyncio.create_subprocess_exec
    async def hidden(*a,**kw):kw['creationflags']=kw.get('creationflags',0)|subprocess.CREATE_NO_WINDOW;return await original(*a,**kw)
    try:
        c.repository();c.atomic(baseline=c.head);task=c.hub.store('alpha').get('new/one');c.action('link',{'repo':'main','commit':c.head,'task':'new/one','scope':task['scope_hash'],'reason':'Actual fixture implementation'})
        asyncio.create_subprocess_exec=hidden
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--disable-gpu','--no-first-run'])
            try:
                capture();context=await browser.new_context(viewport={'width':1280,'height':960});page=await context.new_page();page.on('pageerror',lambda e:report['errors'].append(str(e)))
                ticket=c.hub.admin_store.create_ticket(c.hub.admin_store.authenticate(c.admin['token']))
                await page.goto(c.url+'/?project=alpha&panel=git#kind=admin&access='+ticket,wait_until='networkidle');await page.wait_for_selector('g[data-commit]')
                check(await page.locator('g[data-commit]').count()==5,'graph renders every actual selected-branch commit')
                check(await page.locator('path[data-parent]').count()==5,'graph edges represent real parents including merge')
                check(await page.locator('#task-board').is_hidden(),'Git page has no repeated delivery queue')
                await page.locator('#workspace-body details').first.locator('summary').click()
                check('Local-only research' in await page.locator('#workspace-body').inner_text(),'mistakenly tracked local paths warn')
                for width in (1280,375):
                    for theme in ('light','dark'):
                        await page.set_viewport_size({'width':width,'height':960 if width==1280 else 812});await page.emulate_media(color_scheme=theme)
                        await page.screenshot(path=str(E/f'graph-{width}-{theme}.png'),full_page=True)
                        if not await page.evaluate('document.documentElement.scrollWidth<=innerWidth'):
                            lifecycle.write(E/'OVERFLOW.json',await page.evaluate('() => [...document.querySelectorAll("#workspace *")].filter(e=>{const r=e.getBoundingClientRect();return r.width>innerWidth && !e.closest(".graph-stage");}).map(e=>({tag:e.tagName,cls:e.className,html:e.outerHTML.slice(0,500),width:e.getBoundingClientRect().width}))'))
                        check(await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'Git {width}/{theme} fits')
                await page.set_viewport_size({'width':1280,'height':960})
                await page.locator('[name=git-ref]').select_option('refs/heads/feature');await page.wait_for_function('() => document.querySelectorAll("g[data-commit]").length===2');check(True,'branch selection displays actual branch ancestry')
                await page.locator('[name=git-ref]').select_option('refs/heads/main');await page.wait_for_selector('g[data-commit="'+c.head+'"]')
                await page.locator('g[data-commit="'+c.head+'"]').click();await page.wait_for_selector('#detail .git-file')
                check('new/one' in await page.locator('#detail-body').inner_text(),'commit links actual project task scope')
                await page.get_by_role('button',name='打开任务',exact=True).click();await page.get_by_role('button',name='在 Private fixture 中查找此提交').click();await page.wait_for_selector('g[data-commit="'+c.head+'"]');check(True,'task detail navigates back to fixed implementation history')
                await page.locator('g[data-commit="'+c.head+'"]').click();await page.wait_for_selector('#detail .git-file')
                row=page.locator('#detail .git-file').filter(has=page.get_by_text('src/main.py ·',exact=False));await row.get_by_role('button',name='逐行溯源').click();await page.wait_for_selector('#detail .git-blame-line')
                check('first = 1' in await page.locator('#detail-body').inner_text(),'blame displays actual line content and source SHA')
                await page.screenshot(path=str(E/'blame-desktop.png'),full_page=True);await page.locator('#close-detail').click()
                await page.locator('[name=git-commit]').fill(c.first);await page.get_by_role('button',name='定位提交',exact=True).click();await page.wait_for_selector('#detail .git-file');check(True,'full SHA lookup opens exact commit')
                check('Root <img' in await page.locator('#detail-body').inner_text() and await page.locator('#detail img').count()==0,'commit text cannot execute markup')
                local=page.locator('#detail .git-file').filter(has_text='research/raw.md');check(await local.get_by_role('button').count()==0,'local-only path offers no content actions')
                check('PRIVATE RESEARCH MUST NOT BE SHOWN' not in await page.locator('body').inner_text(),'research body is not disclosed')
                literal=page.locator('#detail .git-file').filter(has_text='src/[x].txt');await literal.get_by_role('button',name='查看差异').click();await page.wait_for_selector('.git-diff');check('+literal' in await page.locator('.git-diff').inner_text(),'literal special filename diff is accurate');await page.locator('#close-detail').click()
                await page.get_by_role('button',name='比较两个提交').click();await page.locator('#detail [name=base]').fill(c.before_merge);await page.locator('#detail [name=head]').fill(c.merge);await page.locator('#detail button[type=submit]').click();await page.wait_for_selector('#detail .git-file');check('feature.py' in await page.locator('#detail-body').inner_text(),'compare two fixed commits uses actual snapshot difference');await page.locator('#close-detail').click()
                await page.get_by_role('button',name='浏览当前版本文件').click();await page.locator('#detail [name=prefix]').fill('src');await page.locator('#detail button[type=submit]').click();await page.wait_for_selector('#detail .git-file');check(await page.locator('#detail .git-file').count()==2,'file tree locates fixed input directory');await page.locator('#close-detail').click()
                await page.locator('[name=git-path]').fill('src/main.py');await page.locator('[name=git-path]').locator('xpath=ancestor::form').locator('button[type=submit]').click();await page.wait_for_function('() => document.querySelectorAll("g[data-commit]").length===2');check(True,'file history follows actual rename')
                await page.locator('[name=git-path]').fill('');await page.locator('[name=git-path]').locator('xpath=ancestor::form').locator('button[type=submit]').click();await page.wait_for_function('() => document.querySelectorAll("g[data-commit]").length===5')
                await page.locator('#workspace-edit').click();await page.locator('[name=git-action]').select_option('policy');await page.locator('#detail [name=patterns]').fill('research/**\nlocal/**');await page.locator('#detail [name=reason]').fill('Keep project research and generated evidence on NAS')
                captured=[]
                async def intercept(route):
                    if route.request.method!='POST':await route.continue_();return
                    captured.append(route.request.post_data_json)
                    if len(captured)==1:await route.fetch();await route.abort('failed')
                    else:await route.continue_()
                await page.route('**/api/projects/alpha/git',intercept);await page.locator('#detail button[type=submit]').click();await page.wait_for_function('() => document.querySelector("#detail .form-message").textContent.length>0');await page.locator('#detail button[type=submit]').click();await page.locator('#detail').wait_for(state='hidden');await page.unroute('**/api/projects/alpha/git',intercept)
                check(len(captured)==2 and captured[0]==captured[1],'lost reply retries identical frozen Git request')
                await page.locator('#project-select').select_option('beta');await page.wait_for_function('() => Boolean(ws.git && app.project==="beta" && Object.keys(ws.git.repos).length===0)')
                check(await page.locator('g[data-commit]').count()==0 and 'fixture/private' not in await page.locator('body').inner_text(),'project switch clears previous private repository')
                c.member(role='tracker');actor=c.hub.store('alpha').authenticate(c.a['token']);ticket=c.hub.store('alpha').create_ticket(actor,allow_agent=True);worker=await browser.new_context();wp=await worker.new_page();wp.on('pageerror',lambda e:report['errors'].append(str(e)))
                await wp.goto(c.url+'/?project=alpha&panel=git#access='+ticket,wait_until='networkidle');await wp.wait_for_selector('g[data-commit]');check(await wp.locator('#workspace-edit').is_hidden(),'tracker has no governance or binding editor')
                r=await worker.request.get(c.url+'/api/projects/beta/git');check(r.status==404,'project tracker cannot read another project')
                r=await context.request.get(c.url+'/help/github');check(r.status==200,'Git operational guide available');r=await context.request.get(c.url+'/gitignore.txt');check(r.status==200 and 'runtime/' in await r.text(),'local-only ignore template downloadable')
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
        report['passed']=report['passed'] and not alive and not report['errors'] and len(report['checks'])>=24;lifecycle.write(E/'RESULT.json',report)
    print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'evidence':str(E)}))
if __name__=='__main__':asyncio.run(main())
