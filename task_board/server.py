"""Loopback HTTP board, optionally behind an owned Tailscale Serve proxy.

No CORS, arbitrary file serving or client-supplied privileged roles. Ordinary
project access authenticates; opted-in SE/Worker registration has only the
bounded creation authority granted by instance/project policy.
Tailscale identity is accepted only at the configured proxy Host. Local machine
processes share a trust boundary; reviewer actions still require separate keys.
"""

from datetime import datetime, timezone
from email.header import decode_header
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import gzip
import os
from pathlib import Path
import secrets
import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit

from .store import BoardError, BoardStore, canonical, fields, text
from .projects import ProjectHub, project_id

WEB_ROOT = Path(__file__).resolve().parents[1] / "task_board_web"
STATIC = {
    "/roadmap.js":"roadmap.js",
    "/focus.js":"focus.js",
    "/git-onboarding.js":"git-onboarding.js",
    "/product.js":"product.js",
    "/workspace-v2.js":"workspace-v2.js",
    "/workspace-v2.css":"workspace-v2.css",
    "/dependency-explorer.js":"dependency-explorer.js",
    "/": "index.html",
    "/index.html": "index.html",
    "/app.js": "app.js",
    "/workspace.js": "workspace.js",
    "/planning.js": "planning.js",
    "/operations.js": "operations.js",
    "/git.js": "git.js",
    "/resources.js": "resources.js",
    "/workflow.js": "workflow.js",
    "/coordination.js": "coordination.js",
    "/convergence.js": "convergence.js",
    "/finishing.js": "finishing.js",
    "/graph-layout.js": "graph-layout.js",
    "/help.css": "help.css",
    "/app.css": "app.css",
    "/tokens.css": "tokens.css",
    "/theme.css": "theme.css",
    "/login": "login.html",
    "/login.js": "login.js",
    "/login.css": "login.css",
    "/agent-console.js":"agent-console.js",
}


class BoardServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    # Linux otherwise rejects an immediate restart while old HTTP sockets are
    # in TIME_WAIT. SO_REUSEADDR does not take over a live Unix listener; the
    # lifecycle still verifies port/owner identity. Keep Windows exclusivity.
    allow_reuse_address = os.name != 'nt'

    def __init__(self, address, store: BoardStore, settings: dict):
        if address[0] != "127.0.0.1":
            raise ValueError(
                "Board backend must bind only loopback; use the authenticated proxy for other machines"
            )
        self.store, self.settings = store, settings
        self.hub = (
            ProjectHub(settings["project_state"])
            if settings.get("project_state")
            else None
        )
        from .human_auth import HumanAuth
        self.human=HumanAuth(self.hub) if self.hub else None
        if self.human:self.human.ensure_setup(settings.get('public_url','http://127.0.0.1:'+str(address[1])))
        self.semaphore = threading.BoundedSemaphore(32)
        self.started = time.time()
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.semaphore.acquire(blocking=False):
            try:
                request.sendall(
                    b"HTTP/1.1 503 Busy\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.semaphore.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.semaphore.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "ProjectBoard/4"
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(8)

    def log_message(self, fmt, *args):
        # Never record Authorization, cookies, tickets, query strings or bodies.
        path = urlsplit(self.path).path
        record = {
            "at": datetime.now(timezone.utc).isoformat(),
            "method": self.command,
            "path": path,
            "status": args[1] if len(args) > 1 else None,
        }
        log = self.server.settings.get("access_log")
        if log:
            with Path(log).open("a", encoding="utf8") as handle:
                handle.write(canonical(record) + "\n")

    def send(
        self,
        status,
        value=None,
        *,
        content_type="application/json; charset=utf-8",
        headers=None
    ):
        if (
            self.server.hub
            and getattr(self, "project", None)
            and isinstance(value, dict)
        ):
            value = {**value, "project_id": self.project}
        body = (
            (
                canonical(value).encode("utf8")
                if content_type.startswith("application/json")
                else value
            )
            if value is not None
            else b""
        )
        compressed = len(body) > 2048 and "gzip" in self.headers.get(
            "Accept-Encoding", ""
        )
        if compressed:
            body = gzip.compress(body, mtime=0)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        self.send_header("Connection", "close")
        self.send_header("Vary", "Accept-Encoding")
        if compressed:
            self.send_header("Content-Encoding", "gzip")
        for key, val in (headers or {}).items():
            for item in val if isinstance(val,list) else [val]:self.send_header(key,item)
        self.end_headers()
        if body:
            try:self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
        self.close_connection = True

    def guard(self, write=False):
        host = self.headers.get("Host", "")
        local = "127.0.0.1:" + str(self.server.server_port)
        allowed = {
            local,
            "localhost:" + str(self.server.server_port),
            *self.server.settings.get("proxy_hosts", []),
        }
        if (
            self.client_address[0] != "127.0.0.1"
            or host not in allowed
            or len(self.headers.get_all("Host", [])) != 1
        ):
            raise BoardError("主机来源不受支持", 403)
        if write:
            origin = self.headers.get("Origin")
            if origin and origin not in self.server.settings.get(
                "allowed_origins", []
            ) + ["http://" + local, "http://localhost:" + str(self.server.server_port)]:
                raise BoardError("拒绝跨站写入", 403)
        return host

    def tailnet_identity(self):
        host = self.headers.get("Host", "")
        if host not in self.server.settings.get("proxy_hosts", []):
            return None
        values = self.headers.get_all("Tailscale-User-Login", [])
        if len(values) != 1:
            return None
        try:
            login = "".join(
                part.decode(encoding or "utf8") if isinstance(part, bytes) else part
                for part, encoding in decode_header(values[0])
            )
        except (UnicodeError, LookupError):
            return None
        return (
            login
            if login in self.server.settings.get("allowed_tailnet_logins", [])
            else None
        )

    @property
    def store(self):
        if self.server.hub:
            return self.server.hub.store(getattr(self, "project", None) or "sampleapp")
        return self.server.store

    def route(self, path):
        self.project = None
        if not self.server.hub:
            return path
        if path.startswith("/api/projects/"):
            parts = path.split("/", 4)
            self.project = project_id(parts[3])
            return (
                "/api/" + parts[4] if len(parts) == 5 and parts[4] else "/api/project"
            )
        if path.startswith('/api/human/'):return path
        if path.startswith('/api/node/') or path=='/api/nodes' or path.startswith('/api/nodes/'):return path
        if path.startswith("/api/") and path not in (
            "/api/projects",
            "/api/project-grants",
            "/api/project-grants/revoke",
            "/api/bootstrap",
            "/api/se-start",
            "/api/se-entry",
            "/api/worker-entry",
            "/api/worker-join",
            "/api/me",
            "/api/session",
            "/api/logout",
            "/api/connection",
        ):
            self.project = (
                "sampleapp"  # Frozen v1 paths can only address the original project.
            )
        return path

    def identity(self):
        if hasattr(self, "_identity"):
            return self._identity
        authorization = self.headers.get("Authorization", "")
        token = None
        if authorization:
            if (
                not authorization.startswith("Bearer ")
                or len(self.headers.get_all("Authorization", [])) != 1
            ):
                raise BoardError("身份头格式不正确", 401)
            token = authorization[7:]
            if not token:
                raise BoardError("需要有效身份", 401)
        jar = cookies.SimpleCookie()
        if len(self.headers.get_all("Cookie", [])) > 1:
            raise BoardError("会话格式不正确", 401)
        try:
            jar.load(self.headers.get("Cookie", ""))
        except cookies.CookieError:
            raise BoardError("会话格式不正确", 401) from None
        self._identity = self.server.hub.resolve(
            token, jar['board_human'].value if 'board_human' in jar else jar["dhy_board"].value if "dhy_board" in jar else None
        )
        return self._identity

    def actor(self, *, required=True):
        if self.server.hub:
            identity = self.identity()
            if getattr(self, "project", None):
                self.server.hub.authorize(identity, self.project)
                return self.server.hub.effective_actor(identity, self.project)
            return identity["actor"]
        authorization = self.headers.get("Authorization", "")
        if authorization:
            if (
                not authorization.startswith("Bearer ")
                or len(self.headers.get_all("Authorization", [])) != 1
            ):
                raise BoardError("身份头格式不正确", 401)
            return self.store.authenticate(authorization[7:])
        jar = cookies.SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except cookies.CookieError:
            raise BoardError("会话格式不正确", 401) from None
        if "dhy_board" in jar:
            try:
                return self.store.session_actor(jar["dhy_board"].value)
            except BoardError:
                if required:
                    raise
        if required:
            raise BoardError("请使用Agent身份或审核授权入口", 401)
        return None

    def read_access(self):
        if self.server.hub:
            self.actor()
            return
        if self.actor(required=False) or self.tailnet_identity():
            return
        if self.headers.get("Host", "") in {
            "127.0.0.1:" + str(self.server.server_port),
            "localhost:" + str(self.server.server_port),
        }:
            return
        raise BoardError("需要已允许的Tailscale用户或Agent身份", 401)

    def body(self):
        if (
            self.headers.get("Transfer-Encoding")
            or self.headers.get("Content-Type", "").split(";")[0] != "application/json"
        ):
            raise BoardError("只接受有长度的JSON请求", 415)
        if len(self.headers.get_all("Content-Length", [])) != 1:
            raise BoardError("需要单个Content-Length")
        try:
            size = int(self.headers["Content-Length"])
        except ValueError:
            raise BoardError("Content-Length无效") from None
        if not 0 < size <= 65536:
            raise BoardError("请求大小超限", 413)
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise BoardError("请求不完整")

        def unique(pairs):
            output = {}
            for key, value in pairs:
                if key in output:
                    raise BoardError("JSON字段重复")
                output[key] = value
            return output

        try:
            return json.loads(
                raw,
                object_pairs_hook=unique,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
            )
        except (ValueError, UnicodeError, RecursionError):
            raise BoardError("JSON格式不正确") from None

    def do_GET(self):
        try:
            self.guard()
            parsed = urlsplit(self.path)
            path = self.route(parsed.path)
            if path=='/api/human/status' and self.server.human:return self.send(200,{'enabled':True,'configured':self.server.human.configured(),'login':'/login','agent_guide':'/help/worker-start'})
            from .help import DOCS, RAW_DOCS, PUBLIC_TEMPLATES, ROOT, INDEX, document_page, template_index
            if path in ('/help','/help/'):
                return self.send(200,document_page('使用手册',INDEX),content_type='text/html; charset=utf-8')
            if path=='/help/templates':
                return self.send(200,document_page('模板目录',template_index()),content_type='text/html; charset=utf-8')
            if path in ('/runner-kit.zip','/rollback-kit.zip'):
                from .help import runner_kit
                return self.send(200,runner_kit(path=='/rollback-kit.zip'),content_type='application/zip',headers={'Content-Disposition':'attachment; filename="project-board-runner.zip"'})
            if path=='/observer-kit.zip':
                from .help import observer_kit
                return self.send(200,observer_kit(),content_type='application/zip',headers={'Content-Disposition':'attachment; filename="project-observer.zip"'})
            if path=='/node-kit.zip':
                from .help import node_kit
                return self.send(200,node_kit(),content_type='application/zip',headers={'Content-Disposition':'attachment; filename="project-board-node.zip"'})
            if path in DOCS or path in RAW_DOCS:
                title,relative,private=DOCS[path] if path in DOCS else ('操作文档',*RAW_DOCS[path])
                if private and (not self.server.hub or not self.identity()['global_admin']):
                    raise BoardError('此文档需要实例管理员会话；项目协作请阅读负责人/SE或Agent指南',403)
                body=(ROOT/relative).read_text('utf8')
                return self.send(200,document_page(title,body) if path in DOCS else body.encode('utf8'),content_type='text/html; charset=utf-8' if path in DOCS else 'text/markdown; charset=utf-8')
            if path.startswith('/templates/') and path.removeprefix('/templates/') in PUBLIC_TEMPLATES:
                filename=path.removeprefix('/templates/')
                return self.send(200,(ROOT/'templates'/filename).read_bytes(),content_type='application/octet-stream' if filename.endswith('.json') else 'text/markdown; charset=utf-8',headers={'Content-Disposition':'attachment; filename="'+filename+'"'})
            if path in STATIC:
                p = WEB_ROOT / STATIC[path]
                kind = (
                    "text/html; charset=utf-8"
                    if p.suffix == ".html"
                    else (
                        "text/css; charset=utf-8"
                        if p.suffix == ".css"
                        else "text/javascript; charset=utf-8"
                    )
                )
                return self.send(200, p.read_bytes(), content_type=kind)
            if path == "/api-docs.md":
                return self.send(
                    200,
                    (WEB_ROOT.parent / "docs/TASK_BOARD_API_V2.md").read_bytes(),
                    content_type="text/markdown; charset=utf-8",
                )
            if path == '/governance-docs.md':
                return self.send(200,(WEB_ROOT.parent/'docs/API-GOVERNANCE.md').read_bytes(),content_type='text/markdown; charset=utf-8')
            if path == "/client.py":
                return self.send(
                    200,
                    (WEB_ROOT.parent / "tools/task_board_client.py").read_bytes(),
                    content_type="text/x-python; charset=utf-8",
                )
            if path == "/health":
                return self.send(
                    200,
                    {
                        "ready": True,
                        "api_version": 2 if self.server.hub else 1,
                        "product_version": 4,
                        "focus_schema": 1,
                        "roadmap_schema": 1,
                        "governance_schema": 2,
                        "operations_schema": 1,
                        "git_schema": 1,
                        "resource_directory_schema": 1,
                        "project_start_schema": 2,
                        "se_self_service": self.server.settings.get('se_self_service') is True,
                        "worker_access_schema": 1,
                        "async_flow_schema": 1,
                        "human_auth_schema": 1,
                        "orchestration_schema": 1,
                        "delegation_schema": 1,
                        "project_readiness_schema": 1,
                        "workflow_schema": 1,
                        "coordination_schema": 1,
                        "convergence_schema": 1,
                        "uptime_seconds": int(time.time() - self.server.started),
                    },
                )
            if path=='/gitignore.txt':
                from .storage_boundary import ignore_template
                return self.send(200,ignore_template().encode('utf8'),content_type='text/plain; charset=utf-8')
            if self.server.hub and self.project and path=='/api/worker-entry':
                from .worker_access import entry
                return self.send(200,entry(self.server.hub,self.project))
            if self.server.hub and path=='/api/se-entry':
                return self.send(200,{'se_self_service':self.server.settings.get('se_self_service') is True,'guide':'/help/project-start','command':'create-se','existing_project_access':'requires_current_project_identity'})
            self.read_access()
            query = parse_qs(parsed.query)
            if path=='/api/nodes':
                from .orchestration import Orchestrator
                return self.send(200,Orchestrator(self.server.hub).nodes(self.identity()))
            if path=='/api/orchestration':
                from .orchestration import Orchestrator
                return self.send(200,Orchestrator(self.server.hub).listing(self.identity(),self.project))
            if path=='/api/roadmap':
                if not self.server.hub or not self.project:raise BoardError('请使用项目路径',404)
                from .roadmap import snapshot
                return self.send(200,snapshot(self.store,self.actor()))
            if path=='/api/current':
                if not self.server.hub or not self.project:raise BoardError('请使用项目路径',404)
                from .focus import snapshot
                return self.send(200,snapshot(self.store,self.actor()))
            if path in ('/api/convergence','/api/convergence/context','/api/convergence/template'):
                if not self.server.hub or not self.project:raise BoardError('请使用项目路径',404)
                from .convergence import snapshot,context_pack,template_definition
                if path.endswith('/context'):return self.send(200,context_pack(self.store,self.actor(),query.get('task',[''])[0],query.get('since',[''])[0]))
                data=snapshot(self.store,self.actor(),query.get('task',[None])[0])
                if path.endswith('/template'):
                    ref=query.get('ref',[''])[0];t=data['templates'].get(ref)
                    if not t or t['retired'] or (t['review'] or {}).get('result')!='approve':raise BoardError('模板不存在或尚未批准',404)
                    definition=template_definition(t);document=json.dumps(definition,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
                    return self.send(200,{'definition':definition,'document':document,'sha256':__import__('hashlib').sha256(document.encode()).hexdigest()})
                return self.send(200,data)
            if path in ('/api/coordination','/api/coordination/feed'):
                if not self.server.hub or not self.project:raise BoardError('请使用项目路径',404)
                from .coordination import snapshot,feed
                return self.send(200,feed(self.store,self.actor(),query) if path.endswith('/feed') else snapshot(self.store,self.actor(),query.get('task',[None])[0]))
            if path in ('/api/workflow','/api/workflow/task','/api/workflow/inbox'):
                if not self.server.hub or not self.project:raise BoardError('请使用项目路径',404)
                from .workflow import snapshot
                task=query.get('task',[''])[0] if path.endswith('/task') else None
                if path.endswith('/task') and not task:raise BoardError('需任务ID')
                return self.send(200,snapshot(self.store,self.actor(),task,path.endswith('/inbox')))
            if path=='/api/resources' or path.startswith('/api/resources/'):
                if not self.server.hub or not self.project:raise BoardError('请使用项目路径',404)
                from .resources import Directory
                directory=Directory(self.store);actor=self.actor();operator=self.identity()['global_admin']
                suffix=path.removeprefix('/api/resources').strip('/')
                if not suffix:return self.send(200,directory.listing(actor,operator,query))
                parts=suffix.split('/')
                if len(parts)>2 or (len(parts)==2 and parts[1]!='history'):raise BoardError('资源接口不存在',404)
                return self.send(200,directory.entry(parts[0],actor,operator,len(parts)==2))
            if path=='/api/git' or path.startswith('/api/git/'):
                if not self.server.hub or not self.project:raise BoardError('请使用项目路径',404)
                from .git_tracking import Tracking
                tracking=Tracking(self.store);endpoint=path.removeprefix('/api/git').lstrip('/')
                return self.send(200,tracking.verify() if endpoint=='verify' else tracking.query(endpoint,query))
            if path=='/api/readiness':
                from .readiness import diagnose
                return self.send(200,diagnose(self.store,self.actor()))
            if path=='/api/delegations':
                from .delegation import listing
                return self.send(200,listing(self.store,self.actor()))
            if path=='/api/git-onboarding':
                if not self.server.hub or not self.project:raise BoardError('请使用项目路径',404)
                from .git_onboarding import Onboarding
                return self.send(200,Onboarding(self.store).status(query.get('repo',[''])[0]))
            if path in ('/api/product','/api/usage','/api/usage/head','/api/sessions'):
                if not self.server.hub or not self.project:raise BoardError('请使用项目路径',404)
                if path in ('/api/usage','/api/usage/head'):
                    from .usage import Usage
                    usage=Usage(self.store)
                    return self.send(200,usage.head(self.actor()) if path.endswith('/head') else usage.report(self.actor()))
                from .product import snapshot
                data=snapshot(self.store,self.actor())
                if path=='/api/sessions':
                    from .orchestration import Orchestrator
                    from .operations import Operations
                    data={'references':data['sessions'],'managed':Orchestrator(self.server.hub).listing(self.identity(),self.project)['bindings'],'attempts':Operations(self.store).snapshot(self.actor()).get('cv_sessions',{})}
                return self.send(200,data)
            if path in ('/api/operations','/api/operations/verify'):
                if not self.server.hub or not self.project:raise BoardError('请使用项目路径',404)
                from .operations import Operations
                op=Operations(self.store)
                return self.send(200,op.verify() if path.endswith('/verify') else op.snapshot(self.actor()))
            if path in ('/api/governance','/api/graph','/api/search','/api/governance/export','/api/governance/verify','/api/brief','/api/shared','/api/shared/impact'):
                if not self.server.hub or not self.project:
                    raise BoardError('请使用项目路径',404)
                from .governance import Governance
                governance=Governance(self.store)
                if path=='/api/governance/verify':return self.send(200,governance.verify())
                if path=='/api/shared':return self.send(200,{'releases':self.store.registry.listing(),'consumption':self.store.registry.consumption()})
                if path=='/api/shared/impact':return self.send(200,{'consumers':self.store.registry.impact(self.identity(),query.get('ref',[''])[0])})
                if path=='/api/brief':
                    from .brief import build_brief
                    return self.send(200,build_brief(self.store,query.get('task',[''])[0],self.project,self.server.settings.get('public_url',''),self.actor(),self.identity()['global_admin']))
                data=governance.snapshot(query.get('q',[''])[0] if path=='/api/search' else '',self.actor(),self.identity()['global_admin'])
                if path=='/api/graph':data={k:data[k] for k in ('revision','graph','queue','nodes')}
                return self.send(200,data)
            if self.server.hub and path == "/api/projects":
                return self.send(
                    200, {"projects": self.server.hub.list_projects(self.identity())}
                )
            if self.server.hub and path == "/api/project":
                return self.send(
                    200, self.server.hub.authorize(self.identity(), self.project)
                )
            if path == "/api/me":
                actor = self.actor(required=False)
                return self.send(
                    200,
                    {
                        "actor": actor["id"] if actor else None,
                        "project_role":actor.get('project_role') if actor else None,
                        "role": (
                            (
                                "admin"
                                if self.server.hub
                                and self.identity()["global_admin"]
                                and not self.project
                                else actor["role"]
                            )
                            if actor
                            else "viewer"
                        ),
                        **(
                            {
                                "global_admin": self.identity()["global_admin"],
                                "principal_kind": self.identity().get('principal_kind','operator' if self.identity()['global_admin'] else 'agent'),
                                "display_name": actor.get('display_name',actor['id']),
                                "project_id": self.project
                                or self.identity()["project_id"],
                            }
                            if self.server.hub
                            else {}
                        ),
                        "tailnet_authenticated": bool(self.tailnet_identity()),
                    },
                )
            if path == "/api/connection":
                return self.send(
                    200,
                    {
                        "api_version": 2 if self.server.hub else 1,
                        "url": self.server.settings.get(
                            "public_url",
                            "http://127.0.0.1:" + str(self.server.server_port),
                        ),
                        "connect_ip": (
                            self.server.settings.get("network_ownership") or {}
                        ).get("connect_ip"),
                        "note": "Agent凭据与审核凭据分别签发；此处不含凭据",
                    },
                )
            if path == "/api/snapshot":
                etag = (
                    '"'
                    + (self.project + ":" if self.server.hub else "")
                    + self.store.head()["hash"]
                    + '"'
                )
                if self.headers.get("If-None-Match") == etag:
                    return self.send(304, headers={"ETag": etag})
                value = self.store.snapshot()
                etag = (
                    '"'
                    + (self.project + ":" if self.server.hub else "")
                    + value["head"]["hash"]
                    + '"'
                )
                return self.send(200, value, headers={"ETag": etag})
            if path == "/api/history":
                after = int(query.get("after", ["0"])[0])
                limit = int(query.get("limit", ["200"])[0])
                return self.send(
                    200,
                    {
                        "events": self.store.history(
                            query.get("task", [None])[0], after, limit
                        )
                    },
                )
            if path == "/api/task":
                return self.send(200, self.store.get(query.get("id", [""])[0]))
            if path == "/api/receipt":
                return self.send(200, self.store.receipt(query.get("id", [""])[0]))
            if path == "/api/verify":
                actor = self.actor()
                if actor["role"] != "reviewer":
                    raise BoardError("需要审核者", 403)
                return self.send(200, self.store.verify())
            raise BoardError("接口不存在", 404)
        except BoardError as exc:
            self.send(exc.status, {"error": str(exc)})
        except (ValueError, TypeError):
            self.send(400, {"error": "请求字段类型不正确"})
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            self.close_connection = True

    def do_POST(self):
        try:
            self.guard(write=True)
            if self.server.settings.get('maintenance_read_only'):
                raise BoardError('迁移校验期间暂缓写入，请保留原请求稍后重试',503)
            path = self.route(urlsplit(self.path).path)
            value = self.body()
            if path.startswith('/api/node/'):
                from .orchestration import Orchestrator
                control=Orchestrator(self.server.hub);auth=self.headers.get('Authorization','')
                if len(self.headers.get_all('Authorization',[]))!=1 or not auth.startswith('Bearer '):raise BoardError('需要单一节点身份',401)
                token=auth[7:]
                if path=='/api/node/enroll':return self.send(201,control.enroll(token,value))
                node=control.node(token)
                if path=='/api/node/heartbeat':result=control.heartbeat(node,value)
                elif path=='/api/node/poll':
                    fields(value,set(),set());result=control.poll(node)
                elif path=='/api/node/report':result=control.report(node,value)
                elif path=='/api/node/profile':result=control.profile(node,value)
                else:raise BoardError('节点接口不存在',404)
                return self.send(200,result)
            if path in ('/api/nodes/pair','/api/nodes/revoke'):
                from .orchestration import Orchestrator
                control=Orchestrator(self.server.hub)
                return self.send(201,control.pair(self.identity(),value) if path.endswith('/pair') else control.revoke(self.identity(),value))
            if path.startswith('/api/human/') and self.server.human:
                if path=='/api/human/setup':token=self.server.human.setup(value)
                elif path=='/api/human/login':token=self.server.human.login(value)
                elif path=='/api/human/password':token=self.server.human.change_password(self.identity(),value)
                else:raise BoardError('人类账号接口不存在',404)
                secure='; Secure' if self.headers.get('Host') in self.server.settings.get('proxy_hosts',[]) and self.server.settings.get('proxy_https',True) else ''
                return self.send(200,{'logged_in':True,'principal_kind':'human'},headers={'Set-Cookie':'board_human='+token+'; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800'+secure})
            if path == "/api/enroll":
                fields(value, {"actor", "join_key"}, {"actor"})
                if value["actor"] == "root":
                    raise BoardError("root不能自助注册", 403)
                if self.server.hub:
                    return self.send(
                        201,
                        self.server.hub.enroll(
                            self.project or "sampleapp",
                            value["actor"],
                            value.get("join_key", ""),
                        ),
                    )
                local_join = secrets.compare_digest(
                    str(value.get("join_key", "")),
                    self.server.settings.get("join_key", "!"),
                )
                if not self.tailnet_identity() and not local_join:
                    raise BoardError("需可信Tailscale身份或本机登记文件", 401)
                # Enrollment can never choose its role or obtain reviewer keys.
                result = self.store.register_actor(value["actor"], "agent")
                return self.send(201, result)
            if path == "/api/session":
                fields(value, {"ticket"}, {"ticket"})
                token = (
                    self.server.hub.redeem(value["ticket"], self.project)
                    if self.server.hub
                    else self.store.redeem_ticket(value["ticket"])
                )
                secure = (
                    "; Secure"
                    if self.headers.get("Host")
                    in self.server.settings.get("proxy_hosts", [])
                    and self.server.settings.get("proxy_https", True)
                    else ""
                )
                return self.send(
                    200,
                    {"logged_in": True},
                    headers={
                        "Set-Cookie": "dhy_board="
                        + token
                        + "; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800"
                        + secure
                    },
                )
            if path == "/api/logout":
                jar = cookies.SimpleCookie()
                jar.load(self.headers.get("Cookie", ""))
                if 'board_human' in jar and self.server.human:self.server.human.logout(jar['board_human'].value)
                if "dhy_board" in jar:
                    if self.server.hub:
                        self.server.hub.logout(jar["dhy_board"].value)
                    else:
                        self.store.logout(jar["dhy_board"].value)
                return self.send(
                    200,
                    {"logged_out": True},
                    headers={
                        "Set-Cookie": ["dhy_board=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0","board_human=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"]
                    },
                )
            if self.server.hub and path=='/api/se-start':
                if not self.project:raise BoardError('请使用明确的新项目路径',404)
                auth=self.headers.get_all('Authorization',[])
                if len(auth)!=1 or not auth[0].startswith('Bearer '):raise BoardError('需要客户端生成的本项目SE身份',401)
                from .project_start import self_start
                return self.send(201,self_start(self.server.hub,self.project,auth[0][7:],value,self.server.settings.get('se_self_service')))
            if self.server.hub and path=='/api/worker-join':
                if not self.project:raise BoardError('请使用指定项目入口',404)
                auth=self.headers.get_all('Authorization',[])
                if len(auth)!=1 or not auth[0].startswith('Bearer '):raise BoardError('需要客户端生成的项目Worker身份',401)
                from .worker_access import join
                return self.send(201,join(self.server.hub,self.project,auth[0][7:],value))
            if self.server.hub and path=='/api/bootstrap':
                if not self.project:raise BoardError('Use the bound project path',404)
                auth=self.headers.get_all('Authorization',[])
                if len(auth)!=1 or not auth[0].startswith('Bearer ') or not auth[0][7:]:raise BoardError('Need a private bound-project grant',401)
                from .project_start import bootstrap
                return self.send(201,bootstrap(self.server.hub,self.project,auth[0][7:],value))
            actor = self.actor()
            if path=='/api/orchestration':
                from .orchestration import Orchestrator
                return self.send(201,Orchestrator(self.server.hub).apply(self.identity(),self.project,value))
            if self.server.hub and path in ('/api/project-grants','/api/project-grants/revoke'):
                from .project_start import issue,revoke
                result=issue(self.server.hub,self.identity(),value,self.server.settings.get('public_url','')) if path=='/api/project-grants' else revoke(self.server.hub,self.identity(),value)
                return self.send(201,result)
            if path=='/api/git':
                if not self.server.hub or not self.project:raise BoardError('请使用项目路径',404)
                from .git_tracking import Tracking
                return self.send(201,Tracking(self.store).apply(actor,value))
            if path=='/api/operations':
                if not self.server.hub or not self.project:raise BoardError('请使用项目路径',404)
                from .operations import Operations
                return self.send(201,Operations(self.store).apply(actor,value))
            if path in ('/api/git-onboarding/request','/api/git-onboarding/authorize','/api/git-onboarding/sync'):
                if not self.server.hub or not self.project:raise BoardError('请使用项目路径',404)
                from .git_onboarding import Onboarding
                return self.send(201,getattr(Onboarding(self.store),path.rsplit('/',1)[1])(actor,value))
            if path=='/api/usage':
                if not self.server.hub or not self.project:raise BoardError('请使用项目路径',404)
                from .usage import Usage
                return self.send(201,Usage(self.store).append(actor,value))
            if path in ('/api/governance','/api/shared'):
                if not self.server.hub or not self.project:raise BoardError('请使用项目路径',404)
                from .governance import Governance
                return self.send(201,Governance(self.store).apply({**actor,'global_admin':self.identity()['global_admin']},value) if path=='/api/governance' else self.store.registry.apply(actor,value))
            if self.server.hub and path == "/api/projects":
                return self.send(201, self.server.hub.create(self.identity(), value))
            if self.server.hub and path == "/api/access":
                fields(value, set(), set())
                return self.send(
                    201,
                    {
                        "ticket": self.store.create_ticket(actor, allow_agent=True),
                        "expires_in_seconds": 86400,
                    },
                )
            if self.server.hub and path == "/api/actors":
                fields(value, {"actor", "role"}, {"actor"})
                role = value.get("role", "agent")
                if (
                    actor["role"] != "reviewer"
                    or role not in ("agent", "reviewer")
                    or (role == "reviewer" and not self.identity()["global_admin"])
                ):
                    raise BoardError("需要适用范围的审核权限", 403)
                return self.send(
                    201,
                    self.server.hub.invite(
                        self.project, value["actor"], role, operator=actor["id"]
                    ),
                )
            if path == "/api/actors/revoke":
                fields(value, {"actor", "reason"}, {"actor", "reason"})
                if self.server.hub:
                    return self.send(
                        200,
                        self.server.hub.revoke(
                            self.identity(),
                            self.project,
                            value["actor"],
                            value["reason"],
                        ),
                    )
                return self.send(
                    200,
                    self.store.revoke_actor(actor, value["actor"], value["reason"]),
                )
            if path == "/api/events":
                return self.send(201, self.store.apply(actor, value))
            raise BoardError("接口不存在", 404)
        except BoardError as exc:
            self.send(exc.status, {"error": str(exc)})
        except (ValueError, TypeError, KeyError):
            self.send(400, {"error": "请求字段类型不正确"})
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            self.close_connection = True


def serve(store: BoardStore, port: int, settings: dict, stop_file: Path, ready=None):
    server = BoardServer(("127.0.0.1", port), store, settings)
    server.timeout = 0.5
    try:
        if ready:
            ready(server.server_port)
        while not stop_file.exists():
            server.handle_request()
    finally:
        server.server_close()
