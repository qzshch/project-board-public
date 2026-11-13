"""Transactional append-only board events and rebuildable task projections.

Contributor submissions are claims. Only reviewers accept, revise scope, merge
or record native acceptance. A SHA256 chain detects ordinary corruption; it is
not a security boundary against an administrator who controls the database.
"""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import secrets
import sqlite3
import time
import uuid

API_VERSION = 1
ZERO_HASH = "0" * 64
REVIEW_ACTIONS = {
    "create",
    "assign",
    "scope",
    "accept",
    "request_changes",
    "reopen",
    "merge",
    "native",
}
AGENT_ACTIONS = {"claim", "progress", "submit", "note", "scope_proposal"}


class BoardError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def canonical(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf8")).hexdigest()


def text(value, name: str, maximum: int = 4000) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise BoardError(name + "必须是非空且有长度上限的文字")
    return value.strip()


def fields(value, allowed, required=()) -> dict:
    if (
        type(value) is not dict
        or set(value) - set(allowed)
        or not set(required) <= set(value)
    ):
        raise BoardError("字段缺失或包含未声明字段")
    return value


def integer(value, name: str, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value < 2**53:
        raise BoardError(name + "必须是有界整数")
    return value


def identifiers(value, name: str, limit: int = 128) -> list[str]:
    if (
        type(value) is not list
        or len(value) > limit
        or any(type(x) is not str or len(x) > 180 for x in value)
    ):
        raise BoardError(name + "列表格式不正确")
    if len(set(value)) != len(value):
        raise BoardError(name + "不能重复")
    return value


def evidence(value) -> list[dict]:
    if type(value) is not list or not 1 <= len(value) <= 32:
        raise BoardError("需要1～32个证据引用")
    result = []
    for row in value:
        fields(row, {"path", "sha256", "label"}, {"path", "sha256"})
        if type(row["sha256"]) is not str or not re.fullmatch(
            "[0-9a-f]{64}", row["sha256"]
        ):
            raise BoardError("证据需SHA256完整摘要")
        result.append(
            {
                "path": text(row["path"], "证据路径", 1000),
                "sha256": row["sha256"],
                "label": text(row.get("label", "证据"), "证据标签", 200),
            }
        )
    return result


def task_spec(value: dict) -> dict:
    fields(
        value,
        {
            "id",
            "title",
            "kind",
            "description",
            "parents",
            "depends_on",
            "allowed_paths",
            "deliverables",
            "claimable",
            "registered",
            "source",
            "priority",
            "work",
        },
        {"id", "title", "kind", "description", "deliverables"},
    )
    task_id = text(value["id"], "任务ID", 160)
    if not re.fullmatch("[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}", task_id):
        raise BoardError("任务ID格式不正确")
    deliverables = value["deliverables"]
    if type(deliverables) is not list or not 1 <= len(deliverables) <= 64:
        raise BoardError("任务需1～64个约定交付项")
    output = []
    for row in deliverables:
        fields(row, {"id", "label"}, {"id", "label"})
        output.append(
            {
                "id": text(row["id"], "交付项ID", 100),
                "label": text(row["label"], "交付项", 2000),
            }
        )
    if len({x["id"] for x in output}) != len(output):
        raise BoardError("交付项ID重复")
    for flag in ("claimable", "registered"):
        if flag in value and type(value[flag]) is not bool:
            raise BoardError("任务开关必须是布尔值")
    source = value.get("source", {})
    if type(source) is not dict or len(canonical(source)) > 32768:
        raise BoardError("来源元数据格式不正确或超限")
    paths = identifiers(value.get("allowed_paths", []), "写目录")
    if any(
        PurePosixPath(p).is_absolute()
        or ".." in PurePosixPath(p).parts
        or ":" in p
        or "\\" in p
        for p in paths
    ):
        raise BoardError("写目录必须是无越界的工程相对路径")
    if (
        value["kind"] == "plan"
        and value.get("registered")
        and not re.fullmatch("[0-9a-f]{64}", str(source.get("packet_sha256", "")))
    ):
        raise BoardError("新规划卡需先冻结输入packet摘要才能登记")
    if (
        value["kind"] == "plan"
        and value.get("registered")
        and not re.fullmatch("[0-9a-f]{40}", str(source.get("base_commit", "")))
    ):
        raise BoardError("新规划卡需先冻结实现基点才能登记")
    work = value.get('work')
    if work is not None:
        from .governance import work_spec
        work = work_spec(work)
    return {
        "id": task_id,
        "title": text(value["title"], "任务名", 300),
        "kind": text(value["kind"], "任务类型", 60),
        "description": text(value["description"], "范围", 12000),
        "parents": identifiers(value.get("parents", []), "父任务"),
        "depends_on": identifiers(value.get("depends_on", []), "依赖"),
        "allowed_paths": paths,
        "deliverables": output,
        "claimable": value.get("claimable", False),
        "registered": value.get("registered", False),
        "source": source,
        "priority": text(value.get("priority", "P1"), "优先级", 20),
        **({'work': work} if work is not None else {}),
    }


def new_projection(spec: dict) -> dict:
    return {
        "spec": spec,
        "revision": 0,
        "scope_version": 1,
        "scope_hash": digest(spec),
        "owner": None,
        "status": "planned",
        "accepted": {},
        "findings": [],
        "round": 0,
        "latest_submission": None,
        "last_merge": None,
        "native": None,
        "latest_summary": "",
        "updated_at": "",
        "last_actor": "",
        "last_event": None,
    }


def reduce_event(current: dict | None, event: dict) -> dict:
    """Pure event projection used both for commits and independent replay audit."""
    kind, payload = event["kind"], event["payload"]
    if kind in ("import", "create"):
        state = new_projection(payload["spec"])
        if kind == "import":
            state["status"] = payload["status"]
            state["owner"] = payload.get("owner")
            state["imported_snapshot"] = payload["snapshot"]
    else:
        if current is None:
            raise BoardError("任务不存在", 404)
        state = deepcopy(current)
    if kind in ("claim", "assign"):
        state["owner"] = payload.get("owner", event["actor"])
        if state["status"] == "planned":
            state["status"] = "active"
        if kind == "assign" and payload.get("registered"):
            state["spec"]["registered"] = True
            state["scope_hash"] = digest(state["spec"])
    elif kind == "scope":
        state["prior_scope_count"] = state.get("prior_scope_count", 0) + 1
        state["spec"] = payload["spec"]
        state["scope_version"] += 1
        state["scope_hash"] = digest(state["spec"])
        state.update(
            status="planned",
            accepted={},
            latest_submission=None,
            findings=[],
            last_merge=None,
            native=None,
        )
    elif kind == "progress":
        if state["status"] == "planned":
            state["status"] = "active"
    elif kind == "submit":
        state["round"] += 1
        state["latest_submission"] = {
            **payload,
            "id": event["id"],
            "round": state["round"],
            "actor": event["actor"],
            "scope_version": state["scope_version"],
            "accepted": False,
        }
        state["status"] = "submitted"
    elif kind in ("request_changes", "reopen"):
        state["status"] = "changes_requested"
        for index, finding in enumerate(payload["findings"]):
            state["findings"].append(
                {
                    **finding,
                    "id": event["id"] + ":" + str(index + 1),
                    "submission": payload["submission"],
                    "open": True,
                }
            )

        if kind == "reopen":
            state["accepted"] = {
                k: v for k, v in state["accepted"].items() if v != payload["submission"]
            }
            if (
                state["latest_submission"]
                and state["latest_submission"]["id"] == payload["submission"]
            ):
                state["latest_submission"]["accepted"] = False
    elif kind == "accept":
        submission = state["latest_submission"]
        for item in payload["deliverable_ids"]:
            state["accepted"][item] = submission["id"]
        for finding in state["findings"]:
            if finding["id"] in submission.get("addresses", []):
                finding["open"] = False
        submission["accepted"] = True
        complete = {x["id"] for x in state["spec"]["deliverables"]} <= set(
            state["accepted"]
        )
        state["status"] = (
            "accepted"
            if complete and not any(f["open"] for f in state["findings"])
            else "partial_accepted"
        )
    elif kind == "merge":
        state["last_merge"] = {**payload, "event": event["id"]}
        state["status"] = (
            "merged" if state["status"] == "accepted" else "partial_merged"
        )
    elif kind == "native":
        state["native"] = {**payload, "event": event["id"]}
        state["status"] = (
            "native_accepted" if state["status"] == "merged" else "partial_native"
        )
    state["revision"] += 1
    state.update(
        updated_at=event["created_at"],
        last_actor=event["actor"],
        last_event=event["id"],
    )
    state["latest_summary"] = payload.get(
        "summary", payload.get("reason", state["latest_summary"])
    )
    return state


class BoardStore:
    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript(
                """
              CREATE TABLE IF NOT EXISTS actors(id TEXT PRIMARY KEY, role TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE);
              CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE,
                task_id TEXT NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL, role TEXT NOT NULL,
                created_at TEXT NOT NULL, payload TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL UNIQUE);
              CREATE INDEX IF NOT EXISTS event_task ON events(task_id,seq);
              CREATE TABLE IF NOT EXISTS requests(actor TEXT NOT NULL, request_id TEXT NOT NULL,
                digest TEXT NOT NULL, event_id TEXT NOT NULL, receipt TEXT NOT NULL, PRIMARY KEY(actor,request_id));
              CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, state TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS tickets(hash TEXT PRIMARY KEY, actor TEXT NOT NULL, expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, actor TEXT NOT NULL, expires REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS actor_audit(seq INTEGER PRIMARY KEY, actor TEXT NOT NULL,
                action TEXT NOT NULL, operator TEXT NOT NULL, reason TEXT NOT NULL, created REAL NOT NULL);
              CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
                BEGIN SELECT RAISE(ABORT,'events are append only'); END;
              CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
                BEGIN SELECT RAISE(ABORT,'events are append only'); END;
            """
            )

            from .governance import setup
            setup(db)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("PRAGMA synchronous=FULL")
            yield db
        finally:
            db.close()

    def register_actor(self, actor: str, role: str = "agent") -> dict:
        if not re.fullmatch("[a-z][a-z0-9_-]{1,47}", actor) or role not in (
            "agent",
            "reviewer",
        ):
            raise BoardError("身份格式或角色不正确")
        token = secrets.token_urlsafe(32)
        with self.connection() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "INSERT INTO actors VALUES(?,?,?)",
                    (actor, role, hashlib.sha256(token.encode()).hexdigest()),
                )
                db.execute(
                    "INSERT INTO actor_audit(actor,action,operator,reason,created) VALUES(?,?,?,?,?)",
                    (
                        actor,
                        "registered",
                        "enrollment" if role == "agent" else "bootstrap",
                        "单独身份登记",
                        time.time(),
                    ),
                )
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                raise BoardError(
                    "身份已存在；请复用原身份文件或由审核者处理", 409
                ) from None
        return {"actor": actor, "role": role, "token": token}

    def revoke_actor(self, reviewer: dict, actor_id: str, reason: str) -> dict:
        if reviewer["role"] != "reviewer" or actor_id == "root":
            raise BoardError("需要审核者；不能由此撤销root", 403)
        text(actor_id, "身份ID", 48)
        text(reason, "撤销原因")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if not db.execute(
                    "SELECT id FROM actors WHERE id=?", (actor_id,)
                ).fetchone():
                    raise BoardError("身份不存在", 404)
                db.execute(
                    "UPDATE actors SET token_hash=? WHERE id=?",
                    (hashlib.sha256(secrets.token_bytes(32)).hexdigest(), actor_id),
                )
                db.execute("DELETE FROM sessions WHERE actor=?", (actor_id,))
                db.execute(
                    "INSERT INTO actor_audit(actor,action,operator,reason,created) VALUES(?,?,?,?,?)",
                    (actor_id, "revoked", reviewer["id"], reason, time.time()),
                )
                db.commit()
            except BaseException:
                db.rollback()
                raise
        return {"revoked": actor_id, "history_preserved": True}

    def authenticate(self, token: str) -> dict:
        if type(token) is not str or len(token) > 256:
            raise BoardError("需要有效身份", 401)
        with self.connection() as db:
            row = db.execute(
                "SELECT id,role FROM actors WHERE token_hash=?",
                (hashlib.sha256(token.encode()).hexdigest(),),
            ).fetchone()
        if row is None:
            raise BoardError("身份无效", 401)
        return dict(row)

    def get(self, task_id: str) -> dict:
        with self.connection() as db:
            row = db.execute(
                "SELECT state FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
        if row is None:
            raise BoardError("任务不存在", 404)
        return json.loads(row["state"])

    def _append(self, db, actor: dict, task_id: str, kind: str, payload: dict) -> dict:
        prior = db.execute(
            "SELECT seq,hash FROM events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        event = {
            "seq": prior["seq"] + 1 if prior else 1,
            "id": "ev_" + uuid.uuid4().hex,
            "task_id": task_id,
            "kind": kind,
            "actor": actor["id"],
            "role": actor["role"],
            "created_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "payload": payload,
            "prev_hash": prior["hash"] if prior else ZERO_HASH,
        }
        event["hash"] = digest(event)
        db.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                event["seq"],
                event["id"],
                task_id,
                kind,
                event["actor"],
                event["role"],
                event["created_at"],
                canonical(payload),
                event["prev_hash"],
                event["hash"],
            ),
        )
        old = db.execute("SELECT state FROM tasks WHERE id=?", (task_id,)).fetchone()
        projected = reduce_event(json.loads(old["state"]) if old else None, event)
        db.execute(
            "INSERT INTO tasks VALUES(?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state",
            (task_id, canonical(projected)),
        )
        return self._receipt(event, projected)

    @staticmethod
    def _receipt(event, state) -> dict:
        return {
            "api_version": API_VERSION,
            "event_id": event["id"],
            "event_hash": event["hash"],
            "seq": event["seq"],
            "task_id": event["task_id"],
            "revision": state["revision"],
            "scope_version": state["scope_version"],
            "status": state["status"],
        }

    def import_tasks(self, actor: dict, entries: list[dict], snapshot: dict) -> int:
        if actor["role"] != "reviewer":
            raise BoardError("只有审核者可以导入基线", 403)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                count = 0
                for entry in entries:
                    spec = task_spec(entry["spec"])
                    old = db.execute(
                        "SELECT state FROM tasks WHERE id=?", (spec["id"],)
                    ).fetchone()
                    if old:
                        # Re-import is never allowed to erase post-import work.
                        continue
                    self._append(
                        db,
                        actor,
                        spec["id"],
                        "import",
                        {
                            "spec": spec,
                            "status": entry["status"],
                            "owner": entry.get("owner"),
                            "snapshot": snapshot,
                        },
                    )
                    count += 1
                db.commit()
                return count
            except BaseException:
                db.rollback()
                raise

    def apply(self, actor: dict, request: dict) -> dict:
        fields(
            request,
            {
                "request_id",
                "task_id",
                "action",
                "expected_revision",
                "scope_version",
                "payload",
            },
            {"request_id", "task_id", "action", "expected_revision", "payload"},
        )
        request_id = text(request["request_id"], "请求ID", 100)
        task_id = text(request["task_id"], "任务ID", 160)
        action = request["action"]
        if type(action) is not str or action not in REVIEW_ACTIONS | AGENT_ACTIONS:
            raise BoardError("未支持的事件类型")
        expected = integer(request["expected_revision"], "任务版本")
        request_digest = digest(request)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                from .governance import effective
                actor = effective(db, actor)
                if actor['project_role'] == 'viewer':
                    raise BoardError('此身份已移交管理职责或仅有读取权限',403)
                if action in REVIEW_ACTIONS and actor['role'] != 'reviewer':
                    raise BoardError('此操作需要本项目审核权限',403)
                prior = db.execute(
                    "SELECT digest,event_id,receipt FROM requests WHERE actor=? AND request_id=?",
                    (actor["id"], request_id),
                ).fetchone()
                if prior:
                    if prior["digest"] != request_digest:
                        raise BoardError("相同请求ID绑定了不同内容", 409)
                    result = json.loads(prior["receipt"])
                    result["replayed"] = True
                    db.rollback()
                    return result
                old = db.execute(
                    "SELECT state FROM tasks WHERE id=?", (task_id,)
                ).fetchone()
                state = json.loads(old["state"]) if old else None
                if (state["revision"] if state else 0) != expected:
                    raise BoardError(
                        "任务已变化，请重新读取后决定；不能覆盖其他人的更新", 409
                    )
                if action != "create" and state is None:
                    raise BoardError("任务不存在", 404)
                if action == "create" and state is not None:
                    raise BoardError("任务ID已存在", 409)
                if state and action not in ("note", "scope_proposal"):
                    if request.get("scope_version") != state["scope_version"]:
                        raise BoardError("任务范围版本已变化", 409)
                payload = self._validate(
                    db, actor, task_id, state, action, request["payload"]
                )
                result = self._append(db, actor, task_id, action, payload)
                db.execute(
                    "INSERT INTO requests VALUES(?,?,?,?,?)",
                    (
                        actor["id"],
                        request_id,
                        request_digest,
                        result["event_id"],
                        canonical(result),
                    ),
                )
                db.commit()
                return result
            except BaseException:
                db.rollback()
                raise

    def _validate(
        self,
        db,
        actor: dict,
        task_id: str,
        state: dict | None,
        action: str,
        payload: dict,
    ) -> dict:
        if type(payload) is not dict:
            raise BoardError("事件内容必须是对象")
        if action == "create":
            fields(payload, {"spec", "reason"}, {"spec", "reason"})
            spec = task_spec(payload["spec"])
            if spec["id"] != task_id:
                raise BoardError("任务范围ID不一致")
            self._check_dependencies(db, spec)
            return {"spec": spec, "reason": text(payload["reason"], "创建原因")}
        if action == "scope":
            fields(payload, {"spec", "reason"}, {"spec", "reason"})
            spec = task_spec(payload["spec"])
            if state['spec'].get('work'):
                from .governance import load
                prior=state['spec']['work']['contracts']
                newer=spec.get('work',{}).get('contracts',[])
                changes=load(db)['changes'].values()
                for old in set(prior)-set(newer):
                    if not any(c['contract']==old and c['replacement'] in newer and c['executed'] for c in changes):
                        raise BoardError('已有接口切换需先完成影响提案、确认和执行',409)
            if spec["id"] != task_id:
                raise BoardError("修改范围不能更换任务ID")
            self._check_dependencies(db, spec)
            return {"spec": spec, "reason": text(payload["reason"], "范围变更原因")}
        if action == "assign":
            fields(payload, {"owner", "reason", "registered"}, {"owner", "reason"})
            if state['spec'].get('work'):
                from .governance import blockers
                reasons=blockers(db,state,registry=getattr(self,'registry',None))
                if reasons:raise BoardError('；'.join(reasons),409)
            if not re.fullmatch("[a-z][a-z0-9_-]{1,47}", payload["owner"]):
                raise BoardError("负责人ID不正确")
            if type(payload.get("registered", False)) is not bool:
                raise BoardError("登记开关不正确")
            if (
                payload.get("registered")
                and state["spec"]["kind"] == "plan"
                and not re.fullmatch(
                    "[0-9a-f]{64}",
                    str(state["spec"]["source"].get("packet_sha256", "")),
                )
            ):
                raise BoardError("派发新规划卡前先冻结实际输入packet摘要")
            if payload.get("registered"):
                task_spec({**state["spec"], "registered": True})
            return {
                "owner": payload["owner"],
                "reason": text(payload["reason"], "派发/转交原因"),
                "registered": payload.get("registered", False),
            }
        if action == "claim":
            fields(payload, {"summary"}, {"summary"})
            if state['spec'].get('work'):
                from .governance import blockers
                reasons = blockers(db, state, actor, getattr(self,'registry',None))
                if reasons:
                    raise BoardError('；'.join(reasons),409)
            if state["owner"] not in (None, actor["id"]):
                raise BoardError("任务已有其他负责人", 409)
            if actor["role"] != "reviewer" and (
                not state["spec"]["claimable"] or not state["spec"]["registered"]
            ):
                raise BoardError("此范围需root先登记或属于集成人保留范围", 403)
            for dep in state["spec"]["depends_on"]:
                found = db.execute(
                    "SELECT state FROM tasks WHERE id=?", (dep,)
                ).fetchone()
                if not found or json.loads(found[0])["status"] not in (
                    "accepted",
                    "merged",
                    "native_accepted",
                    "baseline_merged",
                ):
                    raise BoardError("具体前置尚未验收：" + dep, 409)
            return {"summary": text(payload["summary"], "领取说明")}
        if action in ("note", "scope_proposal"):
            fields(payload, {"summary"}, {"summary"})
            return {"summary": text(payload["summary"], "说明")}
        if action in ("progress", "submit"):
            if state["owner"] != actor["id"]:
                raise BoardError("只有当前负责人可以上报进展/提交", 403)
            if actor["role"] != "reviewer" and not state["spec"]["registered"]:
                raise BoardError("此任务尚未登记实际输入范围，先由root固定范围", 403)
            if state["status"] in (
                "accepted",
                "merged",
                "native_accepted",
                "baseline_merged",
            ):
                raise BoardError(
                    "此范围已完成；请提交新FOLLOWUP或由审核者重新打开", 409
                )
        if action == "progress":
            fields(payload, {"summary"}, {"summary"})
            return {"summary": text(payload["summary"], "进展")}
        if action == "submit":
            fields(
                payload,
                {
                    "summary",
                    "completeness",
                    "deliverable_ids",
                    "implementation_commit",
                    "evidence",
                    "tests",
                    "remaining",
                    "addresses",
                },
                {
                    "summary",
                    "completeness",
                    "deliverable_ids",
                    "implementation_commit",
                    "evidence",
                    "tests",
                    "remaining",
                },
            )
            commit = payload["implementation_commit"]
            if type(commit) is not str or not re.fullmatch("[0-9a-f]{40}", commit):
                raise BoardError("提交需冻结40位实现提交或原件Git锚点")
            selected = identifiers(payload["deliverable_ids"], "已交付项")
            allowed = {x["id"] for x in state["spec"]["deliverables"]}
            if not selected or not set(selected) <= allowed:
                raise BoardError("提交必须对应约定范围内的交付项")
            mode = payload["completeness"]
            if mode not in ("partial", "full") or (
                mode == "full" and set(selected) != allowed
            ):
                raise BoardError("完整交付必须覆盖全部约定项")
            addresses = identifiers(payload.get("addresses", []), "返修项")
            open_findings = {f["id"] for f in state["findings"] if f["open"]}
            if not set(addresses) <= open_findings:
                raise BoardError("引用的返修项不存在或已关闭")
            return {
                "summary": text(payload["summary"], "提交说明"),
                "completeness": mode,
                "deliverable_ids": selected,
                "implementation_commit": commit,
                "evidence": evidence(payload["evidence"]),
                "tests": text(payload["tests"], "测试结果或不适用依据"),
                "remaining": text(payload["remaining"], "剩余范围"),
                "addresses": addresses,
            }
        latest = state["latest_submission"]
        if action in ("accept", "request_changes", "merge", "native"):
            if latest is None or payload.get("submission") != latest["id"]:
                raise BoardError(
                    "审核必须引用当前最新提交；旧记录保留但不能误验收", 409
                )
        if action in ("request_changes", "reopen"):
            fields(
                payload,
                {"submission", "reason", "findings"},
                {"submission", "reason", "findings"},
            )
            target = self._event(db, payload["submission"])
            if target["task_id"] != task_id or target["kind"] != "submit":
                raise BoardError("返修必须引用本任务的具体提交")
            if action == "request_changes" and state["status"] != "submitted":
                raise BoardError("当前没有待审核提交；已验收内容请使用重新打开", 409)
            if action == "reopen" and target["id"] not in state["accepted"].values():
                raise BoardError("只能重新打开当前范围内已验收的内容", 409)
            if (
                type(payload["findings"]) is not list
                or not 1 <= len(payload["findings"]) <= 32
            ):
                raise BoardError("返修需要明确问题和验收要求")
            findings = []
            for row in payload["findings"]:
                fields(
                    row, {"description", "acceptance"}, {"description", "acceptance"}
                )
                findings.append(
                    {
                        "description": text(row["description"], "问题"),
                        "acceptance": text(row["acceptance"], "返修验收"),
                    }
                )
            return {
                "submission": target["id"],
                "reason": text(payload["reason"], "返修原因"),
                "findings": findings,
            }
        if action == "accept":
            fields(
                payload,
                {"submission", "summary", "deliverable_ids", "evidence"},
                {"submission", "summary", "deliverable_ids", "evidence"},
            )
            selected = identifiers(payload["deliverable_ids"], "验收项")
            if state["status"] != "submitted":
                raise BoardError("当前没有待审核的新提交", 409)
            if not selected or not set(selected) <= set(latest["deliverable_ids"]):
                raise BoardError("只能验收此次实际提交的部分")
            if latest["scope_version"] != state["scope_version"]:
                raise BoardError("提交使用了旧范围")
            return {
                "submission": latest["id"],
                "summary": text(payload["summary"], "验收结论"),
                "deliverable_ids": selected,
                "evidence": evidence(payload["evidence"]),
            }
        if action in ("merge", "native"):
            allowed_status = (
                ("accepted", "partial_accepted")
                if action == "merge"
                else ("merged", "partial_merged")
            )
            if not latest["accepted"] or state["status"] not in allowed_status:
                raise BoardError("必须先验收再合入、先合入再记录原客户端验收", 409)
            fields(
                payload,
                {"submission", "summary", "commit", "evidence"},
                {"submission", "summary", "commit", "evidence"},
            )
            if type(payload["commit"]) is not str or not re.fullmatch(
                "[0-9a-f]{40}", payload["commit"]
            ):
                raise BoardError("需要完整提交锚点")
            if (
                action == "native"
                and payload["commit"] != state["last_merge"]["commit"]
            ):
                raise BoardError("原客户端证据必须对应已合入提交")
            return {
                "submission": latest["id"],
                "summary": text(payload["summary"], "结论"),
                "commit": payload["commit"],
                "evidence": evidence(payload["evidence"]),
            }
        raise BoardError("不支持的状态转换")

    def _check_dependencies(self, db, spec):
        graph = {
            row["id"]: json.loads(row["state"])["spec"]["depends_on"]
            for row in db.execute("SELECT id,state FROM tasks")
        }
        graph[spec["id"]] = spec["depends_on"]

        def visit(task, active):
            if task in active:
                raise BoardError("依赖形成循环")
            if task not in graph:
                raise BoardError("依赖任务不存在：" + task)
            for dep in graph[task]:
                visit(dep, active | {task})

        visit(spec["id"], set())

    @staticmethod
    def _event(db, event_id):
        row = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if row is None:
            raise BoardError("事件不存在", 404)
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        return result

    def receipt(self, event_id: str) -> dict:
        with self.connection() as db:
            db.execute("BEGIN")
            event = self._event(db, event_id)
            state = json.loads(
                db.execute(
                    "SELECT state FROM tasks WHERE id=?", (event["task_id"],)
                ).fetchone()[0]
            )
            db.rollback()
        return {
            "event": event,
            "current_revision": state["revision"],
            "scope_version": state["scope_version"],
            "current_submission_id": (state["latest_submission"] or {}).get("id"),
            "current_status": state["status"],
            "task": state,
        }

    def snapshot(self) -> dict:
        with self.connection() as db:
            db.execute("BEGIN")
            head = db.execute(
                "SELECT seq,hash FROM events ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            tasks = [
                json.loads(row[0])
                for row in db.execute("SELECT state FROM tasks ORDER BY id")
            ]
            db.rollback()
        return {
            "api_version": API_VERSION,
            "head": dict(head) if head else {"seq": 0, "hash": ZERO_HASH},
            "tasks": tasks,
        }

    def head(self) -> dict:
        with self.connection() as db:
            row = db.execute(
                "SELECT seq,hash FROM events ORDER BY seq DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else {"seq": 0, "hash": ZERO_HASH}

    def history(
        self, task_id: str | None = None, after: int = 0, limit: int = 100
    ) -> list[dict]:
        integer(after, "事件游标")
        integer(limit, "分页大小", 1)
        if limit > 1000:
            raise BoardError("分页最多1000项")
        with self.connection() as db:
            query = "SELECT * FROM events WHERE seq>?"
            args = [after]
            if task_id:
                query += " AND task_id=?"
                args.append(task_id)
            query += " ORDER BY seq LIMIT ?"
            args.append(limit)
            rows = [dict(row) for row in db.execute(query, args)]
        for row in rows:
            row["payload"] = json.loads(row["payload"])
        return rows

    def verify(self) -> dict:
        replay = {}
        previous = ZERO_HASH
        count = 0
        with self.connection() as db:
            db.execute("BEGIN")
            for row in db.execute("SELECT * FROM events ORDER BY seq"):
                event = dict(row)
                event["payload"] = json.loads(event["payload"])
                actual = event.pop("hash")
                if (
                    event["seq"] != count + 1
                    or event["prev_hash"] != previous
                    or digest(event) != actual
                ):
                    raise BoardError("事件链校验失败", 409)
                event["hash"] = actual
                replay[event["task_id"]] = reduce_event(
                    replay.get(event["task_id"]), event
                )
                previous = actual
                count += 1
            actual = {
                row["id"]: json.loads(row["state"])
                for row in db.execute("SELECT id,state FROM tasks")
            }
            if actual != replay:
                raise BoardError("当前投影与事件重放不一致", 409)
            db.rollback()
        return {
            "passed": True,
            "events": count,
            "tasks": len(replay),
            "head_hash": previous,
        }

    def export_events(self, path: Path) -> dict:
        """Export one consistent read snapshot without credentials or actor tokens."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        previous = ZERO_HASH
        with self.connection() as db:
            db.execute("BEGIN")
            with path.open("x", encoding="utf8", newline="\n") as handle:
                for raw in db.execute("SELECT * FROM events ORDER BY seq"):
                    event = dict(raw)
                    event["payload"] = json.loads(event["payload"])
                    actual = event.pop("hash")
                    if (
                        event["seq"] != count + 1
                        or event["prev_hash"] != previous
                        or digest(event) != actual
                    ):
                        raise BoardError("导出时事件链校验失败", 409)
                    event["hash"] = actual
                    handle.write(canonical(event) + "\n")
                    previous = actual
                    count += 1
            db.rollback()
        return {
            "exported": str(path),
            "events": count,
            "head_hash": previous,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "credentials_included": False,
        }

    def create_ticket(
        self, actor: dict, lifetime: int = 86400, *, allow_agent: bool = False
    ) -> str:
        if actor["role"] != "reviewer" and not (
            allow_agent and actor["role"] == "agent"
        ):
            raise BoardError("需要已认证的项目身份", 403)
        ticket = secrets.token_urlsafe(32)
        with self.connection() as db:
            db.execute(
                "INSERT INTO tickets VALUES(?,?,?,0)",
                (
                    hashlib.sha256(ticket.encode()).hexdigest(),
                    actor["id"],
                    time.time() + lifetime,
                ),
            )
        return ticket

    def redeem_ticket(self, ticket: str) -> str:
        if type(ticket) is not str or len(ticket) > 256:
            raise BoardError("授权入口无效", 401)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                key = hashlib.sha256(ticket.encode()).hexdigest()
                row = db.execute(
                    "SELECT * FROM tickets WHERE hash=?", (key,)
                ).fetchone()
                if not row or row["used"] or row["expires"] < time.time():
                    raise BoardError("授权入口已使用或过期，请重新生成", 401)
                token = secrets.token_urlsafe(32)
                db.execute("UPDATE tickets SET used=1 WHERE hash=?", (key,))
                db.execute(
                    "INSERT INTO sessions VALUES(?,?,?)",
                    (
                        hashlib.sha256(token.encode()).hexdigest(),
                        row["actor"],
                        time.time() + 8 * 3600,
                    ),
                )
                db.commit()
                return token
            except BaseException:
                db.rollback()
                raise

    def session_actor(self, token: str) -> dict:
        with self.connection() as db:
            row = db.execute(
                "SELECT a.id,a.role FROM sessions s JOIN actors a ON a.id=s.actor WHERE s.hash=? AND s.expires>?",
                (hashlib.sha256(token.encode()).hexdigest(), time.time()),
            ).fetchone()
        if not row:
            raise BoardError("审核会话已过期", 401)
        return dict(row)

    def logout(self, token: str):
        with self.connection() as db:
            db.execute(
                "DELETE FROM sessions WHERE hash=?",
                (hashlib.sha256(token.encode()).hexdigest(),),
            )
