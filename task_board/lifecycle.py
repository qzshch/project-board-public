"""Explicit persistent board service with hidden Windows startup and exact stop.

Runtime/credentials live in a separate G: directory. Starting an existing owner
reuses it; PID reuse, an occupied unknown port or a foreign proxy is refused.
"""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import signal
import time
import psutil

from .server import serve
from .store import BoardStore, BoardError
from .projects import ProjectHub

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / "state"


def read(path):
    return json.loads(Path(path).read_text("utf8"))


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf8",
            newline="\n",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def init_state(
    state: Path,
    *,
    public_url: str,
    network: dict | None = None,
    login: str | None = None,
    port: int = 24710,
) -> dict:
    state = state.resolve()
    if (state/'MIGRATED_TO.json').exists():
        raise BoardError('此PC状态已迁往NAS，禁止重新初始化',409)
    if type(port) is not int or not 1024<=port<=65535:
        raise BoardError('后端端口需1024～65535整数')
    from urllib.parse import urlsplit
    endpoint=urlsplit(public_url)
    if endpoint.scheme not in ('http','https') or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.path not in ('','/') or endpoint.query or endpoint.fragment:
        raise BoardError('需无凭据与路径的HTTP(S)实例URL')
    public_url=public_url.rstrip('/')
    if os.name == "nt" and state.drive.upper() == "C:":
        raise BoardError("公告板运行数据必须位于C盘之外")
    state.mkdir(parents=True, exist_ok=True)
    private = state / "_private"
    private.mkdir(exist_ok=True)
    store = BoardStore(state / "board.sqlite")
    reviewer = private / "reviewer.json"
    if reviewer.exists():
        identity = read(reviewer)
        actor = store.authenticate(identity["token"])
    else:
        identity = store.register_actor("root", "reviewer")
        write(reviewer, {**identity, "url": public_url})
        actor = store.authenticate(identity["token"])
    setting_path = private / "server.json"
    if setting_path.exists():
        settings = read(setting_path)
        if settings["public_url"] != public_url:
            raise BoardError("实例地址已登记，不能静默更换")
    else:
        from urllib.parse import urlsplit

        parsed = urlsplit(public_url)
        urls = [public_url, *((network or {}).get("alternate_urls", []))]
        settings = {
            "public_url": public_url,
            "proxy_hosts": [
                urlsplit(u).netloc
                for u in urls
                if urlsplit(u).hostname not in ("127.0.0.1", "localhost")
            ],
            "allowed_origins": urls,
            "allowed_tailnet_logins": [login] if login else [],
            "proxy_https": parsed.scheme == "https",
            "join_key": secrets.token_urlsafe(32),
            "access_log": str(state / "access.jsonl"),
            "port": port,
            "network_ownership": network,
        }
        write(setting_path, settings)
        write(private / "agent-enrollment.json", {"join_key": settings["join_key"]})
    snapshot = {'adapter': 'empty-v1'}
    imported = 0
    result = store.verify()
    hub = ProjectHub(state)
    hub.initialize_empty(public_url)
    settings["project_state"] = str(state)
    write(setting_path, settings)
    write(
        state / "connection.json",
        {
            "api_version": 2,
            "default_project": None,
            "url": public_url,
            "local_url": "http://127.0.0.1:"+str(settings['port']),
            "code_root": str(ROOT),
            "client_script": str(ROOT / "tools/task_board_client.py"),
            "project": "project-board",
            "state": str(state),
            "snapshot": snapshot,
        },
    )
    return {
        "initialized": True,
        "imported": imported,
        "verification": result,
        "url": public_url,
    }


def exact_owner(record):
    try:
        process = psutil.Process(record["pid"])
        if (
            abs(process.create_time() - record["created"]) < 0.01
            and Path(process.exe()).resolve() == Path(record["executable"]).resolve()
            and process.cmdline() == record["command"]
        ):
            return process
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return None


