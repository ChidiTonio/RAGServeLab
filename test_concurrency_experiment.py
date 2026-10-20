"""Offline preparation and stop-policy tests."""

import unittest
from unittest.mock import Mock

from concurrency_experiment import (
    CALIBRATION_SCHEDULE, SCHEDULE, run_prepared_batch, run_schedule,
)
from probe import build_payload
from concurrency_test_fixtures import successful_batch


DIGEST = "test-digest"


def residency(present, context=4096):
    return {
        "model_digest": DIGEST,
        "expected_present": present,
        "status": "success",
        "observations": [{
            "status": "success", "present": present,
            "response": {"models": (
                [{"digest": DIGEST, "context_length": context}]
                if present else []
            )},
        }],
    }


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.payload = build_payload(
            "test-model", prompt="fixture", num_ctx=4096, num_predict=64
        )
        self.calls = []
        self.snapshots = []

    def control(self, model, action, **kwargs):
        self.calls.append(action)
        if action == "load":
            self.assertEqual(kwargs["num_ctx"], 4096)
        return {"status": "success"}

    def verify(self, digest, present):
        self.assertEqual(digest, DIGEST)
        self.calls.append("present" if present else "absent")
        return residency(present)

    def batch(self, payload, concurrency, *, checkpoint):
        self.calls.append("batch")
        pending = {
            "status": "pending", "concurrency": concurrency, "requests": [],
        }
        checkpoint(pending)
        result = successful_batch(payload, concurrency)
        checkpoint(result)
        return result

    def run_prepared(self, **overrides):
        options = {
            "checkpoint": self.snapshots.append,
            "control": self.control,
            "verify": self.verify,
            "batch_runner": self.batch,
        }
        options.update(overrides)
        return run_prepared_batch(
            self.payload, DIGEST, 2, **options
        )

    def test_preparation_order_and_postcheck(self):
        report = self.run_prepared()
        self.assertEqual(report["status"], "success")
        self.assertEqual(
            self.calls, ["unload", "absent", "load", "present", "batch", "present"]
        )
        self.assertEqual(self.snapshots[0]["status"], "pending")
        self.assertIsNone(self.snapshots[0]["batch"])

    def test_failed_unload_prevents_verification_and_batch(self):
        control = Mock(return_value={"status": "error"})
        verify, batch = Mock(), Mock()
        report = self.run_prepared(
            control=control, verify=verify, batch_runner=batch
        )
        self.assertEqual(report["status"], "error")
        self.assertEqual(control.call_count, 1)
        verify.assert_not_called()
        batch.assert_not_called()

    def test_wrong_context_prevents_measurement(self):
        verify = Mock(side_effect=[
            residency(False), residency(True, context=2048),
        ])
        batch = Mock()
        report = self.run_prepared(verify=verify, batch_runner=batch)
        self.assertEqual(report["status"], "error")
        self.assertIn("validation_error", report["preparation"][-1])
        batch.assert_not_called()

    def test_postcheck_failure_retains_successful_measurement(self):
        verify = Mock(side_effect=[
            residency(False), residency(True), {"status": "error"},
        ])
        report = self.run_prepared(verify=verify)
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["batch"]["status"], "success")

    def test_failed_batch_is_postchecked_without_retry(self):
        batch = Mock(return_value={
            "status": "error", "concurrency": 2,
            "requests": [{"request_id": 1, "status": "error"}],
        })
        report = self.run_prepared(batch_runner=batch)
        self.assertEqual(report["status"], "error")
        self.assertEqual(batch.call_count, 1)
        self.assertEqual(self.calls[-1], "present")

    def test_interrupted_batch_remains_interrupted_after_failed_postcheck(self):
        verify = Mock(side_effect=[
            residency(False), residency(True), {"status": "error"},
        ])
        batch = Mock(return_value={
            "status": "interrupted", "concurrency": 2, "requests": [],
        })
        report = self.run_prepared(verify=verify, batch_runner=batch)
        self.assertEqual(report["status"], "interrupted")
        self.assertEqual(report["batch"]["status"], "interrupted")
        self.assertEqual(
            report["preparation"][-1]["kind"], "verify_present_after"
        )
        self.assertEqual(
            report["preparation"][-1]["record"]["status"], "error"
        )
        self.assertEqual(self.snapshots[-1], report)
        batch.assert_called_once()

    def test_initial_persistence_failure_prevents_operations(self):
        control = Mock()
        def fail(report):
            raise OSError("storage failure")
        with self.assertRaisesRegex(OSError, "storage failure"):
            self.run_prepared(checkpoint=fail, control=control)
        control.assert_not_called()

    def test_mid_preparation_persistence_failure_stops_operations(self):
        count = 0
        def fail(report):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("storage failure")
        with self.assertRaises(OSError):
            self.run_prepared(checkpoint=fail)
        self.assertEqual(self.calls, ["unload"])


class ScheduleTests(unittest.TestCase):
    def test_balanced_schedule_counts(self):
        self.assertEqual(len(SCHEDULE), 6)
        self.assertEqual(sum(len(row) for row in SCHEDULE), 18)
        self.assertEqual(sum(sum(row) for row in SCHEDULE), 42)
        for position in range(3):
            self.assertEqual(
                sorted(row[position] for row in SCHEDULE),
                [1, 1, 2, 2, 4, 4],
            )
        self.assertEqual(CALIBRATION_SCHEDULE, ((1, 2, 4),))

    def test_complete_schedule_has_ordered_identities(self):
        calls, snapshots = [], []
        def runner(payload, digest, concurrency, *, checkpoint):
            calls.append(concurrency)
            report = {"status": "success", "concurrency": concurrency}
            checkpoint(report)
            return report
        summary = run_schedule(
            {}, DIGEST, checkpoint=snapshots.append, prepared_runner=runner
        )
        self.assertEqual(summary["status"], "complete")
        self.assertEqual(calls, [c for row in SCHEDULE for c in row])
        self.assertEqual(len(summary["batches"]), 18)
        self.assertEqual(
            [(r["block"], r["position"]) for r in summary["batches"]],
            [(b, p) for b in range(1, 7) for p in range(1, 4)],
        )

    def test_first_failure_stops_schedule(self):
        runner = Mock(return_value={"status": "error", "concurrency": 1})
        summary = run_schedule(
            {}, DIGEST, checkpoint=lambda report: None,
            prepared_runner=runner,
        )
        self.assertEqual(summary["status"], "stopped")
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(len(summary["batches"]), 1)

    def test_persistence_failure_prevents_next_batch(self):
        runner = Mock(return_value={"status": "success", "concurrency": 1})
        def fail(report):
            raise OSError("storage failure")
        with self.assertRaises(OSError):
            run_schedule(
                {}, DIGEST, checkpoint=fail, prepared_runner=runner
            )
        self.assertEqual(runner.call_count, 1)


if __name__ == "__main__":
    unittest.main()
