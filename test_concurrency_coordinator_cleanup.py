"""Coordinator cleanup and persistence tests; simulated HTTP only."""

import io
import threading
import unittest
from unittest.mock import patch

from concurrency import run_batch
from probe import build_payload


class CoordinatorCleanupTests(unittest.TestCase):
    def setUp(self):
        self.payload = build_payload(
            "test-model", prompt="fixture",
            num_ctx=4096, num_predict=64,
        )
        self.calls = []
        self.openers_ready = threading.Barrier(2, timeout=2)
        self.snapshots = []
        self.real_join = threading.Thread.join
        self.real_wait = threading.Event.wait

    def opener(self, request, timeout):
        self.calls.append(request)
        # Ensure both requests enter before either can finish.
        self.openers_ready.wait()
        return io.BytesIO(
            b'{"response":"Complete","done":true,"eval_count":1}\n'
        )

    def run_batch(self, checkpoint=None):
        return run_batch(
            self.payload, 2,
            checkpoint=(
                self.snapshots.append if checkpoint is None else checkpoint
            ),
            opener=self.opener,
            readiness_timeout_s=1,
        )

    def assert_retained_results(self, report):
        self.assertEqual(report["status"], "interrupted")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(len(self.snapshots), 2)
        self.assertEqual(self.snapshots[-1], report)
        self.assertTrue(all(
            result["status"] == "success"
            and result["answer"] == "Complete"
            and "terminal_monotonic_s" in result
            for result in report["requests"]
        ))

    def test_second_interruption_during_cleanup_join_is_retained(self):
        injections = 0

        def interrupted_join(thread, *args, **kwargs):
            nonlocal injections
            result = self.real_join(thread, *args, **kwargs)
            if injections < 2:
                injections += 1
                raise KeyboardInterrupt(f"Injected join interruption {injections}")
            return result

        with patch.object(threading.Thread, "join", interrupted_join):
            report = self.run_batch()

        self.assertEqual(injections, 2)
        self.assert_retained_results(report)
        self.assertEqual(
            [error["phase"] for error in report["coordinator_errors"]],
            ["join", "cleanup_join"],
        )

    def test_second_interruption_during_cleanup_wait_is_retained(self):
        join_injected = False
        wait_injected = False

        def interrupted_join(thread, *args, **kwargs):
            nonlocal join_injected
            result = self.real_join(thread, *args, **kwargs)
            if not join_injected:
                join_injected = True
                raise KeyboardInterrupt("Injected initial join interruption")
            return result

        def interrupted_wait(event, *args, **kwargs):
            nonlocal wait_injected
            # Do not interfere with Thread.start() or worker readiness.
            if (
                threading.current_thread() is threading.main_thread()
                and join_injected
                and not wait_injected
            ):
                wait_injected = True
                raise SystemExit("Injected cleanup wait interruption")
            return self.real_wait(event, *args, **kwargs)

        with patch.object(
            threading.Thread, "join", interrupted_join,
        ), patch.object(
            threading.Event, "wait", interrupted_wait,
        ):
            report = self.run_batch()

        self.assertTrue(join_injected)
        self.assertTrue(wait_injected)
        self.assert_retained_results(report)
        self.assertEqual(
            [error["phase"] for error in report["coordinator_errors"]],
            ["join", "cleanup_wait"],
        )
        self.assertIn(
            "SystemExit", report["coordinator_errors"][1]["error"]
        )

    def test_final_checkpoint_failure_propagates_without_write_retry(self):
        attempts = []

        def failing_checkpoint(snapshot):
            attempts.append(snapshot)
            if len(attempts) == 2:
                raise OSError("Injected final checkpoint failure")

        with self.assertRaisesRegex(
            OSError, "Injected final checkpoint failure",
        ):
            self.run_batch(checkpoint=failing_checkpoint)

        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0]["status"], "pending")
        self.assertEqual(attempts[1]["status"], "success")
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(all(
            result["answer"] == "Complete"
            and "terminal_monotonic_s" in result
            for result in attempts[1]["requests"]
        ))
        # The second snapshot was attempted, not successfully persisted.


if __name__ == "__main__":
    unittest.main()
