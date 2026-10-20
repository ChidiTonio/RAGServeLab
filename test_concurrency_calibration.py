"""Offline adapter wiring tests; provenance is deliberately mocked."""

import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

import concurrency_calibration as adapter
from probe import build_payload


class CalibrationAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / "run"
        self.preflight = {
            "status": "success",
            "live_enabled": False,
            "plan": {
                "mode": "calibration",
                "live_enabled": False,
                "schedule": [[1, 2, 4]],
                "batch_count": 3,
                "request_count": 7,
                "payload": build_payload(
                    "test-model", prompt="fixture",
                    num_ctx=4096, num_predict=64,
                ),
                "model_digest": "test-digest",
            },
            "execution_provenance": {
                "execution_commit": "test-only",
                "file_sha256": {},
            },
        }
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(
            adapter, "build_offline_execution_preflight",
            return_value=self.preflight,
        ))
        self.provenance = self.stack.enter_context(patch.object(
            adapter, "verify_provenance",
            return_value=self.preflight["execution_provenance"],
        ))
        # None of these dependencies can reach a real transport.
        self.control = Mock(return_value={"status": "error"})
        self.verify = Mock(side_effect=AssertionError(
            "Unexpected residency fake call"
        ))
        self.batch = Mock(side_effect=AssertionError(
            "Unexpected batch fake call"
        ))

    def run_adapter(self):
        return adapter.run_offline_calibration(
            self.root, self.directory,
            control=self.control,
            verify=self.verify,
            batch_runner=self.batch,
        )

    def test_explicit_calibration_schedule_and_saved_flags(self):
        visits = []

        def prepared(payload, digest, concurrency, *, checkpoint, **kwargs):
            visits.append(concurrency)
            self.assertIs(kwargs["control"], self.control)
            self.assertIs(kwargs["verify"], self.verify)
            self.assertIs(kwargs["batch_runner"], self.batch)
            report = {"concurrency": concurrency, "status": "success"}
            checkpoint(report)
            return report

        # Tests adapter wiring, not successful-batch validation.
        with patch.object(adapter, "run_prepared_batch", prepared):
            summary = self.run_adapter()

        self.assertEqual(visits, [1, 2, 4])
        self.assertEqual(summary["status"], "complete")
        self.assertIs(summary["execution_authorized"], False)
        journal = json.loads(
            (self.directory / "journal.json").read_text()
        )
        self.assertEqual(len(journal["batches"]), 3)
        self.assertIs(journal["provenance"]["live_enabled"], False)
        self.assertIs(
            journal["provenance"]["execution_authorized"], False
        )
        self.control.assert_not_called()
        self.verify.assert_not_called()
        self.batch.assert_not_called()

    def test_real_preparation_failure_stops_after_first_visit(self):
        summary = self.run_adapter()
        self.assertEqual(summary["status"], "stopped")
        self.assertEqual(len(summary["batches"]), 1)
        self.assertEqual(summary["batches"][0]["status"], "error")
        self.control.assert_called_once_with("test-model", "unload")
        self.verify.assert_not_called()
        self.batch.assert_not_called()

    def test_checkpoint_failure_propagates_without_finalization(self):
        with patch.object(
            adapter.RunReports, "checkpoint",
            side_effect=OSError("Injected storage failure"),
        ), patch.object(adapter.RunReports, "finish") as finish:
            with self.assertRaisesRegex(OSError, "storage failure"):
                self.run_adapter()
            finish.assert_not_called()
        self.control.assert_not_called()
        self.verify.assert_not_called()
        self.batch.assert_not_called()

    def test_initial_provenance_failure_prevents_report_creation(self):
        self.provenance.side_effect = ValueError("Changed provenance")
        with self.assertRaisesRegex(ValueError, "Changed provenance"):
            self.run_adapter()
        self.assertFalse(self.directory.exists())
        self.control.assert_not_called()
        self.verify.assert_not_called()
        self.batch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
