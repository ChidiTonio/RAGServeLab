"""Offline interruption integration; no server requests."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from concurrency import run_batch
from concurrency_experiment import run_prepared_batch, run_schedule
from concurrency_run_store import RunReports, file_hash
from probe import build_payload
from test_concurrency_experiment import DIGEST, residency
from test_concurrency_interruptions import InterruptedStream


class InterruptionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.payload = build_payload(
            "test-model", prompt="fixture",
            num_ctx=4096, num_predict=64,
        )
        self.control = Mock(return_value={"status": "success"})
        self.opener = Mock(
            side_effect=lambda request, timeout: InterruptedStream(
                KeyboardInterrupt
            )
        )

    def batch(self, payload, concurrency, *, checkpoint):
        return run_batch(
            payload, concurrency,
            checkpoint=checkpoint, opener=self.opener,
        )

    def test_interruption_stops_schedule_and_is_saved_in_journal(self):
        verify = Mock(side_effect=[
            residency(False), residency(True), residency(True),
        ])

        with tempfile.TemporaryDirectory() as temporary:
            store = RunReports(Path(temporary) / "run", {
                "test_only": True, "execution_authorized": False,
            })

            def prepared(payload, digest, concurrency, *, checkpoint):
                return run_prepared_batch(
                    payload, digest, concurrency,
                    checkpoint=checkpoint,
                    control=self.control,
                    verify=verify,
                    batch_runner=self.batch,
                )

            summary = run_schedule(
                self.payload, DIGEST,
                checkpoint=store.checkpoint,
                prepared_runner=prepared,
            )
            store.finish(summary)

            self.assertEqual(summary["status"], "stopped")
            self.assertEqual(len(summary["batches"]), 1)
            self.assertEqual(
                summary["batches"][0]["status"], "interrupted"
            )
            self.assertEqual(self.opener.call_count, 1)
            self.assertEqual(self.control.call_count, 2)
            self.assertEqual(verify.call_count, 3)

            journal = json.loads(store.journal_store.path.read_text())
            self.assertEqual(journal["status"], "stopped")
            self.assertTrue(any(
                event["status"] == "interrupted"
                for event in journal["events"]
            ))
            name = journal["batches"][0]["file"]
            saved = json.loads((store.directory / name).read_text())
            self.assertEqual(saved["status"], "interrupted")
            self.assertEqual(saved["batch"]["status"], "interrupted")
            request = saved["batch"]["requests"][0]
            self.assertEqual(request["answer"], "Partial")
            self.assertEqual(len(request["events"]), 1)
            self.assertIn("terminal_monotonic_s", request)
            self.assertEqual(
                journal["report_sha256"][name],
                file_hash(store.directory / name),
            )

    def test_failed_postcheck_retains_nested_interruption_evidence(self):
        verify = Mock(side_effect=[
            residency(False), residency(True),
            {"status": "error", "error": "Injected postcheck failure"},
        ])
        snapshots = []
        report = run_prepared_batch(
            self.payload, DIGEST, 2,
            checkpoint=snapshots.append,
            control=self.control,
            verify=verify,
            batch_runner=self.batch,
        )
        self.assertEqual(report["status"], "interrupted")
        self.assertEqual(report["batch"]["status"], "interrupted")
        self.assertEqual(
            report["preparation"][-1]["record"]["status"], "error"
        )
        self.assertEqual(
            report["preparation"][-1]["record"]["error"],
            "Injected postcheck failure",
        )
        self.assertEqual(
            report["error"], "Required verify_present_after operation failed."
        )
        self.assertEqual(self.opener.call_count, 2)
        self.assertEqual(verify.call_count, 3)
        self.assertEqual(
            report["preparation"][-1]["kind"], "verify_present_after"
        )
        self.assertTrue(all(
            request["status"] == "interrupted"
            and request["answer"] == "Partial"
            for request in report["batch"]["requests"]
        ))
        self.assertEqual(snapshots[-1], report)


if __name__ == "__main__":
    unittest.main()
