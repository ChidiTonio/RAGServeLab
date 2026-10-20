"""Offline checks that inconsistent residency evidence stops orchestration."""

import copy
import unittest
from unittest.mock import Mock

from concurrency_experiment import run_prepared_batch
from probe import build_payload
from concurrency_test_fixtures import successful_batch
from test_concurrency_experiment import DIGEST, residency


class ResidencyIntegrationTests(unittest.TestCase):
    def run_records(self, records):
        snapshots = []
        control = Mock(return_value={"status": "success"})
        verify = Mock(side_effect=records)
        payload = build_payload(
            "test-model", prompt="fixture", num_ctx=4096, num_predict=64
        )
        measured = successful_batch(payload, 2)
        batch = Mock(return_value=measured)
        report = run_prepared_batch(
            payload, DIGEST, 2,
            checkpoint=snapshots.append,
            control=control,
            verify=verify,
            batch_runner=batch,
        )
        self.assertEqual(snapshots[-1], report)
        return report, control, verify, batch, snapshots

    def test_inconsistent_absence_stops_before_preload(self):
        for field, value in (
            ("model_digest", "wrong-digest"),
            ("expected_present", True),
        ):
            with self.subTest(field=field):
                bad = residency(False)
                bad[field] = value
                original = copy.deepcopy(bad)
                report, control, verify, batch, _ = self.run_records([bad])
                self.assertEqual(report["status"], "error")
                self.assertIsNone(report["batch"])
                self.assertEqual(control.call_count, 1)
                self.assertEqual(verify.call_count, 1)
                batch.assert_not_called()
                entry = report["preparation"][-1]
                self.assertEqual(entry["kind"], "verify_absent")
                self.assertEqual(entry["record"], original)
                self.assertIn("validation_error", entry)

    def test_absence_snapshot_contradiction_stops_before_preload(self):
        bad = residency(False)
        bad["observations"][-1]["response"]["models"] = [
            {"digest": DIGEST, "context_length": 4096}
        ]
        report, control, _, batch, _ = self.run_records([bad])
        self.assertEqual(report["status"], "error")
        self.assertEqual(control.call_count, 1)
        batch.assert_not_called()
        self.assertIn("validation_error", report["preparation"][-1])

    def test_inconsistent_presence_stops_before_measurement(self):
        for field, value in (
            ("model_digest", "wrong-digest"),
            ("expected_present", False),
        ):
            with self.subTest(field=field):
                bad = residency(True)
                bad[field] = value
                report, control, verify, batch, _ = self.run_records(
                    [residency(False), bad]
                )
                self.assertEqual(report["status"], "error")
                self.assertEqual(control.call_count, 2)
                self.assertEqual(verify.call_count, 2)
                batch.assert_not_called()
                self.assertIsNone(report["batch"])
                self.assertIn("validation_error", report["preparation"][-1])

    def test_inconsistent_postcheck_retains_measurement_and_evidence(self):
        bad = residency(True)
        bad["model_digest"] = "wrong-digest"
        original = copy.deepcopy(bad)
        report, control, verify, batch, snapshots = self.run_records(
            [residency(False), residency(True), bad]
        )
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["batch"]["status"], "success")
        self.assertEqual(len(report["batch"]["requests"]), 2)
        self.assertEqual(control.call_count, 2)
        self.assertEqual(verify.call_count, 3)
        self.assertEqual(batch.call_count, 1)
        entry = report["preparation"][-1]
        self.assertEqual(entry["kind"], "verify_present_after")
        self.assertEqual(entry["record"], original)
        self.assertIn("validation_error", entry)
        self.assertIsNone(snapshots[0]["batch"])


if __name__ == "__main__":
    unittest.main()