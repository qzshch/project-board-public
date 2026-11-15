"""Interactive instance owner accounts; never infer humanity from client headers.

The private one-use setup link establishes the account, not a reusable API key.
Project Agent credentials and the separately held maintenance identity remain
their existing realms. Passwords and raw session/setup secrets are not audited.
"""
import base64,hashlib,hmac,html,json,os,re,secrets,time,unicodedata
from pathlib import Path
from .store import BoardError,fields,text

SESSION_SECONDS=8*3600

def prepare(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS human_accounts(id TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE,display_name TEXT NOT NULL,salt TEXT NOT NULL,password_hash TEXT NOT NULL,created REAL NOT NULL,disabled INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS human_sessions(hash TEXT PRIMARY KEY,account TEXT NOT NULL,expires REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS human_auth_state(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS human_auth_failures(name TEXT PRIMARY KEY,count INTEGER NOT NULL,window REAL NOT NULL,locked_until REAL NOT NULL);
    ''')

def digest(value):return hashlib.sha256(value.encode('utf8')).hexdigest()
def derive(password,salt):return hashlib.scrypt(password.encode('utf8'),salt=bytes.fromhex(salt),n=16384,r=8,p=1,maxmem=64*1024*1024).hex()
def username(value):
    if type(value) is not str:raise BoardError('账号需字符串')
    value=unicodedata.normalize('NFC',value.strip())
    if not 2<=len(value)<=64 or not all(c.isalnum() or c in '._-' for c in value):raise BoardError('账号需2～64位字母、数字或 . _ -')
    return value.casefold(),value
def password(value,new=False):
    if type(value) is not str or not (12 if new else 1)<=len(value)<=256 or len(value.encode('utf8'))>1024:raise BoardError('新密码至少12个字符，最多256个字符' if new else '密码格式不正确')
    return value

class HumanAuth:
    def __init__(self,hub):self.hub=hub

    def configured(self):
        with self.hub.connection() as db:return bool(db.execute('SELECT 1 FROM human_accounts LIMIT 1').fetchone())

    def ensure_setup(self,public_url):
        """Called by the instance operator/startup; only a private file carries the link."""
        if self.configured():return None
        path=self.hub.state/'_private/human/setup.html'
        with self.hub.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM human_accounts LIMIT 1').fetchone():db.rollback();return None
            old=db.execute("SELECT value FROM human_auth_state WHERE key='setup'").fetchone()
            if old and json.loads(old[0])['expires']>time.time() and path.is_file():db.rollback();return path
            secret=secrets.token_urlsafe(32);value={'hash':digest(secret),'expires':time.time()+72*3600}
            # Write the private pointer before committing its accepted digest.
            path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            url=public_url.rstrip('/')+'/login#setup='+secret
            document='<!doctype html><meta charset="utf-8"><title>公告板人类所有者初始化</title><p>此文件是私有的一次性初始化入口，请勿转发给Agent或放入Git。</p><a href="'+html.escape(url,quote=True)+'">设置人类所有者账号密码</a>'
            temporary=path.with_name(path.name+'.'+secrets.token_hex(8)+'.tmp')
            try:
                temporary.write_text(document,encoding='utf8');temporary.chmod(0o600);os.replace(temporary,path)
            finally:
                if temporary.exists():temporary.unlink()
            db.execute("INSERT OR REPLACE INTO human_auth_state VALUES('setup',?)",(json.dumps(value),));self.hub.audit(db,'human_setup_prepared',None,'instance-operator',{'expires':value['expires'],'secret_in_private_file_only':True});db.commit()
        return path

    def session(self,db,account):
        secret=secrets.token_urlsafe(32);db.execute('INSERT INTO human_sessions VALUES(?,?,?)',(digest(secret),account,time.time()+SESSION_SECONDS));return 'h.'+secret

    def setup(self,p):
        fields(p,{'setup','username','password'},{'setup','username','password'});text(p['setup'],'初始化凭据',256);name,display=username(p['username']);pwd=password(p['password'],True)
        with self.hub.connection() as db:
            db.execute('BEGIN IMMEDIATE');row=db.execute("SELECT value FROM human_auth_state WHERE key='setup'").fetchone();old=json.loads(row[0]) if row else {}
            if db.execute('SELECT 1 FROM human_accounts LIMIT 1').fetchone() or old.get('expires',0)<=time.time() or not hmac.compare_digest(old.get('hash',''),digest(p['setup'])):raise BoardError('初始化入口无效、过期或已使用',401)
            account='human-'+secrets.token_hex(12);salt=secrets.token_hex(16);db.execute('INSERT INTO human_accounts VALUES(?,?,?,?,?,?,0)',(account,name,display,salt,derive(pwd,salt),time.time()));db.execute("DELETE FROM human_auth_state WHERE key='setup'");token=self.session(db,account);self.hub.audit(db,'human_account_created',None,account,{'username':display});db.commit();return token

    def login(self,p):
        fields(p,{'username','password'},{'username','password'});name,_=username(p['username']);pwd=password(p['password']);now=time.time()
        with self.hub.connection() as db:
            db.execute('BEGIN IMMEDIATE');failure=db.execute('SELECT * FROM human_auth_failures WHERE name=?',(name,)).fetchone()
            if failure and failure['locked_until']>now:raise BoardError('登录尝试过多，请稍后重试',429)
            account=db.execute('SELECT * FROM human_accounts WHERE name=?',(name,)).fetchone();actual=derive(pwd,account['salt'] if account else '00'*16)
            if not account or account['disabled'] or not hmac.compare_digest(actual,account['password_hash']):
                count=failure['count']+1 if failure and now-failure['window']<900 else 1;window=failure['window'] if failure and now-failure['window']<900 else now
                db.execute('DELETE FROM human_auth_failures WHERE window<?',(now-86400,));db.execute('INSERT OR REPLACE INTO human_auth_failures VALUES(?,?,?,?)',(name,count,window,now+300 if count>=5 else 0));self.hub.audit(db,'human_login_failed',None,'unauthenticated',{'name_hash':digest(name),'limited':count>=5});db.commit();raise BoardError('账号或密码错误',401)
            db.execute('DELETE FROM human_auth_failures WHERE name=?',(name,));db.execute('DELETE FROM human_sessions WHERE expires<?',(now,));token=self.session(db,account['id']);self.hub.audit(db,'human_login',None,account['id'],{});db.commit();return token

    def resolve(self,token):
        if type(token) is not str or not token.startswith('h.') or len(token)>256:raise BoardError('需要人类所有者登录',401)
        with self.hub.connection() as db:
            row=db.execute('SELECT a.* FROM human_sessions s JOIN human_accounts a ON a.id=s.account WHERE s.hash=? AND s.expires>? AND a.disabled=0',(digest(token[2:]),time.time())).fetchone()
            if not row:raise BoardError('人类会话已失效，请重新登录',401)
            return {'global_admin':True,'project_id':None,'principal_kind':'human','actor':{'id':row['id'],'role':'reviewer','global_human':True,'principal_kind':'human','display_name':row['display_name']}}

    def change_password(self,identity,p):
        if identity.get('principal_kind')!='human':raise BoardError('仅人类账号可修改自己的密码',403)
        fields(p,{'current_password','password'},{'current_password','password'});old=password(p['current_password']);new=password(p['password'],True);account=identity['actor']['id']
        with self.hub.connection() as db:
            db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT * FROM human_accounts WHERE id=?',(account,)).fetchone()
            if not row or not hmac.compare_digest(derive(old,row['salt']),row['password_hash']):raise BoardError('当前密码错误',401)
            salt=secrets.token_hex(16);db.execute('UPDATE human_accounts SET salt=?,password_hash=? WHERE id=?',(salt,derive(new,salt),account));db.execute('DELETE FROM human_sessions WHERE account=?',(account,));token=self.session(db,account);self.hub.audit(db,'human_password_changed',None,account,{'all_previous_sessions_revoked':True});db.commit();return token

    def logout(self,token):
        with self.hub.connection() as db:
            db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT account FROM human_sessions WHERE hash=?',(digest(token[2:]),)).fetchone();db.execute('DELETE FROM human_sessions WHERE hash=?',(digest(token[2:]),))
            if row:self.hub.audit(db,'human_logout',None,row['account'],{})
            db.commit()
