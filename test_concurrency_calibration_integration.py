"""Offline adapter integration; no production transports or live evidence."""

import json
import unittest
from unittest.mock import patch

import concurrency_calibration as adapter
import test_concurrency_calibration as wiring_tests
from concurrency_test_fixtures import successful_batch
from test_concurrency_experiment import DIGEST, residency


class CalibrationIntegrationTests(unittest.TestCase):
    # Reuse the mocked preflight, temporary directory, and explicit fakes.
    setUp = wiring_tests.CalibrationAdapterTests.setUp
    run_adapter = wiring_tests.CalibrationAdapterTests.run_adapter

    def configure_success(self):
        self.calls = []

        def control(model, action, **kwargs):
            self.assertEqual(model, "test-model")
            self.calls.append(action)
            if action == "load":
                self.assertEqual(kwargs["num_ctx"], 4096)
            return {"status": "success"}

        def verify(digest, present):
            self.assertEqual(digest, DIGEST)
            self.calls.append("present" if present else "absent")
            return residency(present)

        def batch(payload, concurrency, *, checkpoint):
            self.calls.append(("batch", concurrency))
            result = successful_batch(payload, concurrency)
            checkpoint(result)
            return result

        self.control.side_effect = control
        self.verify.side_effect = verify
        self.batch.side_effect = batch

    def journal(self):
        return json.loads(
            (self.directory / "journal.json").read_text()
        )

    def saved_batch(self, journal, index=0):
        name = journal["batches"][index]["file"]
        return json.loads((self.directory / name).read_text())

    def test_valid_simulated_evidence_completes_three_batches(self):
        self.configure_success()
        summary = self.run_adapter()

        self.assertEqual(summary["status"], "complete")
        expected = []
        for concurrency in (1, 2, 4):
            expected.extend([
                "unload", "absent", "load", "present",
                ("batch", concurrency), "present",
            ])
        self.assertEqual(self.calls, expected)
        self.assertEqual(self.control.call_count, 6)
        self.assertEqual(self.verify.call_count, 9)
        self.assertEqual(self.batch.call_count, 3)

        journal = self.journal()
        self.assertEqual(journal["status"], "complete")
        self.assertEqual(
            sum(
                len(self.saved_batch(journal, i)["batch"]["requests"])
                for i in range(3)
            ),
            7,
        )
        for i in range(3):
            report = self.saved_batch(journal, i)
            self.assertEqual(report["status"], "success")
            self.assertNotIn("batch_validation_error", report)
        self.assertIs(
            journal["summary"]["execution_authorized"], False
        )

    def test_invalid_success_evidence_stops_after_postcheck(self):
        self.configure_success()

        def invalid_batch(payload, concurrency, *, checkpoint):
            result = successful_batch(payload, concurrency)
            # Claimed success without the required request outcomes.
            result["requests"] = []
            checkpoint(result)
            return result

        self.batch.side_effect = invalid_batch
        summary = self.run_adapter()

        self.assertEqual(summary["status"], "stopped")
        self.assertEqual(len(summary["batches"]), 1)
        self.assertEqual(self.batch.call_count, 1)
        self.assertEqual(self.verify.call_count, 3)
        saved = self.saved_batch(self.journal())
        self.assertEqual(saved["status"], "error")
        self.assertEqual(saved["batch"]["status"], "success")
        self.assertIn("batch_validation_error", saved)
        self.assertEqual(
            saved["preparation"][-1]["kind"], "verify_present_after"
        )

    def test_interrupted_batch_is_preserved(self):
        self.configure_success()

        def interrupted(payload, concurrency, *, checkpoint):
            result = {
                "status": "interrupted",
                "concurrency": concurrency,
                "requests": [],
            }
            checkpoint(result)
            return result

        self.batch.side_effect = interrupted
        summary = self.run_adapter()

        self.assertEqual(summary["status"], "stopped")
        self.assertEqual(len(summary["batches"]), 1)
        self.assertEqual(summary["batches"][0]["status"], "interrupted")
        self.assertEqual(self.batch.call_count, 1)
        self.assertEqual(self.verify.call_count, 3)
        journal = self.journal()
        self.assertEqual(journal["status"], "stopped")
        saved = self.saved_batch(journal)
        self.assertEqual(saved["status"], "interrupted")
        self.assertEqual(saved["batch"]["status"], "interrupted")

    def test_between_batch_provenance_failure_prevents_next_visit(self):
        self.configure_success()
        self.provenance.side_effect = [
            {},  # Before report creation.
            {},  # Before the first prepared batch.
            ValueError("Changed between batches"),
        ]

        with patch.object(adapter.RunReports, "finish") as finish:
            with self.assertRaisesRegex(ValueError, "between batches"):
                self.run_adapter()
            finish.assert_not_called()

        self.assertEqual(self.batch.call_count, 1)
        self.assertEqual(self.control.call_count, 2)
        self.assertEqual(self.verify.call_count, 3)
        journal = self.journal()
        self.assertEqual(journal["status"], "running")
        self.assertEqual(len(journal["batches"]), 1)
        self.assertNotIn("summary", journal)

    def test_final_provenance_failure_prevents_finalization(self):
        self.configure_success()
        self.provenance.side_effect = [
            {}, {}, {}, {},
            ValueError("Changed before finalization"),
        ]

        with patch.object(adapter.RunReports, "finish") as finish:
            with self.assertRaisesRegex(ValueError, "before finalization"):
                self.run_adapter()
            finish.assert_not_called()

        self.assertEqual(self.batch.call_count, 3)
        journal = self.journal()
        self.assertEqual(journal["status"], "running")
        self.assertNotIn("summary", journal)

    def test_finalization_storage_failure_propagates(self):
        self.configure_success()
        real_finish = adapter.RunReports.finish

        def fail_final_write(reports, summary):
            with patch.object(
                reports.journal_store, "checkpoint",
                side_effect=OSError("Injected final write failure"),
            ):
                return real_finish(reports, summary)

        with patch.object(adapter.RunReports, "finish", fail_final_write):
            with self.assertRaisesRegex(OSError, "final write failure"):
                self.run_adapter()

        self.assertEqual(self.batch.call_count, 3)
        # The persisted journal must not claim completion.
        journal = self.journal()
        self.assertEqual(journal["status"], "running")
        self.assertNotIn("summary", journal)


if __name__ == "__main__":
    unittest.main()
