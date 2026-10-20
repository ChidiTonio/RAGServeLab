"""Offline coordinator interruptions through schedule and report storage."""

import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from concurrency import run_batch
from concurrency_experiment import run_prepared_batch, run_schedule
from concurrency_run_store import RunReports, file_hash
from probe import build_payload
from test_concurrency_experiment import DIGEST, residency


class CoordinatorIntegrationTests(unittest.TestCase):
    def test_coordinator_interruption_stops_schedule_and_is_persisted(self):
        for phase in ("readiness", "join"):
            with self.subTest(phase=phase):
                self.check_phase(phase)

    def check_phase(self, phase):
        payload = build_payload(
            "test-model", prompt="fixture",
            num_ctx=4096, num_predict=64,
        )
        control = Mock(return_value={"status": "success"})
        verify = Mock(side_effect=[
            residency(False), residency(True), residency(True),
        ])
        opener = Mock(side_effect=lambda request, timeout: io.BytesIO(
            b'{"response":"Complete","done":true,"eval_count":1}\n'
        ))
        real_wait = threading.Barrier.wait
        real_join = threading.Thread.join
        injected = False

        def interrupted_wait(barrier, *args, **kwargs):
            nonlocal injected
            if (
                phase == "readiness"
                and threading.current_thread() is threading.main_thread()
                and not injected
            ):
                injected = True
                raise KeyboardInterrupt("Injected coordinator readiness")
            return real_wait(barrier, *args, **kwargs)

        def interrupted_join(thread, *args, **kwargs):
            nonlocal injected
            result = real_join(thread, *args, **kwargs)
            if (
                phase == "join"
                and threading.current_thread() is threading.main_thread()
                and not injected
            ):
                injected = True
                raise SystemExit("Injected coordinator join")
            return result

        def batch(payload, concurrency, *, checkpoint):
            return run_batch(
                payload, concurrency, checkpoint=checkpoint,
                opener=opener, readiness_timeout_s=1,
            )

        def prepared(payload, digest, concurrency, *, checkpoint):
            return run_prepared_batch(
                payload, digest, concurrency, checkpoint=checkpoint,
                control=control, verify=verify, batch_runner=batch,
            )

        with tempfile.TemporaryDirectory() as temporary:
            store = RunReports(Path(temporary) / "run", {
                "test_only": True, "execution_authorized": False,
            })
            with patch.object(
                threading.Barrier, "wait", interrupted_wait,
            ), patch.object(
                threading.Thread, "join", interrupted_join,
            ):
                summary = run_schedule(
                    payload, DIGEST, checkpoint=store.checkpoint,
                    prepared_runner=prepared,
                )
            store.finish(summary)

            self.assertTrue(injected)
            self.assertEqual(summary["status"], "stopped")
            self.assertEqual(len(summary["batches"]), 1)
            self.assertEqual(
                summary["batches"][0]["status"], "interrupted"
            )
            self.assertEqual(control.call_count, 2)
            self.assertEqual(verify.call_count, 3)
            self.assertEqual(opener.call_count, 0 if phase == "readiness" else 1)

            journal = json.loads(store.journal_store.path.read_text())
            self.assertEqual(journal["status"], "stopped")
            self.assertEqual(len(journal["batches"]), 1)
            self.assertTrue(any(
                event["status"] == "interrupted"
                for event in journal["events"]
            ))
            name = journal["batches"][0]["file"]
            saved = json.loads((store.directory / name).read_text())
            self.assertEqual(saved["status"], "interrupted")
            nested = saved["batch"]
            self.assertEqual(nested["status"], "interrupted")
            self.assertEqual(
                nested["coordinator_errors"][0]["phase"], phase
            )
            self.assertEqual(
                nested["coordinator_errors"][0]["status"], "interrupted"
            )
            self.assertEqual(
                saved["preparation"][-1]["kind"], "verify_present_after"
            )
            request = nested["requests"][0]
            if phase == "readiness":
                self.assertEqual(request["status"], "not_released")
                self.assertNotIn("release_monotonic_s", nested)
            else:
                self.assertEqual(request["status"], "success")
                self.assertEqual(request["answer"], "Complete")
                self.assertIn("terminal_monotonic_s", request)
            self.assertEqual(
                journal["report_sha256"][name],
                file_hash(store.directory / name),
            )


if __name__ == "__main__":
    unittest.main()
