"""Offline regression for coordinator interruption during barrier cleanup."""

import threading
import unittest
from unittest.mock import Mock, patch

from concurrency import run_batch
from probe import build_payload


class CleanupAbortTests(unittest.TestCase):
    def test_cleanup_abort_interruption_retains_final_checkpoint(self):
        payload = build_payload(
            "test-model", prompt="fixture",
            num_ctx=4096, num_predict=64,
        )
        snapshots = []
        opener = Mock(side_effect=AssertionError("HTTP must not be called"))
        real_wait = threading.Barrier.wait
        real_abort = threading.Barrier.abort
        readiness_injected = False
        cleanup_injected = False

        def interrupted_wait(barrier, *args, **kwargs):
            nonlocal readiness_injected
            if (
                threading.current_thread() is threading.main_thread()
                and not readiness_injected
            ):
                readiness_injected = True
                raise KeyboardInterrupt("Injected readiness interruption")
            return real_wait(barrier, *args, **kwargs)

        def interrupted_abort(barrier):
            nonlocal cleanup_injected
            if (
                threading.current_thread() is threading.main_thread()
                and not cleanup_injected
            ):
                cleanup_injected = True
                raise SystemExit("Injected cleanup abort interruption")
            return real_abort(barrier)

        escaped = None
        report = None
        with patch.object(
            threading.Barrier, "wait", interrupted_wait,
        ), patch.object(
            threading.Barrier, "abort", interrupted_abort,
        ):
            try:
                report = run_batch(
                    payload, 1, checkpoint=snapshots.append,
                    opener=opener, readiness_timeout_s=0.1,
                )
            except BaseException as exc:
                escaped = exc

        self.assertTrue(readiness_injected)
        self.assertTrue(cleanup_injected)
        opener.assert_not_called()
        if escaped is not None:
            self.fail(
                f"Cleanup escaped as {type(escaped).__name__}: {escaped}; "
                f"checkpoint count={len(snapshots)}"
            )
        self.assertEqual(report["status"], "interrupted")
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(snapshots[-1], report)
        self.assertTrue(any(
            "Injected cleanup abort interruption" in entry["error"]
            for entry in report["coordinator_errors"]
        ))


if __name__ == "__main__":
    unittest.main()
