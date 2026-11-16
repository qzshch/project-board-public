"""Portable Python-stdlib client for local or tailnet Agent reporting.

Identity secrets are read from a profile, never command arguments or output.
Write requests are durably queued before sending; a lost response retries the
same request identity. A conflict stays visible and is never silently rebased.
"""

import argparse
import hashlib
import ipaddress
import json
import os
import re
import html
import secrets
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, ProxyHandler, build_opener
import uuid


class ClientError(Exception):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


def suite_digest(value):
    """operations schema1 canonical UTF-8 JSON manifest fingerprint."""
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf8')).hexdigest()


def save(path: Path, value: dict):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf8",
            newline="\n",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def read(path):
    return json.loads(Path(path).read_text("utf8"))

def join_worker(client,profile_path=None,private_dir=None):
    if not client.project:raise ClientError('join-worker需要明确--project，不能默认为其他项目')
    if client.profile:
        profile=client.profile
        if profile.get('project_role')!='worker' or not profile.get('worker_join_request'):raise ClientError('请复用Worker身份；不能覆盖SE或旧登记身份')
    else:
        if not profile_path:
            if not private_dir:raise ClientError('首次加入需要--private-dir指定Git外私有目录')
            profile_path=Path(private_dir)/client.project/('worker-'+uuid.uuid4().hex+'.json')
        profile_path=Path(profile_path).resolve()
        profile={'url':client.url,'project_id':client.project,'actor':'worker-'+uuid.uuid4().hex,'role':'agent','project_role':'worker','token':'worker.'+client.project+'.'+secrets.token_urlsafe(32),'worker_join_request':uuid.uuid4().hex,**({'connect_ip':client.connect_ip} if client.connect_ip else {})}
        profile_path.parent.mkdir(parents=True,exist_ok=True)
        # Exclusive creation prevents simultaneous sessions replacing each
        # other's key. Persist the same seed and request before any network I/O.
        fd=os.open(profile_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w',encoding='utf8',newline='\n') as h:
            h.write(json.dumps(profile,ensure_ascii=False,indent=2)+'\n');h.flush();os.fsync(h.fileno())
        client.profile=profile
    profile_path=Path(profile_path).resolve()
    for attempt in range(3):
        try:
            result=client.call('/api/worker-join',{'request_id':profile['worker_join_request'],'actor':profile['actor']});break
        except ClientError as exc:
            if exc.status or attempt==2:raise ClientError(str(exc)+'；原身份已保留，使用 --profile '+str(profile_path)+' join-worker 原样恢复',exc.status) from None
    save(profile_path.with_suffix('.join-receipt.json'),result)
    return {**result,'profile':str(profile_path),'token_printed':False}


def create_se(client,definition,profile_path,private_dir,receipt,actor=None):
    pid=definition.get('id') if type(definition) is dict else None
    if type(pid) is not str or not re.fullmatch(r'[a-z][a-z0-9-]{1,47}',pid):raise ClientError('定义需有效项目ID')
    if client.project and client.project!=pid:raise ClientError('项目定义与指定项目不符')
    if not profile_path:
        if not private_dir:raise ClientError('首次创建需要--private-dir指定Git外私有目录，无需先取得owner文件')
        profile_path=Path(private_dir)/pid/'owner.json'
    profile_path=Path(profile_path).resolve()
    if profile_path.exists():profile=read(profile_path)
    else:
        if client.profile:raise ClientError('已有身份不能复制为新SE身份')
        profile={'url':client.url,'project_id':pid,'actor':actor or 'se-'+uuid.uuid4().hex,'role':'agent','project_role':'owner','capability':'self-create-project','token':secrets.token_urlsafe(32),**({'connect_ip':client.connect_ip} if client.connect_ip else {})}
        if not re.fullmatch(r'[a-z][a-z0-9_-]{1,47}',profile['actor']) or profile['actor']=='root':raise ClientError('SE actor需非root的有效名称')
        profile_path.parent.mkdir(parents=True,exist_ok=True)
        try:fd=os.open(profile_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError:raise ClientError('另一会话正在创建本项目身份；原命令重试，不覆盖文件') from None
        with os.fdopen(fd,'w',encoding='utf8',newline='\n') as h:
            h.write(json.dumps(profile,ensure_ascii=False,indent=2)+'\n');h.flush();os.fsync(h.fileno())
    if profile.get('capability')!='self-create-project' or profile.get('project_id')!=pid or (actor and profile.get('actor')!=actor):raise ClientError('已有私有文件与本次自助创建不符，未覆盖')
    scoped=Client(client.url,profile,client.connect_ip,pid)
    pending=profile_path.parent/'outbox'/pid/'self-create.json'
    if pending.exists():
        request=read(pending)
        if request.get('project')!=definition or request.get('actor')!=profile['actor']:raise ClientError('原创建请求已冻结；先读回执，后续修改走knowledge，不能替换原定义',409)
    else:
        request={'request_id':uuid.uuid4().hex,'actor':profile['actor'],'project':definition};save(pending,request)
    for attempt in range(3):
        try:result=scoped.call('/api/se-start',request);break
        except ClientError as exc:
            if exc.status or attempt==2:raise ClientError(str(exc)+'；原身份及请求保留在 '+str(profile_path)+'，可用原命令恢复',exc.status) from None
    save(receipt,result)
    return {'project_id':pid,'created':result['created'],'replayed':result['replayed'],'owner_profile':str(profile_path),'receipt':str(Path(receipt).resolve()),'token_printed':False}


class Client:
    def __init__(
        self,
        url: str,
        profile: dict | None = None,
        connect_ip: str | None = None,
        project: str | None = None,
    ):
        self.url = url.rstrip("/")
        parsed = urlsplit(self.url)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path
        ):
            raise ClientError("公告板地址必须是纯HTTP(S)源地址")
        try:
            tailnet_ip = ipaddress.ip_address(parsed.hostname) in ipaddress.ip_network(
                "100.64.0.0/10"
            )
        except ValueError:
            tailnet_ip = False
        if (
            parsed.scheme == "http"
            and parsed.hostname not in ("127.0.0.1", "localhost")
            and not parsed.hostname.endswith(".ts.net")
            and not tailnet_ip
        ):
            raise ClientError(
                "HTTP只允许本机或已配置Tailscale域名；其他远端请使用HTTPS"
            )
        if profile and profile.get("url", "").rstrip("/") != self.url:
            raise ClientError("身份文件与目标公告板地址不匹配")
        self.project = project or (profile or {}).get("project_id")
        if self.project and not re.fullmatch(r"[a-z][a-z0-9-]{1,47}", self.project):
            raise ClientError("项目ID格式不正确")
        if project and profile and profile.get("project_id", "sampleapp") != project:
            raise ClientError("身份文件仅授权自己的项目，不能切换项目")
        self.profile = profile
        self.connect_ip = connect_ip or (profile or {}).get("connect_ip")
        if self.connect_ip:
            try:
                valid = ipaddress.ip_address(self.connect_ip) in ipaddress.ip_network(
                    "100.64.0.0/10"
                )
            except ValueError:
                valid = False
            if (
                not valid
                or parsed.scheme != "http"
                or not parsed.hostname.endswith(".ts.net")
            ):
                raise ClientError(
                    "显式连接IP仅用于当前HTTP Tailscale域名，且必须是私网Tailscale地址"
                )
        # Never send project credentials via a machine-wide HTTP proxy.
        self.opener = build_opener(ProxyHandler({}))

    def call(self, path: str, payload=None, *, timeout=12):
        if (
            self.project
            and path.startswith("/api/")
            and not path.startswith("/api/projects")
        ):
            path = "/api/projects/" + self.project + "/" + path[5:]
        headers = {"Accept": "application/json"}
        if self.profile:
            headers["Authorization"] = "Bearer " + self.profile["token"]
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(
                "utf8"
            )
            headers["Content-Type"] = "application/json"
        target = self.url + path
        if self.connect_ip:
            endpoint = urlsplit(self.url)
            headers["Host"] = endpoint.netloc
            target = "http://" + self.connect_ip + ":" + str(endpoint.port or 80) + path
        # Only these server journals bind request_id to the exact body. Account
        # setup, tickets and session creation are deliberately not replayed.
        endpoint=path.split('?',1)[0].rsplit('/',1)[-1]
        replayable=payload is None or type(payload) is dict and bool(payload.get('request_id')) and endpoint in {'events','governance','operations','se-start','worker-join','bootstrap','orchestration'}
        for attempt in range(3 if replayable else 1):
            try:
                with self.opener.open(Request(target,data=body,headers=headers),timeout=timeout) as response:return json.load(response)
            except HTTPError as exc:
                try:message=json.loads(exc.read(65536)).get('error','请求失败')
                except (ValueError,UnicodeError):message='请求失败'
                error=ClientError(message,exc.code)
                if exc.code not in (502,503,504):raise error from None
            except (URLError,TimeoutError,OSError):error=ClientError('公告板暂不可达；未确认已提交')
            if not replayable or attempt==2:raise error from None
            time.sleep(.3*(attempt+1))

    def task(self, task_id: str):
        try:
            return self.call("/api/task?id=" + quote(task_id, safe=""))
        except ClientError as exc:
            if exc.status == 404:
                return None
            raise

    def create_project(self, definition: dict, profile_path: Path, receipt: Path):
        """Reuse the bound private grant; never print or replace its token."""
        if not self.profile or not self.project or self.profile.get('capability')!='create-bound-project':
            raise ClientError('需要私下签发的本项目开通/owner授权文件')
        if type(definition) is not dict or definition.get('id')!=self.project:
            raise ClientError('project-init.json 的 id 必须与本项目授权一致')
        pending=Path(profile_path).parent/'outbox'/self.project/'project-create.json'
        if pending.exists():
            request=read(pending)
            if request.get('project')!=definition:raise ClientError('原创建请求已冻结；先核对原回执，不能静默替换定义',409)
        else:
            request={'request_id':str(uuid.uuid4()),'project':definition};save(pending,request)
        for attempt in range(3):
            try:
                result=self.call('/api/bootstrap',request);save(receipt,result);return result
            except ClientError as error:
                if error.status or attempt==2:raise

    def post(self, event: dict, profile_path: Path, receipt: Path | None = None):
        if not self.profile:
            raise ClientError("写入需Agent身份文件")
        if not isinstance(event.get("request_id"), str) or not event["request_id"]:
            raise ClientError("事件必须预先生成稳定request_id")
        key = hashlib.sha256(event["request_id"].encode()).hexdigest()
        pending = (
            Path(profile_path).parent
            / "outbox"
            / (self.project or "")
            / self.profile["actor"]
            / (key + ".json")
        )
        if pending.exists() and read(pending) != event:
            raise ClientError("本地请求ID已绑定不同内容", 409)
        save(pending, event)
        for attempt in range(3):
            try:
                result = self.call("/api/events", event)
                if receipt:
                    save(receipt, result)
                pending.unlink()
                return result
            except ClientError as exc:
                if exc.status or attempt == 2:
                    raise ClientError(
                        str(exc) + "；原请求保留于 " + str(pending), exc.status
                    ) from None
                time.sleep(0.3 * (attempt + 1))


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="project ID; must match the private profile")
    parser.add_argument("--url", help="remote tailnet or local board URL")
    parser.add_argument(
        "--profile", type=Path, help="private Agent identity file; never commit"
    )
    parser.add_argument(
        "--connect-ip",
        help="explicit Tailscale IP when the remote host has no MagicDNS; canonical Host retained",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser('read', help='Read an authorized project endpoint')
    inspect.add_argument('--endpoint', required=True)
    create_project = sub.add_parser('create-project',help='Create only the project bound to a private SE grant; same file remains owner identity')
    create_project.add_argument('--definition',type=Path,required=True)
    create_project.add_argument('--receipt',type=Path,required=True)
    self_se=sub.add_parser('create-se',help='Generate your own project identity and create a new project; no pre-issued owner file')
    self_se.add_argument('--definition',type=Path,required=True)
    self_se.add_argument('--private-dir',type=Path)
    self_se.add_argument('--actor',help='Optional local project SE name; does not select privileges')
    self_se.add_argument('--receipt',type=Path,required=True)
    worker=sub.add_parser('join-worker',help='Self-create an ordinary identity for one open project; no owner file required')
    worker.add_argument('--private-dir',type=Path,help='Private directory outside Git; each new session gets a unique file')
    governance = sub.add_parser('prepare-governance',help='Freeze governance revision and request ID')
    governance.add_argument('--action',required=True)
    governance.add_argument('--payload',type=Path,required=True)
    governance.add_argument('--out',type=Path,required=True)
    operations = sub.add_parser('prepare-operations',help='Freeze operational revision and request ID')
    operations.add_argument('--action',required=True)
    operations.add_argument('--payload',type=Path,required=True)
    operations.add_argument('--out',type=Path,required=True)
    git = sub.add_parser('prepare-git',help='Freeze Git binding/policy revision and request ID')
    git.add_argument('--action',required=True)
    git.add_argument('--payload',type=Path,required=True)
    git.add_argument('--out',type=Path,required=True)
    sharing = sub.add_parser('prepare-shared',help='Freeze a shared-asset request ID')
    sharing.add_argument('--action',required=True)
    sharing.add_argument('--payload',type=Path,required=True)
    sharing.add_argument('--out',type=Path,required=True)
    request = sub.add_parser('request', help='Post a frozen JSON request without rebasing')
    request.add_argument('--endpoint', required=True)
    request.add_argument('--payload', type=Path, required=True)
    request.add_argument('--out', type=Path, required=True)
    join = sub.add_parser("join")
    join.add_argument("--actor", required=True)
    join.add_argument("--join-file", type=Path)
    sub.add_parser("status")
    sub.add_parser("projects")
    benchmark=sub.add_parser('export-benchmark',help='Export aggregate time reference without task/actor IDs; review context before sharing')
    benchmark.add_argument('--out',type=Path,required=True)
    portal = sub.add_parser("portal")
    portal.add_argument("--out", type=Path, required=True)
    task = sub.add_parser("task")
    task.add_argument("task_id")
    history = sub.add_parser("history")
    history.add_argument("--task")
    history.add_argument("--after", type=int, default=0)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--task", required=True)
    prepare.add_argument("--action", required=True)
    prepare.add_argument("--payload", type=Path, required=True)
    prepare.add_argument("--out", type=Path, required=True)
    post = sub.add_parser("post")
    post.add_argument("--event", type=Path, required=True)
    post.add_argument("--receipt", type=Path)
    sub.add_parser("flush")
    verify = sub.add_parser("verify-receipt")
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument("--head", required=True)
    verify.add_argument("--task", required=True)
    args = parser.parse_args()
    profile = read(args.profile) if args.profile and args.profile.exists() else None
    url = args.url or (profile or {}).get("url")
    if not url:
        parser.error("--url or an existing --profile is required")
    try:
        client = Client(url, profile, args.connect_ip, args.project)
        if args.command=='create-se':
            print(json.dumps(create_se(client,read(args.definition),args.profile,args.private_dir,args.receipt,args.actor),ensure_ascii=False));return 0
        if args.command=='join-worker':
            print(json.dumps(join_worker(client,args.profile,args.private_dir),ensure_ascii=False));return 0
        if args.command=='create-project':
            result=client.create_project(read(args.definition),args.profile,args.receipt)
            print(json.dumps({'project_id':client.project,'created':result['created'],'replayed':result['replayed'],'owner_profile':str(args.profile.resolve()),'receipt':str(args.receipt.resolve()),'token_printed':False},ensure_ascii=False));return 0
        if args.command in ('prepare-governance','prepare-shared','prepare-operations','prepare-git'):
            if args.out.exists():raise ClientError('请求目标已存在，不能覆盖')
            value={'request_id':str(uuid.uuid4()),'action':args.action,'payload':read(args.payload)}
            if args.command=='prepare-governance':value['expected_revision']=client.call('/api/governance')['revision']
            if args.command=='prepare-operations':value['expected_revision']=client.call('/api/operations')['revision']
            if args.command=='prepare-git':value['expected_revision']=client.call('/api/git')['revision']
            save(args.out,value)
            print(json.dumps({'request':str(args.out),'project_id':client.project,'frozen':True}));return 0
        if args.command in ('read','request'):
            if not args.endpoint.startswith('/api/') or args.endpoint.startswith('/api/projects'):
                raise ClientError('使用项目相对/api端点；身份固定项目')
            result=client.call(args.endpoint, read(args.payload) if args.command=='request' else None)
            if args.command=='request':
                save(args.out,result)
                result={'receipt':str(args.out),'secret_printed':False}
            print(json.dumps(result,ensure_ascii=False))
            return 0
        if args.command == "join":
            if not args.profile:
                raise ClientError("join需要--profile写入私有身份文件")
            if profile:
                raise ClientError("身份文件已存在；直接复用，不重新登记")
            payload = {"actor": args.actor}
            if args.join_file:
                payload["join_key"] = read(args.join_file)["join_key"]
            result = client.call("/api/enroll", payload)
            save(
                args.profile,
                {
                    **result,
                    "url": client.url,
                    **({"project_id": client.project} if client.project else {}),
                    **({"connect_ip": client.connect_ip} if client.connect_ip else {}),
                },
            )
            print(
                json.dumps(
                    {
                        "joined": True,
                        "actor": result["actor"],
                        "role": result["role"],
                        "profile": str(args.profile),
                    }
                )
            )
        elif args.command == "projects":
            print(json.dumps(client.call("/api/projects"), ensure_ascii=False))
        elif args.command=='export-benchmark':
            if args.out.exists():raise ClientError('目标已存在，拒绝覆盖')
            data=client.call('/api/operations')['time_report']['benchmark']
            if not data['groups']:raise ClientError('不足5个已确认完整的同类完成样本，不能生成基准')
            save(args.out,data)
            print(json.dumps({'file':str(args.out),'sha256':hashlib.sha256(args.out.read_bytes()).hexdigest(),'groups':len(data['groups']),'note':'不含任务/人员ID；context仍需负责人审核脱敏，按资产版本显式发布'}))
        elif args.command == "portal":
            if not client.project or not profile:
                raise ClientError("项目网页入口需要含project_id的独立身份文件")
            if args.out.exists():
                raise ClientError("私有入口文件已存在，拒绝覆盖")
            response = client.call("/api/access", {})
            target = (
                client.url
                + "/?project="
                + client.project
                + "#access="
                + response["ticket"]
            )
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(
                '<!doctype html><meta charset="utf-8"><meta name="referrer" content="no-referrer"><a href="'
                + html.escape(target, quote=True)
                + '">打开本项目公告板</a><p>私有一次性入口，不转发、不提交Git。</p>',
                encoding="utf8",
            )
            os.chmod(args.out, 0o600)
            print(
                json.dumps(
                    {
                        "private_portal": str(args.out),
                        "project_id": client.project,
                        "secret_printed": False,
                    }
                )
            )
        elif args.command == "status":
            snapshot = client.call("/api/snapshot")
            counts = {}
            for task in snapshot["tasks"]:
                counts[task["status"]] = counts.get(task["status"], 0) + 1
            print(
                json.dumps(
                    {
                        "head": snapshot["head"],
                        "tasks": len(snapshot["tasks"]),
                        "statuses": counts,
                    },
                    ensure_ascii=False,
                )
            )
        elif args.command == "task":
            result = client.task(args.task_id)
            if result is None:
                raise ClientError("任务不存在", 404)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "history":
            path = (
                "/api/history?after="
                + str(args.after)
                + (("&task=" + quote(args.task, safe="")) if args.task else "")
            )
            print(json.dumps(client.call(path), ensure_ascii=False, indent=2))
        elif args.command == "prepare":
            task = client.task(args.task)
            if not task:
                raise ClientError("任务不存在", 404)
            event = {
                "request_id": str(uuid.uuid4()),
                "task_id": args.task,
                "action": args.action,
                "expected_revision": task["revision"],
                "scope_version": task["scope_version"],
                "payload": read(args.payload),
            }
            save(args.out, event)
            print(
                json.dumps(
                    {
                        "prepared": str(args.out),
                        "task_id": args.task,
                        "revision": task["revision"],
                        "scope_version": task["scope_version"],
                        "next": "检查事件文件后执行post；冲突时重新读取并决定",
                    },
                    ensure_ascii=False,
                )
            )
        elif args.command == "post":
            if not args.profile:
                raise ClientError("post需要--profile")
            print(
                json.dumps(
                    client.post(read(args.event), args.profile, args.receipt),
                    ensure_ascii=False,
                )
            )
        elif args.command == "flush":
            if not profile:
                raise ClientError("flush需要身份文件")
            folder = (
                args.profile.parent
                / "outbox"
                / (client.project or "")
                / profile["actor"]
            )
            results = []
            for pending in sorted(folder.glob("*.json")):
                results.append(client.post(read(pending), args.profile))
            print(
                json.dumps(
                    {"flushed": len(results), "receipts": results}, ensure_ascii=False
                )
            )
        elif args.command == "verify-receipt":
            receipt = read(args.receipt)
            record = client.call("/api/receipt?id=" + quote(receipt["event_id"]))
            event = record["event"]
            if (
                (
                    client.project
                    and (
                        record.get("project_id") != client.project
                        or receipt.get("project_id") != client.project
                    )
                )
                or event["hash"] != receipt["event_hash"]
                or event["task_id"] != args.task
                or event["kind"] != "submit"
                or event["payload"]["implementation_commit"] != args.head
                or record["scope_version"] != receipt["scope_version"]
                or record["current_submission_id"] != event["id"]
                or record["current_status"] == "changes_requested"
            ):
                raise ClientError("交付回执不匹配任务、实现提交或当前范围", 409)
            print(
                json.dumps(
                    {
                        "passed": True,
                        "task_id": args.task,
                        "implementation_commit": args.head,
                        "event_id": event["id"],
                        "scope": "Agent交付声明已登记；不等于root验收或合入",
                    },
                    ensure_ascii=False,
                )
            )
    except ClientError as exc:
        print(
            json.dumps(
                {"posted": False, "error": str(exc), "status": exc.status},
                ensure_ascii=False,
            )
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
