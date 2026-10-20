"""Strict batch acceptance and stop policy; no server requests."""

import copy
import unittest
from unittest.mock import Mock

from concurrency_experiment import run_prepared_batch, run_schedule
from concurrency_test_fixtures import successful_batch
from probe import build_payload
from test_concurrency_experiment import DIGEST, residency


class BatchValidationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.payload = build_payload(
            "test-model", prompt="fixture", num_ctx=4096, num_predict=64
        )

    def prepare(self, measured):
        control = Mock(return_value={"status": "success"})
        verify = Mock(side_effect=[
            residency(False), residency(True), residency(True),
        ])
        runner = Mock(return_value=measured)
        snapshots = []
        report = run_prepared_batch(
            self.payload, DIGEST, 2,
            checkpoint=snapshots.append,
            control=control, verify=verify, batch_runner=runner,
        )
        self.assertEqual(verify.call_count, 3)
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(snapshots[-1], report)
        return report

    def test_complete_success_evidence_is_accepted(self):
        measured = successful_batch(self.payload, 2)
        original = copy.deepcopy(measured)
        report = self.prepare(measured)
        self.assertEqual(report["status"], "success")
        self.assertNotIn("batch_validation_error", report)
        self.assertEqual(measured, original)

    def test_invalid_success_evidence_is_retained_and_rejected(self):
        original = successful_batch(self.payload, 2)
        for kind in ("missing", "nonfinite", "duration", "metric"):
            with self.subTest(kind=kind):
                measured = copy.deepcopy(original)
                if kind == "missing":
                    del measured["requests"][0]["client_total_s"]
                elif kind == "nonfinite":
                    measured["release_monotonic_s"] = float("inf")
                elif kind == "duration":
                    measured["requests"][0]["client_total_s"] += 1
                else:
                    measured["metrics"]["batch_duration_s"] += 1
                before = copy.deepcopy(measured)
                report = self.prepare(measured)
                self.assertEqual(report["status"], "error")
                self.assertEqual(report["batch"]["status"], "success")
                self.assertIn("batch_validation_error", report)
                self.assertEqual(report["batch"], before)
                self.assertEqual(measured, before)

    def test_inconsistent_success_stops_schedule_without_retry(self):
        calls = []
        verify = Mock(side_effect=[
            residency(False), residency(True), residency(True),
        ])
        control = Mock(return_value={"status": "success"})

        def batch_runner(payload, concurrency, *, checkpoint):
            calls.append(concurrency)
            measured = successful_batch(payload, concurrency)
            measured["metrics"]["median_completion_s"] += 1
            checkpoint(measured)
            return measured

        def prepared(payload, digest, concurrency, *, checkpoint):
            return run_prepared_batch(
                payload, digest, concurrency,
                checkpoint=checkpoint,
                control=control, verify=verify,
                batch_runner=batch_runner,
            )

        snapshots = []
        summary = run_schedule(
            self.payload, DIGEST,
            checkpoint=snapshots.append, prepared_runner=prepared,
        )
        self.assertEqual(summary["status"], "stopped")
        self.assertEqual(calls, [1])
        self.assertEqual(len(summary["batches"]), 1)
        self.assertEqual(summary["batches"][0]["status"], "error")
        self.assertEqual(verify.call_count, 3)
        self.assertIn("batch_validation_error", snapshots[-1])


if __name__ == "__main__":
    unittest.main()
