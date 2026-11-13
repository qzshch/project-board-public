"""Actual two-project HTTP isolation, migration, browser sessions and revocation."""

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener
import uuid

from task_board.projects import ProjectHub
from task_board.server import BoardServer
from task_board.store import BoardStore, BoardError

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location(
    "project_portable", ROOT / "tools/task_board_client.py"
)
portable = importlib.util.module_from_spec(loader)
loader.loader.exec_module(portable)


class ProjectCase(unittest.TestCase):
    def setUp(self):
        parent = Path(
            os.environ.get(
                "PROJECT_BOARD_TEST_ROOT", str(ROOT / "evidence/task-board-tests")
            )
        )
        parent.mkdir(parents=True, exist_ok=True)
        self.folder = tempfile.TemporaryDirectory(dir=parent)
        self.state = Path(self.folder.name)
        original = BoardStore(self.state / "board.sqlite")
        self.legacy_root = original.register_actor("root", "reviewer")
        self.legacy_agent = original.register_actor("legacy-agent")
        self.hub = ProjectHub(self.state)
        self.hub.initialize("legacy-join-key", "http://127.0.0.1:1")
        self.admin = json.loads((self.state / "_private/admin.json").read_text("utf8"))
        self.identity = self.hub.resolve(self.admin["token"])
        for project in ("alpha", "beta"):
            self.hub.create(
                self.identity,
                {
                    "id": project,
                    "name": project + " private name",
                    "description": project + " confidential description",
                }, legacy_import=True,
            )
        self.a = self.hub.invite("alpha", "same-agent")
        self.b = self.hub.invite("beta", "same-agent")
        self.reviewer = self.hub.invite("alpha", "alpha-reviewer", "reviewer")
        self.receipts = {}
        for project in ("alpha", "beta"):
            self.receipts[project] = self.hub.store(project).apply(
                {"id": "root", "role": "reviewer"},
                {
                    "request_id": str(uuid.uuid4()),
                    "task_id": "plan/same",
                    "action": "create",
                    "expected_revision": 0,
                    "payload": {
                        "reason": "independent source",
                        "spec": {
                            "id": "plan/same",
                            "title": project + " private task",
                            "kind": "test",
                            "description": project + " secret rule",
                            "claimable": True,
                            "registered": True,
                            "deliverables": [{"id": "D1", "label": project + " only"}],
                        },
                    },
                },
            )
        self.server = BoardServer(
            ("127.0.0.1", 0),
            original,
            {
                "project_state": str(self.state),
                "proxy_hosts": ["board.example.ts.net:18785"],
                "allowed_tailnet_logins": ["same-user"],
                "access_log": str(self.state / "access.jsonl"),
            },
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}
        )
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)
        self.opener = build_opener(ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(3)
        self.server.server_close()
        self.folder.cleanup()

    def call(self, path, payload=None, profile=None, headers=None):
        headers = dict(headers or {})
        if profile:
            headers["Authorization"] = "Bearer " + profile["token"]
        if payload is not None:
            headers["Content-Type"] = "application/json"
        req = Request(
            self.url + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers,
        )
        try:
            with self.opener.open(req, timeout=5) as response:
                return response.status, json.load(response), dict(response.headers)
        except HTTPError as error:
            return error.code, json.loads(error.read() or b"{}"), dict(error.headers)

    def test_migration_preserves_legacy_history_and_limits_old_key(self):
        store = self.hub.store("sampleapp")
        before = store.head()
        self.hub.initialize("legacy-join-key", self.url)
        self.assertEqual(store.head(), before)
        self.assertEqual(
            self.call("/api/projects", profile=self.legacy_root)[1]["projects"][0][
                "id"
            ],
            "sampleapp",
        )
        self.assertEqual(
            self.call("/api/projects/alpha/snapshot", profile=self.legacy_root)[0], 404
        )
        self.assertEqual(self.call("/api/snapshot", profile=self.legacy_agent)[0], 200)

    def test_public_interface_docs_contain_no_project_snapshot(self):
        request = Request(self.url + "/api-docs.md")
        with self.opener.open(request, timeout=5) as response:
            value = response.read().decode("utf8")
        self.assertIn("/api/projects/{project_id}/", value)
        self.assertNotIn("alpha confidential", value)
        self.assertNotIn(self.a["token"], value)

    def test_health_and_project_connection_advertise_v2(self):
        self.assertEqual(self.call("/health")[1]["api_version"], 2)
        connection = self.call("/api/projects/alpha/connection", profile=self.a)[1]
        self.assertEqual(connection["api_version"], 2)
        self.assertEqual(connection["project_id"], "alpha")

    def test_agent_project_list_contains_only_its_project(self):
        status, value, _ = self.call("/api/projects", profile=self.a)
        self.assertEqual(status, 200)
        self.assertEqual([p["id"] for p in value["projects"]], ["alpha"])
        self.assertNotIn("beta", json.dumps(value))

    def test_admin_sees_projects_but_agent_cannot_create_one(self):
        self.assertEqual(
            len(self.call("/api/projects", profile=self.admin)[1]["projects"]), 3
        )
        value = {"id": "third", "name": "Third", "description": "New scope"}
        self.assertEqual(self.call("/api/projects", value, self.a)[0], 403)
        self.assertEqual(self.call("/api/projects", value, self.admin)[0], 201)
        self.assertEqual(self.call("/api/projects", value, self.admin)[0], 409)

    def test_loopback_and_tailnet_identity_are_not_project_grants(self):
        for path in ("/api/projects", "/api/snapshot", "/api/projects/alpha/snapshot"):
            self.assertEqual(self.call(path)[0], 401)
            self.assertEqual(
                self.call(
                    path,
                    headers={
                        "Host": "board.example.ts.net:18785",
                        "Tailscale-User-Login": "same-user",
                    },
                )[0],
                401,
            )

    def test_all_read_endpoints_refuse_foreign_project_before_data_or_etag(self):
        for suffix in (
            "",
            "/me",
            "/connection",
            "/snapshot",
            "/history?task=plan/same",
            "/task?id=plan/same",
            "/receipt?id=" + self.receipts["beta"]["event_id"],
            "/verify",
        ):
            with self.subTest(suffix=suffix):
                status, data, headers = self.call(
                    "/api/projects/beta" + suffix,
                    profile=self.a,
                    headers={"If-None-Match": '"beta:anything"'},
                )
                self.assertEqual(status, 404)
                self.assertNotIn("ETag", headers)
                self.assertNotIn("secret", json.dumps(data))
                self.assertNotIn("description", data)
        absent = self.call("/api/projects/absent/snapshot", profile=self.a)[1]["error"]
        self.assertEqual(
            absent, self.call("/api/projects/beta/snapshot", profile=self.a)[1]["error"]
        )

    def test_same_task_ids_have_independent_sources_and_histories(self):
        a = self.call("/api/projects/alpha/snapshot", profile=self.a)[1]
        b = self.call("/api/projects/beta/snapshot", profile=self.b)[1]
        self.assertEqual(a["tasks"][0]["spec"]["title"], "alpha private task")
        self.assertNotIn("beta", json.dumps(a))
        self.assertNotEqual(a["head"], b["head"])
        for path in ("/task?id=plan/same", "/history"):
            self.assertNotIn(
                "beta",
                json.dumps(self.call("/api/projects/alpha" + path, profile=self.a)[1]),
            )

    def test_receipt_id_from_other_project_cannot_be_read(self):
        self.assertEqual(
            self.call(
                "/api/projects/alpha/receipt?id=" + self.receipts["beta"]["event_id"],
                profile=self.a,
            )[0],
            404,
        )

    def test_foreign_writes_revoke_and_role_forgery_are_refused(self):
        before = self.hub.store("beta").head()
        for suffix, payload in (
            ("events", {}),
            ("actors/revoke", {"actor": "same-agent", "reason": "bad"}),
            ("actors", {"actor": "new-agent", "role": "reviewer"}),
            ("access", {}),
        ):
            self.assertEqual(
                self.call("/api/projects/beta/" + suffix, payload, self.a)[0], 404
            )
        self.assertEqual(before, self.hub.store("beta").head())

    def test_legacy_route_and_query_cannot_change_project(self):
        self.assertEqual(
            self.call("/api/snapshot?project=alpha", profile=self.a)[0], 404
        )
        value = self.call("/api/projects/alpha/snapshot?project=beta", profile=self.a)[
            1
        ]
        self.assertEqual(value["project_id"], "alpha")
        self.assertNotIn("beta", json.dumps(value))

    def test_project_reviewer_cannot_become_global_or_issue_reviewers(self):
        self.assertEqual(
            self.call(
                "/api/projects",
                {"id": "xx", "name": "X", "description": "X"},
                self.reviewer,
            )[0],
            403,
        )
        self.assertEqual(
            self.call(
                "/api/projects/alpha/actors",
                {"actor": "new-reviewer", "role": "reviewer"},
                self.reviewer,
            )[0],
            403,
        )
        self.assertEqual(
            self.call("/api/projects/beta/snapshot", profile=self.reviewer)[0], 404
        )
        self.assertEqual(
            self.call(
                "/api/projects/alpha/actors", {"actor": "new-agent"}, self.reviewer
            )[0],
            201,
        )

    def test_revoking_same_named_actor_does_not_revoke_other_project(self):
        self.assertEqual(
            self.call(
                "/api/projects/alpha/actors/revoke",
                {"actor": "same-agent", "reason": "end test"},
                self.admin,
            )[0],
            200,
        )
        self.assertEqual(self.call("/api/projects", profile=self.a)[0], 401)
        self.assertEqual(
            self.call("/api/projects/beta/snapshot", profile=self.b)[0], 200
        )

    def test_enrollment_requires_project_invite_and_never_tailnet_alone(self):
        path = "/api/projects/alpha/enroll"
        self.assertEqual(
            self.call(
                path,
                {"actor": "joined-agent"},
                headers={
                    "Host": "board.example.ts.net:18785",
                    "Tailscale-User-Login": "same-user",
                },
            )[0],
            401,
        )
        key = json.loads(
            (self.state / "_private/enrollment/alpha.json").read_text("utf8")
        )["join_key"]
        self.assertEqual(
            self.call(
                "/api/projects/beta/enroll", {"actor": "joined-agent", "join_key": key}
            )[0],
            401,
        )
        status, profile, _ = self.call(path, {"actor": "joined-agent", "join_key": key})
        self.assertEqual(status, 201)
        self.assertEqual(
            self.call("/api/projects", profile=profile)[1]["projects"][0]["id"], "alpha"
        )
        self.assertEqual(
            self.call(
                path, {"actor": "forge-role", "join_key": key, "role": "reviewer"}
            )[0],
            400,
        )

    def test_agent_browser_session_is_project_only_and_cannot_review(self):
        status, access, _ = self.call("/api/projects/alpha/access", {}, self.a)
        self.assertEqual(status, 201)
        status, _, headers = self.call(
            "/api/projects/alpha/session", {"ticket": access["ticket"]}
        )
        self.assertEqual(status, 200)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertEqual(
            self.call("/api/projects/alpha/me", headers={"Cookie": cookie})[1]["role"],
            "agent",
        )
        self.assertEqual(
            self.call("/api/projects/beta/snapshot", headers={"Cookie": cookie})[0], 404
        )
        self.assertEqual(
            self.call("/api/projects/alpha/verify", headers={"Cookie": cookie})[0], 403
        )
        self.assertEqual(
            self.call("/api/projects/alpha/session", {"ticket": access["ticket"]})[0],
            401,
        )
        self.call("/api/logout", {}, headers={"Cookie": cookie})
        self.assertEqual(self.call("/api/projects", headers={"Cookie": cookie})[0], 401)

    def test_admin_ticket_has_global_scope_but_project_ticket_cannot_upgrade(self):
        actor = self.hub.admin_store.authenticate(self.admin["token"])
        ticket = self.hub.admin_store.create_ticket(actor)
        status, _, headers = self.call("/api/session", {"ticket": ticket})
        self.assertEqual(status, 200)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertEqual(
            len(self.call("/api/projects", headers={"Cookie": cookie})[1]["projects"]),
            3,
        )
        project_ticket = self.hub.store("alpha").create_ticket(
            self.hub.store("alpha").authenticate(self.a["token"]), allow_agent=True
        )
        self.assertEqual(self.call("/api/session", {"ticket": project_ticket})[0], 401)

    def test_etags_are_project_scoped_and_authorization_precedes_304(self):
        a = self.call("/api/projects/alpha/snapshot", profile=self.admin)[2]["ETag"]
        self.assertEqual(
            self.call(
                "/api/projects/alpha/snapshot",
                profile=self.a,
                headers={"If-None-Match": a},
            )[0],
            304,
        )
        self.assertEqual(
            self.call(
                "/api/projects/beta/snapshot",
                profile=self.a,
                headers={"If-None-Match": a},
            )[0],
            404,
        )
        self.assertNotEqual(
            a, self.call("/api/projects/beta/snapshot", profile=self.admin)[2]["ETag"]
        )

    def test_project_id_cannot_escape_storage_and_invalid_names_are_refused(self):
        for name in ("../escape", "a/b", "C:/temp", "UPPER", "a", "%2e%2e", "a\\b"):
            self.assertEqual(
                self.call(
                    "/api/projects",
                    {"id": name, "name": "bad", "description": "bad"},
                    self.admin,
                )[0],
                400,
            )
        self.assertEqual(
            self.call("/api/projects/alpha%2f../snapshot", profile=self.admin)[0], 400
        )
        self.assertTrue(self.hub.verify()["passed"])

    def test_same_request_id_is_independent_in_each_project(self):
        request = {
            "request_id": str(uuid.uuid4()),
            "task_id": "plan/same",
            "action": "note",
            "expected_revision": 1,
            "scope_version": 1,
            "payload": {"summary": "same request, independent boards"},
        }
        a = self.call("/api/projects/alpha/events", request, self.a)[1]
        b = self.call("/api/projects/beta/events", request, self.b)[1]
        self.assertNotEqual(a["event_id"], b["event_id"])
        self.assertTrue(
            self.call("/api/projects/alpha/events", request, self.a)[1]["replayed"]
        )

    def test_portable_profile_refuses_override_and_keeps_project_outbox(self):
        profile = {**self.a, "url": self.url}
        with self.assertRaises(portable.ClientError):
            portable.Client(self.url, profile, project="beta")
        client = portable.Client(self.url, profile)
        self.assertEqual(client.call("/api/snapshot")["project_id"], "alpha")
        request = {
            "request_id": str(uuid.uuid4()),
            "task_id": "plan/same",
            "action": "note",
            "expected_revision": 0,
            "scope_version": 1,
            "payload": {"summary": "stale"},
        }
        with self.assertRaises(portable.ClientError):
            client.post(request, self.state / "a.json")
        self.assertEqual(
            len(list((self.state / "outbox/alpha/same-agent").glob("*.json"))), 1
        )

    def test_editing_profile_project_does_not_change_server_grant(self):
        tampered = {**self.a, "url": self.url, "project_id": "beta"}
        with self.assertRaises(portable.ClientError) as caught:
            portable.Client(self.url, tampered).call("/api/snapshot")
        self.assertEqual(caught.exception.status, 404)

    def test_project_catalog_export_is_admin_only_and_credential_free(self):
        path = self.state / "public-catalog.json"
        with self.assertRaises(BoardError):
            self.hub.export_catalog(self.hub.resolve(self.a["token"]), path)
        self.hub.export_catalog(self.identity, path)
        data = path.read_text("utf8")
        for secret in (
            self.a["token"],
            self.b["token"],
            self.admin["token"],
            "join_hash",
            "token_hash",
        ):
            self.assertNotIn(secret, data)
        import sqlite3

        with self.hub.connection() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM audit")
        self.assertTrue(self.hub.verify()["passed"])


if __name__ == "__main__":
    unittest.main()
