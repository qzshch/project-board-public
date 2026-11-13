"""Loopback API, identity, stale writes, browser guards and portable client."""

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

from task_board.server import BoardServer
from task_board.store import BoardStore

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "board_portable_client", ROOT / "tools/task_board_client.py"
)
portable = importlib.util.module_from_spec(spec)
spec.loader.exec_module(portable)


class HttpCase(unittest.TestCase):
    def setUp(self):
        parent = Path(
            os.environ.get(
                "PROJECT_BOARD_TEST_ROOT", str(ROOT / "evidence/task-board-tests")
            )
        )
        parent.mkdir(parents=True, exist_ok=True)
        self.folder = tempfile.TemporaryDirectory(dir=parent)
        self.directory = Path(self.folder.name)
        self.store = BoardStore(self.directory / "board.sqlite")
        self.root = self.store.register_actor("root", "reviewer")
        self.agent = self.store.register_actor("agent-one")
        self.proxy = "test-board.example.ts.net:18785"
        self.server = BoardServer(
            ("127.0.0.1", 0),
            self.store,
            {
                "join_key": "local-join-test",
                "proxy_hosts": [self.proxy],
                "allowed_tailnet_logins": ["allowed-user"],
                "allowed_origins": ["http://" + self.proxy],
                "proxy_https": False,
                "access_log": str(self.directory / "access.jsonl"),
            },
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.02}
        )
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)
        self.opener = build_opener(ProxyHandler({}))
        actor = self.store.authenticate(self.root["token"])
        self.store.apply(
            actor,
            {
                "request_id": str(uuid.uuid4()),
                "task_id": "test/task",
                "action": "create",
                "expected_revision": 0,
                "payload": {
                    "spec": {
                        "id": "test/task",
                        "title": "API限定测试",
                        "kind": "test",
                        "description": "只测试公告板",
                        "deliverables": [{"id": "D1", "label": "API交付"}],
                        "registered": True,
                        "claimable": True,
                    },
                    "reason": "隔离测试",
                },
            },
        )

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        self.assertFalse(self.thread.is_alive())
        self.folder.cleanup()

    def call(self, path, payload=None, *, token=None, headers=None, raw=None):
        h = {**(headers or {})}
        if token:
            h["Authorization"] = "Bearer " + token
        data = (
            raw
            if raw is not None
            else json.dumps(payload).encode() if payload is not None else None
        )
        if data is not None:
            h.setdefault("Content-Type", "application/json")
        request = Request(self.url + path, data=data, headers=h)
        try:
            with self.opener.open(request, timeout=3) as response:
                return response.status, dict(response.headers), response.read()
        except HTTPError as error:
            return error.code, dict(error.headers), error.read()

    def event(self, action, payload):
        state = self.store.get("test/task")
        return {
            "request_id": str(uuid.uuid4()),
            "task_id": "test/task",
            "action": action,
            "expected_revision": state["revision"],
            "scope_version": state["scope_version"],
            "payload": payload,
        }

    def test_local_read_and_unauthenticated_write(self):
        self.assertEqual(self.call("/api/snapshot")[0], 200)
        self.assertEqual(
            self.call("/api/events", self.event("note", {"summary": "无身份"}))[0], 401
        )

    def test_tailnet_reader_is_allowlisted_and_host_scoped(self):
        good = {"Host": self.proxy, "Tailscale-User-Login": "allowed-user"}
        self.assertEqual(self.call("/api/snapshot", headers=good)[0], 200)
        self.assertEqual(
            self.call(
                "/api/snapshot", headers={**good, "Tailscale-User-Login": "other-user"}
            )[0],
            401,
        )
        self.assertEqual(
            self.call("/api/snapshot", headers={"Host": self.proxy})[0], 401
        )

    def test_unknown_host_and_cross_site_post_refused(self):
        self.assertEqual(
            self.call("/api/snapshot", headers={"Host": "evil.example"})[0], 403
        )
        self.assertEqual(
            self.call(
                "/api/events",
                self.event("note", {"summary": "跨站"}),
                token=self.root["token"],
                headers={"Origin": "https://evil.example"},
            )[0],
            403,
        )

    def test_enrollment_can_never_request_reviewer_role(self):
        header = {"Host": self.proxy, "Tailscale-User-Login": "allowed-user"}
        status, _, body = self.call(
            "/api/enroll", {"actor": "remote-agent"}, headers=header
        )
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(body)["role"], "agent")
        self.assertEqual(
            self.call(
                "/api/enroll",
                {"actor": "remote-other", "role": "reviewer"},
                headers=header,
            )[0],
            400,
        )
        self.assertEqual(
            self.call("/api/enroll", {"actor": "root"}, headers=header)[0], 403
        )

    def test_local_join_requires_specific_key(self):
        self.assertEqual(self.call("/api/enroll", {"actor": "new-agent"})[0], 401)
        self.assertEqual(
            self.call(
                "/api/enroll", {"actor": "new-agent", "join_key": "local-join-test"}
            )[0],
            201,
        )
        self.assertEqual(
            self.call(
                "/api/enroll", {"actor": "new-agent", "join_key": "local-join-test"}
            )[0],
            409,
        )

    def test_post_cannot_forge_actor_or_root_role(self):
        value = self.event("note", {"summary": "真实作者"})
        value["actor"] = "root"
        self.assertEqual(
            self.call("/api/events", value, token=self.agent["token"])[0], 400
        )
        self.assertEqual(
            self.call(
                "/api/events", self.event("merge", {}), token=self.agent["token"]
            )[0],
            403,
        )

    def test_duplicate_json_and_bad_content_type_refused(self):
        self.assertEqual(
            self.call("/api/enroll", raw=b'{"actor":"x","actor":"y"}')[0], 400
        )
        self.assertEqual(
            self.call("/api/enroll", raw=b"{}", headers={"Content-Type": "text/plain"})[
                0
            ],
            415,
        )
        self.assertEqual(self.call("/api/enroll", raw=b'{"actor":NaN}')[0], 400)

    def test_static_whitelist_prevents_reading_private_state(self):
        for path in (
            "/_private/reviewer.json",
            "/../board.sqlite",
            "/board.sqlite",
            "/client.py/../../server.py",
        ):
            self.assertEqual(self.call(path)[0], 404)
        self.assertEqual(self.call("/client.py")[0], 200)

    def test_snapshot_etag_and_no_token_in_public_projection(self):
        status, headers, body = self.call("/api/snapshot")
        self.assertEqual(status, 200)
        self.assertNotIn(self.root["token"].encode(), body)
        self.assertEqual(
            self.call("/api/snapshot", headers={"If-None-Match": headers["ETag"]})[0],
            304,
        )
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_api_conflict_does_not_add_event(self):
        value = self.event("note", {"summary": "首次"})
        self.assertEqual(
            self.call("/api/events", value, token=self.agent["token"])[0], 201
        )
        value["request_id"] = str(uuid.uuid4())
        self.assertEqual(
            self.call("/api/events", value, token=self.agent["token"])[0], 409
        )
        self.assertEqual(self.store.head()["seq"], 2)

    def test_reviewer_ticket_cookie_one_use_and_logout(self):
        reviewer = self.store.authenticate(self.root["token"])
        ticket = self.store.create_ticket(reviewer)
        status, headers, _ = self.call("/api/session", {"ticket": ticket})
        self.assertEqual(status, 200)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        self.assertEqual(self.call("/api/session", {"ticket": ticket})[0], 401)
        _, _, body = self.call("/api/me", headers={"Cookie": cookie})
        self.assertEqual(json.loads(body)["role"], "reviewer")
        self.call("/api/logout", {}, headers={"Cookie": cookie})
        self.assertEqual(self.call("/api/verify", headers={"Cookie": cookie})[0], 401)

    def test_access_log_excludes_body_authorization_and_ticket(self):
        ticket = self.store.create_ticket(self.store.authenticate(self.root["token"]))
        self.call("/api/session", {"ticket": ticket})
        self.call("/api/me", token=self.agent["token"])
        log = (self.directory / "access.jsonl").read_text("utf8")
        self.assertNotIn(ticket, log)
        self.assertNotIn(self.agent["token"], log)

    def test_portable_client_keeps_fixed_request_across_lost_response(self):
        profile = {**self.agent, "url": self.url}
        client = portable.Client(self.url, profile)
        original = client.call
        calls = []

        def lose_once(path, payload=None):
            result = original(path, payload)
            calls.append(1)
            if len(calls) == 1:
                raise portable.ClientError("模拟提交后丢响应")
            return result

        client.call = lose_once
        request = self.event("note", {"summary": "恰一次说明"})
        result = client.post(
            request, self.directory / "identity.json", self.directory / "receipt.json"
        )
        self.assertTrue(result["replayed"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(self.store.history("test/task")), 2)
        self.assertFalse(list((self.directory / "outbox/agent-one").glob("*.json")))

    def test_client_keeps_conflicted_outbox_and_never_rebases_it(self):
        client = portable.Client(self.url, {**self.agent, "url": self.url})
        request = self.event("note", {"summary": "旧版本"})
        request["expected_revision"] = 0
        with self.assertRaises(portable.ClientError) as caught:
            client.post(request, self.directory / "identity.json")
        self.assertEqual(caught.exception.status, 409)
        pending = list((self.directory / "outbox/agent-one").glob("*.json"))
        self.assertEqual(len(pending), 1)
        self.assertEqual(portable.read(pending[0]), request)

    def test_profile_cannot_be_sent_to_another_board(self):
        with self.assertRaises(portable.ClientError):
            portable.Client(self.url, {**self.agent, "url": "http://127.0.0.1:1"})

    def test_explicit_tailnet_ip_preserves_canonical_proxy_host(self):
        import io

        client = portable.Client(
            "http://board.example.ts.net:18785", connect_ip="100.64.0.11"
        )
        observed = []

        class StubOpener:
            def open(self, request, timeout):
                observed.append((request.full_url, request.get_header("Host")))
                return io.BytesIO(b'{"ready":true}')

        client.opener = StubOpener()
        self.assertTrue(client.call("/health")["ready"])
        self.assertEqual(
            observed,
            [("http://100.64.0.11:18785/health", "board.example.ts.net:18785")],
        )
        with self.assertRaises(portable.ClientError):
            portable.Client(
                "http://board.example.ts.net:18785", connect_ip="192.168.1.1"
            )


if __name__ == "__main__":
    unittest.main()
