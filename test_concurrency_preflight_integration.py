"""Offline integration tests; Git boundaries are mocked, not bypassed in production."""

import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from concurrency_preflight import build_offline_execution_preflight
from concurrency_run_store import FIXTURE, MANIFEST, offline_plan


ROOT = Path(__file__).resolve().parent


class OfflineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.plan = offline_plan(ROOT)
        self.provenance = {
            "execution_commit": "test-commit",
            "file_sha256": {
                "docs/concurrency-protocol-v1.md":
                    self.plan["protocol_sha256"],
                str(FIXTURE): self.plan["prompt_sha256"],
                str(MANIFEST): self.plan["manifest_sha256"],
            },
            "untracked_paths": [],
        }
        self.capture = self.enterContext(patch(
            "concurrency_provenance.capture_provenance",
            return_value=self.provenance,
        ))
        self.verify = self.enterContext(patch(
            "concurrency_provenance.verify_provenance",
            return_value=self.provenance,
        ))

    def test_success_retains_plan_and_provenance_without_authorization(self):
        record = build_offline_execution_preflight(ROOT)
        self.assertEqual(record["status"], "success")
        self.assertFalse(record["live_enabled"])
        self.assertFalse(record["plan"]["live_enabled"])
        self.assertEqual(record["plan"], self.plan)
        self.assertEqual(record["execution_provenance"], self.provenance)
        self.assertIn("environment_evidence", record["pending_checks"])
        self.capture.assert_called_once_with(ROOT)
        self.verify.assert_called_once_with(ROOT, self.provenance)
        record["execution_provenance"]["file_sha256"].clear()
        self.assertTrue(self.provenance["file_sha256"])

    def test_capture_failure_prevents_planning(self):
        self.capture.side_effect = ValueError("Uncommitted input")
        with patch("concurrency_run_store.offline_plan") as planner:
            with self.assertRaisesRegex(ValueError, "Uncommitted"):
                build_offline_execution_preflight(ROOT)
            planner.assert_not_called()
        self.verify.assert_not_called()

    def test_each_input_hash_mismatch_is_rejected(self):
        baseline = copy.deepcopy(self.provenance)
        for name in baseline["file_sha256"]:
            with self.subTest(name=name):
                changed = copy.deepcopy(baseline)
                changed["file_sha256"][name] = "wrong"
                self.capture.return_value = changed
                with self.assertRaisesRegex(ValueError, "Plan input"):
                    build_offline_execution_preflight(ROOT)
        self.verify.assert_not_called()

    def test_revision_change_at_final_boundary_propagates(self):
        self.verify.side_effect = ValueError("Execution provenance changed")
        with self.assertRaisesRegex(ValueError, "provenance changed"):
            build_offline_execution_preflight(ROOT)

    def test_calibration_uses_separate_offline_schedule(self):
        record = build_offline_execution_preflight(ROOT, "calibration")
        self.assertEqual(record["plan"]["mode"], "calibration")
        self.assertEqual(record["plan"]["batch_count"], 3)
        self.assertEqual(record["plan"]["request_count"], 7)
        self.assertFalse(record["live_enabled"])


if __name__ == "__main__":
    unittest.main()