def command(state: Path, arguments: list[str], timeout: int = 15) -> bytes:
    """Finite hidden administrative child; command has no credential values."""
    startup = None
    flags = 0
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        flags = subprocess.CREATE_NO_WINDOW
    child = subprocess.Popen(
        arguments,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=flags,
        startupinfo=startup,
    )
    record = {
        "pid": child.pid,
        "command": arguments,
        "purpose": "owned board proxy lifecycle",
        "started": time.time(),
    }
    try:
        try:
            record["created"] = psutil.Process(child.pid).create_time()
        except psutil.NoSuchProcess:
            record["already_exited"] = True
        out, err = child.communicate(timeout=timeout)
        record["returncode"] = child.returncode
        if child.returncode:
            raise BoardError("私网转发命令失败；未修改其他服务")
        return out
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(5)
        record.update(waited=True, finished=time.time())
        with (state / "lifecycle.jsonl").open("a", encoding="utf8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def proxy(state: Path, enable: bool) -> dict:
    settings = read(state / "_private/server.json")
    network = settings.get("network_ownership")
    if not network or not network.get("configured"):
        return {"managed_proxy": False}
    from urllib.parse import urlsplit

    endpoint = urlsplit(settings["public_url"])
    target = "http://127.0.0.1:" + str(settings["port"])
    if (
        network.get("backend") != target
        or not endpoint.hostname.endswith(".ts.net")
        or not endpoint.port
    ):
        raise BoardError("私网转发所有权记录不一致")
    executable = "C:/Program Files/Tailscale/tailscale.exe"
    before = json.loads(command(state, [executable, "serve", "status", "--json"]))
    host = endpoint.netloc
    handlers = before.get("Web", {}).get(host, {}).get("Handlers", {})
    tcp = before.get("TCP", {}).get(str(endpoint.port))
    expected_tcp = {"HTTPS": True} if endpoint.scheme == "https" else {"HTTP": True}
    if tcp is not None and tcp != expected_tcp:
        raise BoardError("目标端口协议由其他配置持有，未修改", 409)
    current = handlers.get("/")
    expected = {"Proxy": target}
    if current is not None and current != expected:
        raise BoardError("目标转发已由其他服务接管，未覆盖", 409)
    if (enable and current == expected) or (not enable and current is None):
        return {"managed_proxy": True, "enabled": enable, "changed": False}
    flag = "--https=" if endpoint.scheme == "https" else "--http="
    args = [executable, "serve", flag + str(endpoint.port), "--set-path=/"]
    args += ["--bg", "--yes", target] if enable else ["off"]
    command(state, args)
    after = json.loads(command(state, [executable, "serve", "status", "--json"]))

    # Ignore only our exact root handler. Every other service and path must survive.
    def others(value):
        copy = json.loads(json.dumps(value))
        mapping = copy.get("Web", {}).get(host)
        if mapping:
            mapping.get("Handlers", {}).pop("/", None)
            if not mapping.get("Handlers"):
                copy["Web"].pop(host, None)
        copy.get("TCP", {}).pop(str(endpoint.port), None)
        if not copy.get("Web"):
            copy.pop("Web", None)
        if not copy.get("TCP"):
            copy.pop("TCP", None)
        return copy

    if others(before) != others(after):
        raise BoardError("转发变更与既有配置不一致，请核查记录", 409)
    actual = after.get("Web", {}).get(host, {}).get("Handlers", {}).get("/")
    if (enable and actual != expected) or (not enable and actual is not None):
        raise BoardError("私网转发状态尚未确认", 409)
    return {"managed_proxy": True, "enabled": enable, "changed": True}


def run_service(state: Path):
    if (state/'MIGRATED_TO.json').exists():
        raise BoardError('此状态已迁往NAS，禁止重新启动PC写实例',409)
    settings = read(state / "_private/server.json")
    record_path = state / "service.json"
    process = psutil.Process()
    stop_file=state/'stop.flag'
    if stop_file.exists():stop_file.unlink()
    prior_signal={}
    if __import__('threading').current_thread() is __import__('threading').main_thread():
        for sig in (signal.SIGTERM,signal.SIGINT):
            prior_signal[sig]=signal.signal(sig,lambda *_:stop_file.touch())
    record = {
        "pid": process.pid,
        "created": process.create_time(),
        "executable": process.exe(),
        "command": process.cmdline(),
        "purpose": "user-requested persistent cross-computer task board",
        "state": str(state),
        "started": time.time(),
        "ready": False,
        "closed": False,
    }
    write(record_path, record)
    try:
        store = BoardStore(state / "board.sqlite")
        store.verify()
        if not settings.get("project_state"):
            raise BoardError("先执行init进行项目隔离迁移，拒绝以旧授权模式启动")
        ProjectHub(state).verify()

        def ready(port):
            record.update(ready=True, port=port, public_url=settings["public_url"])
            write(record_path, record)

        serve(store, settings["port"], settings, state / "stop.flag", ready)
    finally:
        record.update(ready=False, closed=True, finished=time.time())
        write(record_path, record)
        for sig,handler in prior_signal.items():signal.signal(sig,handler)


def start(state: Path) -> dict:
    state = state.resolve()
    if (state/'MIGRATED_TO.json').exists():
        raise BoardError('此状态已迁往NAS，禁止重新启动PC写实例',409)
    record_path = state / "service.json"
    if record_path.exists():
        record = read(record_path)
        if exact_owner(record):
            if not record.get("ready"):
                raise BoardError("现有实例尚未就绪，不能重复启动", 409)
            proxy(state, True)
            return {"reused": True, "pid": record["pid"], "url": record["public_url"]}
    settings = read(state / "_private/server.json")
    with socket.socket() as probe:
        probe.settimeout(0.2)
        if probe.connect_ex(("127.0.0.1", settings["port"])) == 0:
            raise BoardError("端口由未知服务占用，不能替换", 409)
    stop = state / "stop.flag"
    if stop.exists():
        stop.unlink()
    proxy(state, True)
    command = [
        sys.executable,
        "-B",
        "-X",
        "utf8",
        str(ROOT / "tools/task_board.py"),
        "--state",
        str(state),
        "serve",
    ]
    startup = None
    flags = 0
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        flags = subprocess.CREATE_NO_WINDOW
    with (state / "service.stdout.log").open("ab") as out, (
        state / "service.stderr.log"
    ).open("ab") as err:
        child = subprocess.Popen(
            command,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            startupinfo=startup,
            creationflags=flags,
        )
    parent = {
        "pid": child.pid,
        "command": command,
        "purpose": "persistent board requested by user",
        "started": time.time(),
    }
    try:
        try:
            parent["created"] = psutil.Process(child.pid).create_time()
        except psutil.NoSuchProcess:
            parent["already_exited"] = True
        write(state / "start.json", parent)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise BoardError("服务启动失败，参看本实例日志")
            if record_path.exists():
                record = read(record_path)
                if record["pid"] == child.pid and record.get("ready"):
                    return {
                        "started": True,
                        "pid": child.pid,
                        "url": settings["public_url"],
                    }
            time.sleep(0.1)
        raise BoardError("公告板就绪检查超时")
    except BaseException:
        stop.touch()
        try:
            child.wait(15)
        except subprocess.TimeoutExpired:
            actual = psutil.Process(child.pid)
            if abs(actual.create_time() - parent["created"]) < 0.01:
                child.kill()
                child.wait(5)
        proxy(state, False)
        raise


def stop(state: Path) -> dict:
    record = read(state / "service.json")
    process = exact_owner(record)
    if process:
        (state / "stop.flag").touch()
        try:
            process.wait(20)
        except psutil.TimeoutExpired:
            raise BoardError(
                "服务未按时关闭，保留身份记录；未按进程名清理", 409
            ) from None
    elif not record.get("closed"):
        raise BoardError("PID身份已变化，拒绝操作其他进程", 409)
    proxy_result = proxy(state, False)
    return {
        "stopped": True,
        "pid": record["pid"],
        "record": str(state / "service.json"),
        "proxy": proxy_result,
    }


def operator_portal(state: Path, out: Path | None = None, project: str = "sampleapp") -> dict:
    settings = read(state / "_private/server.json")
    hub = ProjectHub(state)
    hub.metadata(project)
    profile = read(state / "_private/admin.json")
    actor = hub.admin_store.authenticate(profile["token"])
    ticket = hub.admin_store.create_ticket(actor)
    url = (
        settings["public_url"] + "/?project=" + project + "#kind=admin&access=" + ticket
    )
    out = out or state / "_private/operator.html"
    import html

    content = (
        '<!doctype html><meta charset="utf-8"><meta name="referrer" content="no-referrer"><title>多项目公告板 · 管理入口</title><p><a href="'
        + html.escape(url, quote=True)
        + '">进入公告板并启用审核</a></p><p>此入口含一次性审核授权，仅供项目负责人使用，不提交Git或转发给开发Agent。</p>'
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf8", newline="\n")
    os.chmod(out, 0o600)
    return {
        "operator_portal": str(out),
        "expires_in_seconds": 86400,
        "secret_printed": False,
    }
