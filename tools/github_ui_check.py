"""Real SE onboarding UI over isolated HTTP; GitHub is a fixed protocol fixture."""
import asyncio,json,os,subprocess,sys,tempfile,time,hashlib
from pathlib import Path
from unittest.mock import patch
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tests.task_board.test_github_local import GitHubLocalCase,IDENTITY,READ,READONLY
from task_board.git_onboarding import Onboarding
from tools.owned_process import remove_owned_tree
from playwright.async_api import async_playwright
E=ROOT/'evidence/github-ui'/time.strftime('%Y%m%d-%H%M%S');E.mkdir(parents=True);T=E/'temporary';T.mkdir();os.environ.update(TMP=str(T),TEMP=str(T),TMPDIR=str(T),PROJECT_BOARD_TEST_ROOT=str(E/'fixtures'));tempfile.tempdir=str(T)
report={'passed':False,'checks':[],'errors':[],'screens':[],'processes':[],'isolated_fixture':True}
def sources():return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ['task_board','task_board_web','tests','tools'] for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
report['sources']=sources()
def check(v,label):
 assert v,label
 report['checks'].append(label)
async def main():
 c=GitHubLocalCase();c.setUp();original=asyncio.create_subprocess_exec
 async def hidden(*a,**k):
  if os.name=='nt':k['creationflags']=k.get('creationflags',0)|subprocess.CREATE_NO_WINDOW
  return await original(*a,**k)
 try:
  c.key();asyncio.create_subprocess_exec=hidden
  async with async_playwright() as pw:
   browser=await pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--disable-gpu','--no-first-run'])
   try:
    for p in psutil.Process().children(recursive=True):
     try:report['processes'].append({'pid':p.pid,'created':p.create_time(),'command':p.cmdline(),'purpose':'Owned SE GitHub onboarding UI fixture'})
     except psutil.NoSuchProcess:pass
    ctx=await browser.new_context(viewport={'width':1440,'height':960});page=await ctx.new_page();page.on('pageerror',lambda e:report['errors'].append(str(e)));requests=[]
    page.on('request',lambda r:requests.append({'url':r.url,'body':r.post_data}) if '/git-onboarding/' in r.url and r.method=='POST' else None)
    ticket=c.hub.admin_store.create_ticket(c.hub.admin_store.authenticate(c.admin['token']));await ctx.request.post(c.url+'/api/session',data={'ticket':ticket});await page.goto(c.url+'/?project=alpha',wait_until='networkidle');await page.evaluate("selectWorkspacePanel('git')");await page.wait_for_selector('[data-github-local=main]',state='attached');await page.locator('[data-github-local=main]').evaluate('(e)=>e.closest("details").open=true')
    box=page.locator('[data-github-local=main]');check('使用本机现有GitHub管理授权' in await box.inner_text(),'local existing authorization is primary')
    check(await box.locator('a[href="/github-kit.zip"]').count()==1,'downloadable local SE tool available')
    check('--repo main' in await box.locator('pre').inner_text(),'command binds selected repository')
    grant=page.locator('details').filter(has=page.locator('summary',has_text='可选：使用单仓库临时授权')).last
    check(not await grant.evaluate('(e)=>e.open'),'temporary grant is optional and folded')
    for width,theme in [(1440,'light'),(1440,'dark'),(390,'light'),(390,'dark')]:
     await page.set_viewport_size({'width':width,'height':960});await page.evaluate('(v)=>{currentTheme=v;applyTheme();}',theme);check(await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),f'{width} {theme} no overflow');f=E/f'{width}-{theme}.png';await page.screenshot(path=str(f),full_page=True);report['screens'].append(str(f))
    await page.set_viewport_size({'width':1440,'height':960})
    with patch('tools.owned_process.run',side_effect=[IDENTITY,READ,READONLY]),patch.object(Onboarding,'sync',return_value={'stage':'ready','read_only':True}):
     await page.get_by_role('button',name='我已登记公钥，核验并接入').click();await page.wait_for_function('()=>document.querySelector("#notice").textContent.includes("独立核对")')
    complete=next(r for r in requests if r['url'].endswith('/complete'));p=json.loads(complete['body']);check(set(p)=={'repo','repository','public_key'},'actual browser posts only repository and public key')
    check(not any(r['url'].endswith('/authorize') for r in requests),'no token authorization request made')
    check((await ctx.request.get(c.url+'/github-kit.zip')).ok,'actual tool kit download served')
    check(not report['errors'],'no browser runtime errors');check(sources()==report['sources'],'same source bytes throughout UI checks');report['passed']=True
   finally:await browser.close()
 finally:
  asyncio.create_subprocess_exec=original;c.tearDown();(E/'RESULT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');remove_owned_tree(T,E)
if __name__=='__main__':
 asyncio.run(main());print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'evidence':str(E)}))
