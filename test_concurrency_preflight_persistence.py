"""Offline preflight persistence tests; no server requests."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from concurrency_preflight import persist_offline_preflight


ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "docs/concurrency-environment-evidence-20261020.json"


class PreflightPersistenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / "preflight"
        self.builder = self.enterContext(patch(
            "concurrency_preflight.build_offline_execution_preflight",
            return_value={
                "status": "success",
                "live_enabled": False,
                "pending_checks": ["authorized_live_connectivity_and_metadata"],
            },
        ))

    def run_check(self, evidence=EVIDENCE):
        return persist_offline_preflight(
            ROOT, evidence, self.directory, "measured"
        )

    def saved(self):
        return json.loads(
            (self.directory / "preflight.json").read_text(encoding="utf-8")
        )

    def test_completed_offline_checks_are_saved_without_authorization(self):
        report = self.run_check()
        self.assertEqual(report, self.saved())
        self.assertEqual(report["status"], "offline_checks_complete")
        self.assertFalse(report["live_enabled"])
        self.assertFalse(report["execution_authorized"])
        self.assertEqual(
            report["environment_evidence"]["status"], "recorded"
        )
        self.assertTrue(report["client_runtime"]["python_version"])
        self.assertEqual(
            len(report["environment_evidence_sha256"]), 64
        )
        self.assertEqual(list(self.directory.glob("*.tmp")), [])

    def test_provenance_failure_is_retained_with_environment_evidence(self):
        self.builder.side_effect = ValueError(
            "Required file is absent from execution commit"
        )
        report = self.run_check()
        self.assertEqual(report, self.saved())
        self.assertEqual(report["status"], "failed")
        self.assertEqual(
            report["error"]["stage"], "planning_and_execution_provenance"
        )
        self.assertIsNotNone(report["environment_evidence"])
        self.assertIsNone(report["execution_preflight"])

    def test_missing_evidence_is_saved_as_failure_without_planning(self):
        report = self.run_check(self.directory.parent / "missing.json")
        self.assertEqual(report, self.saved())
        self.assertEqual(report["status"], "failed")
        self.assertEqual(
            report["error"]["stage"], "environment_evidence"
        )
        self.builder.assert_not_called()

    def test_existing_directory_is_never_reused(self):
        self.run_check()
        original = (self.directory / "preflight.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.run_check()
        self.assertEqual(
            original, (self.directory / "preflight.json").read_bytes()
        )

    def test_checkpoint_failure_propagates_and_leaves_pending_report(self):
        with patch(
            "report_store.ReportStore.checkpoint",
            side_effect=OSError("Injected storage failure"),
        ):
            with self.assertRaisesRegex(OSError, "storage failure"):
                self.run_check()
        self.assertEqual(self.saved()["status"], "pending")


if __name__ == "__main__":
    unittest.main()
