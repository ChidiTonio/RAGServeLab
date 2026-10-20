"""Offline regressions for interruption during cleanup gate opening."""

import threading
import unittest
from unittest.mock import Mock, patch

from concurrency import run_batch
from probe import build_payload


class CleanupGateTests(unittest.TestCase):
    def test_cleanup_gate_interruptions_retain_final_checkpoint(self):
        for after_set in (False, True):
            for exception_type in (KeyboardInterrupt, SystemExit):
                with self.subTest(
                    after_set=after_set,
                    exception_type=exception_type.__name__,
                ):
                    self.check_cleanup_gate(after_set, exception_type)

    def check_cleanup_gate(self, after_set, exception_type):
        payload = build_payload(
            "test-model", prompt="fixture",
            num_ctx=4096, num_predict=64,
        )
        snapshots = []
        opener = Mock(side_effect=AssertionError("HTTP must not be called"))
        main_ident = threading.get_ident()
        real_wait = threading.Barrier.wait
        real_abort = threading.Barrier.abort
        real_set = threading.Event.set
        real_start = threading.Thread.start
        real_join = threading.Thread.join
        threads = []
        readiness_injected = False
        cleanup_started = False
        gate_injected = False
        gate = None
        escaped = None
        report = None
        finished_before_rescue = []

        def interrupted_wait(barrier, *args, **kwargs):
            nonlocal readiness_injected
            result = real_wait(barrier, *args, **kwargs)
            if (
                threading.get_ident() == main_ident
                and not readiness_injected
            ):
                readiness_injected = True
                raise KeyboardInterrupt("Injected after completed readiness")
            return result

        def observed_abort(barrier):
            nonlocal cleanup_started
            result = real_abort(barrier)
            if threading.get_ident() == main_ident:
                cleanup_started = True
            return result

        def interrupted_set(event):
            nonlocal gate_injected, gate
            if (
                threading.get_ident() == main_ident
                and cleanup_started
                and not gate_injected
            ):
                gate = event
                gate_injected = True
                if after_set:
                    real_set(event)
                raise exception_type("Injected cleanup gate interruption")
            return real_set(event)

        def observed_start(thread, *args, **kwargs):
            threads.append(thread)
            return real_start(thread, *args, **kwargs)

        try:
            with patch.object(
                threading.Barrier, "wait", interrupted_wait,
            ), patch.object(
                threading.Barrier, "abort", observed_abort,
            ), patch.object(
                threading.Event, "set", interrupted_set,
            ), patch.object(
                threading.Thread, "start", observed_start,
            ):
                try:
                    report = run_batch(
                        payload, 1, checkpoint=snapshots.append,
                        opener=opener, readiness_timeout_s=1,
                    )
                except BaseException as exc:
                    escaped = exc
                finished_before_rescue = [
                    not thread.is_alive() for thread in threads
                ]
        finally:
            # Rescue an unopened gate only after recording the outcome.
            # Use original methods outside the injection context.
            if gate is not None:
                real_set(gate)
            for thread in threads:
                if thread.ident is not None:
                    real_join(thread, timeout=2)

        self.assertTrue(readiness_injected)
        self.assertTrue(gate_injected)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        opener.assert_not_called()
        if escaped is not None:
            self.fail(
                f"Cleanup escaped as {type(escaped).__name__}: {escaped}; "
                f"checkpoint count={len(snapshots)}"
            )
        self.assertEqual(finished_before_rescue, [True])
        self.assertEqual(report["status"], "interrupted")
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(snapshots[-1], report)
        self.assertNotIn("release_monotonic_s", report)
        self.assertEqual(report["requests"][0]["status"], "not_released")
        self.assertTrue(any(
            entry["phase"] == "cleanup_release"
            and entry["status"] == "interrupted"
            and "Injected cleanup gate interruption" in entry["error"]
            for entry in report["coordinator_errors"]
        ))


if __name__ == "__main__":
    unittest.main()
