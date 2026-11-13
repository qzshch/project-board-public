"""Workflow and durable-concurrency tests; no game or external network access."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
import uuid

from task_board.store import BoardError, BoardStore
from task_board.catalog import import_catalog

ROOT = Path(__file__).resolve().parents[2]


class BoardCase(unittest.TestCase):
    def setUp(self):
        parent = Path(
            os.environ.get(
                "PROJECT_BOARD_TEST_ROOT", str(ROOT / "evidence/task-board-tests")
            )
        )
        parent.mkdir(parents=True, exist_ok=True)
        self.folder = tempfile.TemporaryDirectory(dir=parent)
        self.path = Path(self.folder.name) / "board.sqlite"
        self.store = BoardStore(self.path)
        self.root_profile = self.store.register_actor("root", "reviewer")
        self.agent_profile = self.store.register_actor("agent-one")
        self.other_profile = self.store.register_actor("agent-two")
        self.root = self.store.authenticate(self.root_profile["token"])
        self.agent = self.store.authenticate(self.agent_profile["token"])
        self.other = self.store.authenticate(self.other_profile["token"])
        self.spec = {
            "id": "plan/test",
            "title": "测试限定范围",
            "kind": "test",
            "description": "第一项与第二项分开交付",
            "deliverables": [
                {"id": "D1", "label": "第一项"},
                {"id": "D2", "label": "第二项"},
            ],
            "registered": True,
            "claimable": True,
        }
        self.create(self.spec)

    def tearDown(self):
        self.folder.cleanup()

    def create(self, spec):
        return self.store.apply(
            self.root,
            {
                "request_id": str(uuid.uuid4()),
                "task_id": spec["id"],
                "action": "create",
                "expected_revision": 0,
                "payload": {"spec": spec, "reason": "建立独立测试范围"},
            },
        )

    def action(self, actor, action, payload, task="plan/test", **overrides):
        current = self.store.get(task)
        event = {
            "request_id": str(uuid.uuid4()),
            "task_id": task,
            "action": action,
            "expected_revision": current["revision"],
            "scope_version": current["scope_version"],
            "payload": payload,
            **overrides,
        }
        return self.store.apply(actor, event)

    def claim(self):
        return self.action(self.agent, "claim", {"summary": "领取已登记范围"})

    def submit(self, items=None, **overrides):
        return self.action(
            self.agent,
            "submit",
            {
                "summary": "声明完成第一部分",
                "completeness": "partial",
                "deliverable_ids": items or ["D1"],
                "implementation_commit": "a" * 40,
                "evidence": [{"path": "G:/evidence/report.json", "sha256": "b" * 64}],
                "tests": "真实执行测试通过",
                "remaining": "第二部分继续进行",
                **overrides,
            },
        )

    def accept(self, submission, items=None):
        return self.action(
            self.root,
            "accept",
            {
                "submission": submission["event_id"],
                "summary": "按证据验收本次范围",
                "deliverable_ids": items or ["D1"],
                "evidence": [{"path": "G:/evidence/review.json", "sha256": "c" * 64}],
            },
        )

    def test_partial_acceptance_does_not_close_the_task(self):
        self.claim()
        submission = self.submit()
        self.accept(submission)
        state = self.store.get("plan/test")
        self.assertEqual(state["status"], "partial_accepted")
        self.assertEqual(set(state["accepted"]), {"D1"})

    def test_second_partial_can_complete_the_agreed_scope(self):
        self.claim()
        self.accept(self.submit())
        second = self.submit(["D2"])
        self.accept(second, ["D2"])
        self.assertEqual(self.store.get("plan/test")["status"], "accepted")

    def test_contributor_cannot_accept_or_merge(self):
        for action in (
            "accept",
            "merge",
            "native",
            "assign",
            "scope",
            "reopen",
            "create",
        ):
            with self.subTest(action=action), self.assertRaises(BoardError) as caught:
                self.action(self.agent, action, {})
            self.assertEqual(caught.exception.status, 403)

    def test_two_concurrent_claims_have_one_winner(self):
        gate = threading.Barrier(2)
        revision = self.store.get("plan/test")["revision"]

        def claim(actor):
            gate.wait()
            try:
                return self.action(
                    actor, "claim", {"summary": "并发领取"}, expected_revision=revision
                )["status"]
            except BoardError as exc:
                return exc.status

        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(claim, [self.agent, self.other]))
        self.assertEqual(values.count("active"), 1)
        self.assertEqual(values.count(409), 1)

    def test_idempotent_retry_returns_original_receipt_after_other_events(self):
        current = self.store.get("plan/test")
        event = {
            "request_id": "stable-test-id",
            "task_id": "plan/test",
            "action": "claim",
            "expected_revision": current["revision"],
            "scope_version": 1,
            "payload": {"summary": "一次领取"},
        }
        first = self.store.apply(self.agent, event)
        self.action(self.root, "note", {"summary": "另外一条说明"})
        second = self.store.apply(self.agent, event)
        second.pop("replayed")
        self.assertEqual(first, second)
        self.assertEqual(len(self.store.history("plan/test")), 3)

    def test_same_request_id_with_new_content_refused(self):
        current = self.store.get("plan/test")
        event = {
            "request_id": "fixed",
            "task_id": "plan/test",
            "action": "note",
            "expected_revision": current["revision"],
            "payload": {"summary": "原说明"},
        }
        self.store.apply(self.agent, event)
        event["payload"]["summary"] = "不同说明"
        with self.assertRaises(BoardError) as caught:
            self.store.apply(self.agent, event)
        self.assertEqual(caught.exception.status, 409)

    def test_owner_cannot_be_overridden_by_other_agent(self):
        self.claim()
        with self.assertRaises(BoardError):
            self.action(self.other, "progress", {"summary": "越权上报"})
        self.action(self.root, "assign", {"owner": "agent-two", "reason": "明确转交"})
        with self.assertRaises(BoardError):
            self.action(self.agent, "progress", {"summary": "旧负责人迟到"})

    def test_full_claim_requires_every_deliverable(self):
        self.claim()
        with self.assertRaises(BoardError):
            self.submit(completeness="full")
        self.assertIsNone(self.store.get("plan/test")["latest_submission"])

    def test_accept_cannot_expand_the_submitted_scope(self):
        self.claim()
        submission = self.submit()
        with self.assertRaises(BoardError):
            self.accept(submission, ["D1", "D2"])

    def test_old_submission_cannot_be_accepted_after_resubmit(self):
        self.claim()
        old = self.submit()
        self.submit()
        with self.assertRaises(BoardError):
            self.accept(old)

    def test_rework_rounds_preserve_history_and_close_only_after_review(self):
        self.claim()
        first = self.submit()
        self.action(
            self.root,
            "request_changes",
            {
                "submission": first["event_id"],
                "reason": "发现边界缺陷",
                "findings": [
                    {"description": "并发越界", "acceptance": "独立复现后新增回归"}
                ],
            },
        )
        finding = self.store.get("plan/test")["findings"][0]["id"]
        second = self.submit(addresses=[finding], implementation_commit="d" * 40)
        self.assertTrue(self.store.get("plan/test")["findings"][0]["open"])
        self.accept(second)
        self.assertFalse(self.store.get("plan/test")["findings"][0]["open"])
        self.assertEqual(
            [e["kind"] for e in self.store.history("plan/test")],
            ["create", "claim", "submit", "request_changes", "submit", "accept"],
        )

    def test_merge_then_reopen_retains_original_acceptance_events(self):
        self.claim()
        submission = self.submit()
        self.accept(submission)
        self.action(
            self.root,
            "merge",
            {
                "submission": submission["event_id"],
                "summary": "部分合入",
                "commit": "e" * 40,
                "evidence": [{"path": "review.json", "sha256": "f" * 64}],
            },
        )
        self.action(
            self.root,
            "reopen",
            {
                "submission": submission["event_id"],
                "reason": "发现遗漏",
                "findings": [{"description": "恢复缺陷", "acceptance": "跨进程复验"}],
            },
        )
        self.assertEqual(self.store.get("plan/test")["status"], "changes_requested")
        self.assertEqual(self.store.get("plan/test")["accepted"], {})
        self.assertTrue(self.store.verify()["passed"])

    def test_merge_and_native_are_separate_gates(self):
        self.claim()
        submission = self.submit()
        payload = {
            "submission": submission["event_id"],
            "summary": "验收",
            "commit": "e" * 40,
            "evidence": [{"path": "proof.json", "sha256": "f" * 64}],
        }
        with self.assertRaises(BoardError):
            self.action(self.root, "merge", payload)
        self.accept(submission)
        self.action(self.root, "merge", payload)
        with self.assertRaises(BoardError):
            self.action(self.root, "native", {**payload, "commit": "d" * 40})
        self.action(self.root, "native", payload)
        self.assertEqual(self.store.get("plan/test")["status"], "partial_native")

    def test_scope_change_rejects_stale_delivery_without_losing_old_events(self):
        self.claim()
        self.submit()
        spec = deepcopy(self.spec)
        spec["description"] = "经过审核的新范围"
        self.action(self.root, "scope", {"spec": spec, "reason": "追加明确范围"})
        with self.assertRaises(BoardError):
            self.action(
                self.agent, "progress", {"summary": "旧范围迟到"}, scope_version=1
            )
        self.assertEqual(self.store.get("plan/test")["scope_version"], 2)
        self.assertEqual(len(self.store.history("plan/test")), 4)

    def test_dependency_cycle_and_missing_reference_are_refused(self):
        other = deepcopy(self.spec)
        other["id"] = "plan/other"
        other["depends_on"] = ["plan/test"]
        self.create(other)
        changed = deepcopy(self.spec)
        changed["depends_on"] = ["plan/other"]
        with self.assertRaises(BoardError):
            self.action(self.root, "scope", {"spec": changed, "reason": "循环"})
        other["id"] = "plan/third"
        other["depends_on"] = ["plan/absent"]
        with self.assertRaises(BoardError):
            self.create(other)

    def test_planning_card_requires_packet_before_registration(self):
        spec = deepcopy(self.spec)
        spec.update(id="plan/new", kind="plan", registered=False)
        self.create(spec)
        with self.assertRaises(BoardError):
            self.action(
                self.root,
                "assign",
                {"owner": "agent-one", "reason": "派发", "registered": True},
                task="plan/new",
            )

    def test_assignment_without_registration_does_not_authorize_agent_submission(self):
        spec = deepcopy(self.spec)
        spec.update(id="plan/unregistered", kind="plan", registered=False)
        self.create(spec)
        self.action(
            self.root,
            "assign",
            {"owner": "agent-one", "reason": "先登记负责人，输入包未定"},
            task=spec["id"],
        )
        with self.assertRaises(BoardError):
            self.action(
                self.agent, "progress", {"summary": "不应开始"}, task=spec["id"]
            )

    def test_revoke_identity_preserves_old_project_events(self):
        self.claim()
        self.submit()
        head = self.store.head()
        self.store.revoke_actor(self.root, "agent-one", "本次身份结束")
        with self.assertRaises(BoardError):
            self.store.authenticate(self.agent_profile["token"])
        self.assertEqual(head, self.store.head())
        self.assertTrue(self.store.verify()["passed"])

    def test_receipt_exposes_current_submission_for_stale_handoff_rejection(self):
        self.claim()
        old = self.submit()
        new = self.submit()
        result = self.store.receipt(old["event_id"])
        self.assertEqual(result["event"]["id"], old["event_id"])
        self.assertEqual(result["current_submission_id"], new["event_id"])

    def test_export_is_a_frozen_credential_free_checkpoint(self):
        self.claim()
        self.submit()
        path = Path(self.folder.name) / "events.jsonl"
        proof = self.store.export_events(path)
        raw = path.read_bytes()
        rows = [json.loads(line) for line in raw.splitlines()]
        self.assertEqual(len(rows), 3)
        self.assertEqual(proof["head_hash"], rows[-1]["hash"])
        self.assertNotIn(self.agent_profile["token"].encode(), raw)
        self.assertNotIn(self.root_profile["token"].encode(), raw)
        self.action(self.root, "note", {"summary": "快照之后的新记录"})
        self.assertEqual(path.read_bytes(), raw)
        with self.assertRaises(FileExistsError):
            self.store.export_events(path)

    def test_blocked_predecessor_prevents_claim(self):
        spec = deepcopy(self.spec)
        spec.update(id="plan/dependent", depends_on=["plan/test"])
        self.create(spec)
        with self.assertRaises(BoardError):
            self.action(
                self.agent, "claim", {"summary": "前置未验收"}, task="plan/dependent"
            )

    def test_database_reopen_reconstructs_same_state(self):
        self.claim()
        self.submit()
        prior = self.store.snapshot()
        reopened = BoardStore(self.path)
        self.assertEqual(prior, reopened.snapshot())
        self.assertTrue(reopened.verify()["passed"])

    def test_events_update_delete_are_blocked_and_projection_corruption_detected(self):
        with self.store.connection() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE events SET actor='fake'")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM events")
            db.execute("UPDATE tasks SET state='{}'")
        with self.assertRaises(BoardError):
            self.store.verify()

    def test_all_catalog_layers_and_reimport_are_preserved(self):
        fixture = Path(self.folder.name) / "catalog.json"
        entries = [{"spec":{**self.spec,"id":"history/one"},"status":"reported"},
                   {"spec":{**self.spec,"id":"history/two"},"status":"baseline_merged"}]
        fixture.write_text(json.dumps({"entries":entries}),encoding="utf8")
        entries, snapshot = import_catalog(fixture)
        self.assertEqual(self.store.import_tasks(self.root, entries, snapshot), 2)
        self.assertEqual(sum(t["status"] == "reported" for t in self.store.snapshot()["tasks"]), 1)
        self.assertEqual(self.store.import_tasks(self.root, entries, snapshot), 0)
        self.assertTrue(self.store.verify()["passed"])

    def test_authentication_and_one_use_reviewer_session(self):
        with self.assertRaises(BoardError):
            self.store.authenticate("wrong")
        with self.assertRaises(BoardError):
            self.store.create_ticket(self.agent)
        ticket = self.store.create_ticket(self.root)
        session = self.store.redeem_ticket(ticket)
        self.assertEqual(self.store.session_actor(session)["role"], "reviewer")
        with self.assertRaises(BoardError):
            self.store.redeem_ticket(ticket)
        self.store.logout(session)
        with self.assertRaises(BoardError):
            self.store.session_actor(session)

    def test_input_types_and_unknown_fields_fail_without_writes(self):
        before = self.store.head()
        with self.assertRaises(BoardError):
            self.action(self.agent, "note", {"summary": "hello", "role": "reviewer"})
        with self.assertRaises(BoardError):
            self.action(self.agent, "note", None)
        with self.assertRaises(BoardError):
            self.action(self.agent, "note", {"summary": "x"}, expected_revision=True)
        self.assertEqual(before, self.store.head())


if __name__ == "__main__":
    unittest.main()
