"""Project catalog and server-side credentials bound to exactly one project.

Project task/event databases remain independent. Only the operator's separately
issued administrator identity can enumerate or create other projects. Tailnet
membership and loopback access are transport properties, never project grants.
"""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time

from .store import BoardError, BoardStore, canonical, fields, text


def project_id(value: str) -> str:
    if type(value) is not str or not re.fullmatch(r"[a-z][a-z0-9-]{1,47}", value):
        raise BoardError("项目ID需2～48位小写字母、数字或连字符，以字母开头")
    return value


def token_hash(value: str) -> str:
    if type(value) is not str or not 1 <= len(value) <= 256:
        raise BoardError("需要有效身份", 401)
    return hashlib.sha256(value.encode()).hexdigest()


class ProjectHub:
    def __init__(self, state: Path):
        self.state = Path(state).resolve()
        if (self.state/'MIGRATED_TO.json').exists():
            raise BoardError('此PC状态已迁往NAS，请使用NAS入口和状态目录',409)
        self.path = self.state / "projects.sqlite"
        self.admin_store = BoardStore(self.state / "_private/admin.sqlite")
        self._stores = {}
        self._lock = threading.Lock()
        with self.connection() as db:
            db.executescript(
                """
              CREATE TABLE IF NOT EXISTS projects(
                id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT NOT NULL,
                storage TEXT NOT NULL UNIQUE,join_hash TEXT NOT NULL,created REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS credentials(
                token_hash TEXT PRIMARY KEY,project TEXT NOT NULL,actor TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS removed_projects(id TEXT PRIMARY KEY,removed_at REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY,payload TEXT NOT NULL,
                prev_hash TEXT NOT NULL,hash TEXT NOT NULL UNIQUE);
              CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
                BEGIN SELECT RAISE(ABORT,'audit is append only'); END;
              CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
                BEGIN SELECT RAISE(ABORT,'audit is append only'); END;
            """
            )

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            yield db
        finally:
            db.close()

    def audit(self, db, action: str, project: str, actor: str, detail):
        prior = db.execute(
            "SELECT seq,hash FROM audit ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        value = {
            "seq": prior["seq"] + 1 if prior else 1,
            "action": action,
            "project": project,
            "actor": actor,
            "detail": detail,
            "at": time.time(),
        }
        previous = prior["hash"] if prior else "0" * 64
        digest = hashlib.sha256((previous + canonical(value)).encode()).hexdigest()
        db.execute(
            "INSERT INTO audit VALUES(?,?,?,?)",
            (value["seq"], canonical(value), previous, digest),
        )

    def initialize(self, legacy_join_key: str, public_url: str) -> None:
        """Additive migration: retain original DB, event IDs, receipts and hashes."""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM projects WHERE id='sampleapp'").fetchone():
                db.execute(
                    "INSERT INTO projects VALUES(?,?,?,?,?,?)",
                    (
                        "sampleapp",
                        "示例项目",
                        "离线重构：研究、候选、生产接线与原客户端验收分层记录",
                        "board.sqlite",
                        token_hash(legacy_join_key),
                        time.time(),
                    ),
                )
                self.audit(
                    db, "migrate", "sampleapp", "root", "保留原任务库；原凭据仅授权dhy"
                )
            db.commit()
        store = self.store("sampleapp")
        with store.connection() as source, self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in source.execute("SELECT id,token_hash FROM actors"):
                db.execute(
                    "INSERT OR IGNORE INTO credentials VALUES(?,?,?)",
                    (row["token_hash"], "sampleapp", row["id"]),
                )
            db.commit()
        profile = self.state / "_private/admin.json"
        if not profile.exists():
            identity = self.admin_store.register_actor("root", "reviewer")
            self.write_private(
                profile, {**identity, "url": public_url, "global_admin": True}
            )
        else:
            self.admin_store.authenticate(
                json.loads(profile.read_text("utf8"))["token"]
            )

    @staticmethod
    def write_private(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents replacing an existing credential by mistake.
        with path.open("x", encoding="utf8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(path, 0o600)

    def initialize_empty(self, public_url: str) -> dict:
        """Independent installations begin with no business projects."""
        profile = self.state / '_private/admin.json'
        if not profile.exists():
            actor = self.admin_store.register_actor('root', 'reviewer')
            self.write_private(profile, {**actor, 'url': public_url, 'global_admin': True})
        return self.resolve(json.loads(profile.read_text('utf8'))['token'])

    def metadata(self, project: str) -> dict:
        with self.connection() as db:
            row = db.execute(
                "SELECT id,name,description FROM projects WHERE id=?", (project,)
            ).fetchone()
        if not row:
            raise BoardError("项目不可用或未授权", 404)
        return dict(row)

    def store(self, project: str) -> BoardStore:
        project_id(project)
        with self._lock:
            if project not in self._stores:
                with self.connection() as db:
                    row = db.execute(
                        "SELECT storage FROM projects WHERE id=?", (project,)
                    ).fetchone()
                if not row:
                    raise BoardError("项目不可用或未授权", 404)
                relative = (
                    "board.sqlite"
                    if project == "sampleapp"
                    else f"projects/{project}/board.sqlite"
                )
                if row["storage"] != relative:
                    raise BoardError("项目存储身份不一致", 409)
                path = self.state / relative
                if not path.resolve().is_relative_to(self.state) or path.is_symlink():
                    raise BoardError("项目存储不能越界", 409)
                self._stores[project] = BoardStore(path)
                from .assets import Registry
                self._stores[project].registry = Registry(self, project)
            return self._stores[project]

    def resolve(self, token: str | None = None, session: str | None = None) -> dict:
        if token:
            digest = token_hash(token)
            try:
                actor = self.admin_store.authenticate(token)
                return {"global_admin": True, "actor": actor, "project_id": None}
            except BoardError:
                pass
            with self.connection() as db:
                row = db.execute(
                    "SELECT project FROM credentials WHERE token_hash=?", (digest,)
                ).fetchone()
            if not row:
                raise BoardError("需要有效身份", 401)
            project = row["project"]
            actor = self.store(project).authenticate(token)
            return {"global_admin": False, "actor": actor, "project_id": project}
        if session:
            if session.startswith("g."):
                actor = self.admin_store.session_actor(session[2:])
                return {"global_admin": True, "actor": actor, "project_id": None}
            if session.startswith("p."):
                parts = session.split(".", 2)
                if len(parts) != 3:
                    raise BoardError("需要有效身份", 401)
                project = project_id(parts[1])
                actor = self.store(project).session_actor(parts[2])
            else:
                project = "sampleapp"  # An original pre-migration cookie grants only sampleapp.
                actor = self.store(project).session_actor(session)
            return {"global_admin": False, "actor": actor, "project_id": project}
        raise BoardError("请使用本项目身份或管理员入口", 401)

    def authorize(self, identity: dict, project: str) -> dict:
        if not identity["global_admin"] and identity["project_id"] != project:
            raise BoardError("项目不可用或未授权", 404)
        return self.metadata(project)

    def list_projects(self, identity: dict) -> list[dict]:
        if not identity["global_admin"]:
            return [
                {
                    **self.metadata(identity["project_id"]),
                    "role": self.effective_actor(identity, identity['project_id'])["role"],
                    "project_role": self.effective_actor(identity, identity['project_id']).get('project_role'),
                }
            ]
        with self.connection() as db:
            return [
                {**dict(row), "role": "reviewer"}
                for row in db.execute(
                    "SELECT id,name,description FROM projects ORDER BY created,id"
                )
            ]

    def create(self, identity: dict, value: dict, *, legacy_import=False) -> dict:
        if not identity["global_admin"]:
            raise BoardError("需要全局管理员", 403)
        fields(value, {"id", "name", "description", "knowledge"}, {"id", "name", "description"})
        project = project_id(value["id"])
        name = text(value["name"], "项目名称", 200)
        description = text(value["description"], "项目说明", 4000)
        if 'knowledge' in value:
            from .governance import knowledge_spec
            knowledge_spec(value['knowledge'])
        secret = secrets.token_urlsafe(32)
        storage = f"projects/{project}/board.sqlite"
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM projects WHERE id=? UNION SELECT 1 FROM removed_projects WHERE id=?", (project,project)).fetchone():
                raise BoardError("项目ID已存在", 409)
            path = self.state / storage
            if path.exists() or not path.resolve().is_relative_to(self.state):
                raise BoardError("项目目录已存在或越界，未覆盖", 409)
            store = BoardStore(path)
            store.register_actor(
                "root", "reviewer"
            )  # Only admin can act as root; key discarded.
            # Existing/imported catalogs remain compatible. Every new API-created
            # project has planning gates even when its charter is still a draft.
            from .governance import Governance
            governance=Governance(store)
            if 'knowledge' in value:
                governance.apply({'id':'root','role':'reviewer'},{'request_id':'initial-knowledge','expected_revision':0,'action':'knowledge','payload':value['knowledge']})
            if not legacy_import:
                governance.apply({'id':'root','role':'reviewer'},{'request_id':'initial-planning','expected_revision':governance.snapshot()['revision'],'action':'planning_enable','payload':{'reason':'新项目默认启用项目规划与接口覆盖门禁'}})
            enrollment = self.state / f"_private/enrollment/{project}.json"
            self.write_private(enrollment, {"project_id": project, "join_key": secret})
            db.execute(
                "INSERT INTO projects VALUES(?,?,?,?,?,?)",
                (project, name, description, storage, token_hash(secret), time.time()),
            )
            self.audit(
                db,
                "create",
                project,
                identity["actor"]["id"],
                "独立空项目，不复制其他项目任务/凭据",
            )
            db.commit()
        return self.metadata(project)

    def enroll(self, project: str, actor: str, join_key: str) -> dict:
        with self.connection() as db:
            row = db.execute(
                "SELECT join_hash FROM projects WHERE id=?", (project,)
            ).fetchone()
        if not row or not secrets.compare_digest(
            row["join_hash"], token_hash(join_key)
        ):
            raise BoardError("需要有效的项目邀请码", 401)
        if actor == "root":
            raise BoardError("不能自助登记root", 403)
        return self.invite(project, actor, "agent", operator="project-enrollment")

    def invite(
        self, project: str, actor: str, role: str = "agent", operator: str = "root"
    ) -> dict:
        self.metadata(project)
        result = self.store(project).register_actor(actor, role)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO credentials VALUES(?,?,?)",
                (token_hash(result["token"]), project, actor),
            )
            self.audit(db, "invite", project, operator, {"actor": actor, "role": role})
            db.commit()
        return {**result, "project_id": project}

    def revoke(self, identity: dict, project: str, actor: str, reason: str) -> dict:
        self.authorize(identity, project)
        if not identity['global_admin']:
            from .governance import load, role
            with self.store(project).connection() as db:
                target=load(db)['members'].get(actor,{}).get('role')
                if target=='owner' or (target=='se' and role(db,identity['actor'])!='owner'):
                    raise BoardError('管理身份撤销需owner移交或全局恢复审计',403)
        result = self.store(project).revoke_actor(self.effective_actor(identity,project), actor, reason)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "DELETE FROM credentials WHERE project=? AND actor=?", (project, actor)
            )
            self.audit(
                db,
                "revoke",
                project,
                identity["actor"]["id"],
                {"actor": actor, "reason": reason},
            )
            db.commit()
        return result

    def effective_actor(self, identity, project):
        from .governance import effective
        with self.store(project).connection() as db:
            return effective(db, identity['actor'])

    def redeem(self, ticket: str, project: str | None = None) -> str:
        try:
            if project is None:
                return "g." + self.admin_store.redeem_ticket(ticket)
            return "p." + project + "." + self.store(project).redeem_ticket(ticket)
        except BoardError:
            raise BoardError("授权入口无效、已使用或过期", 401) from None

    def logout(self, session: str) -> None:
        if session.startswith("g."):
            self.admin_store.logout(session[2:])
        elif session.startswith("p."):
            parts = session.split(".", 2)
            if len(parts) == 3:
                self.store(project_id(parts[1])).logout(parts[2])
        else:
            self.store("sampleapp").logout(session)

    def verify(self) -> dict:
        previous = "0" * 64
        with self.connection() as db:
            rows = list(db.execute("SELECT * FROM audit ORDER BY seq"))
        for index, row in enumerate(rows, 1):
            value = json.loads(row["payload"])
            expected = hashlib.sha256(
                (previous + canonical(value)).encode()
            ).hexdigest()
            if (
                value["seq"] != index
                or row["prev_hash"] != previous
                or row["hash"] != expected
            ):
                raise BoardError("项目目录审计链不一致", 409)
            previous = expected
        return {"passed": True, "audit_events": len(rows), "audit_hash": previous}

    def export_catalog(self, identity: dict, path: Path) -> dict:
        if not identity["global_admin"]:
            raise BoardError("需要全局管理员", 403)
        with self.connection() as db:
            db.execute("BEGIN")
            projects = [
                dict(row)
                for row in db.execute(
                    "SELECT id,name,description,created FROM projects ORDER BY id"
                )
            ]
            audit = [
                dict(row)
                for row in db.execute(
                    "SELECT seq,payload,prev_hash,hash FROM audit ORDER BY seq"
                )
            ]
            db.commit()
        value = {
            "projects": projects,
            "audit": audit,
            "format": "project-catalog-v1; no credentials",
        }
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf8") as handle:
            handle.write(canonical(value) + "\n")
        return {
            "catalog": str(path),
            "projects": len(projects),
            "audit_events": len(audit),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
