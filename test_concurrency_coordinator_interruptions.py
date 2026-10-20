"""Coordinator interruption regression tests; simulated HTTP only."""

import io
import threading
import unittest
from unittest.mock import patch

import concurrency
from probe import build_payload


class CoordinatorInterruptionTests(unittest.TestCase):
    def setUp(self):
        self.payload = build_payload(
            "test-model", prompt="fixture",
            num_ctx=4096, num_predict=64,
        )
        self.snapshots = []
        self.calls = []
        self.created = []
        self.real_start = threading.Thread.start
        self.real_join = threading.Thread.join
        self.real_barrier_wait = threading.Barrier.wait

    def tearDown(self):
        # Use the original join after mocks have been removed.
        # The short readiness timeout bounds unreleased-worker cleanup.
        for thread in self.created:
            if thread.ident is not None:
                self.real_join(thread, timeout=2)
                self.assertFalse(
                    thread.is_alive(),
                    f"Worker remained alive: {thread.name}",
                )

    def opener(self, request, timeout):
        self.calls.append(request)
        return io.BytesIO(
            b'{"response":"Complete","done":true,"eval_count":1}\n'
        )

    def start_and_track(self, thread):
        self.created.append(thread)
        return self.real_start(thread)

    def run_batch(self):
        return concurrency.run_batch(
            self.payload, 2,
            checkpoint=self.snapshots.append,
            opener=self.opener,
            readiness_timeout_s=0.2,
        )

    def assert_interrupted_checkpoint(self, report):
        self.assertEqual(report["status"], "interrupted")
        self.assertEqual(len(self.snapshots), 2)
        self.assertEqual(self.snapshots[0]["status"], "pending")
        self.assertEqual(self.snapshots[-1], report)
        self.assertEqual(
            [request["request_id"] for request in report["requests"]],
            [1, 2],
        )
        self.assertTrue(all(
            not thread.is_alive() for thread in self.created
        ))

    def test_readiness_interruptions_checkpoint_without_http(self):
        for exception in (KeyboardInterrupt, SystemExit):
            with self.subTest(exception=exception):
                self.snapshots.clear()
                self.calls.clear()
                self.created.clear()

                def interrupted_wait(barrier, *args, **kwargs):
                    if threading.current_thread() is threading.main_thread():
                        raise exception("Injected coordinator readiness interruption")
                    return self.real_barrier_wait(barrier, *args, **kwargs)

                with patch.object(
                    threading.Thread, "start", lambda thread: self.start_and_track(thread),
                ), patch.object(
                    threading.Barrier, "wait", interrupted_wait,
                ):
                    report = self.run_batch()

                self.assert_interrupted_checkpoint(report)
                self.assertNotIn("release_monotonic_s", report)
                self.assertEqual(self.calls, [])
                self.assertTrue(all(
                    request["status"] == "not_released"
                    for request in report["requests"]
                ))

    def test_join_interruption_retains_completed_worker_evidence(self):
        injected = False

        def interrupted_join(thread, *args, **kwargs):
            nonlocal injected
            result = self.real_join(thread, *args, **kwargs)
            if not injected:
                injected = True
                raise KeyboardInterrupt("Injected coordinator join interruption")
            return result

        with patch.object(
            threading.Thread, "start", lambda thread: self.start_and_track(thread),
        ), patch.object(
            threading.Thread, "join", interrupted_join,
        ):
            report = self.run_batch()

        self.assertTrue(injected)
        self.assert_interrupted_checkpoint(report)
        self.assertEqual(len(self.calls), 2)
        self.assertIn("release_monotonic_s", report)
        self.assertTrue(all(
            request["status"] == "success"
            and request["answer"] == "Complete"
            and "terminal_monotonic_s" in request
            for request in report["requests"]
        ))
        # Worker success must not erase the coordinator interruption.
        self.assertEqual(report["status"], "interrupted")

    def test_start_interruption_after_launch_collects_worker(self):
        injected = False

        def interrupted_start(thread):
            nonlocal injected
            self.created.append(thread)
            self.real_start(thread)
            if not injected:
                injected = True
                raise KeyboardInterrupt("Injected interruption after thread launch")

        with patch.object(
            threading.Thread, "start", interrupted_start,
        ):
            report = self.run_batch()

        self.assertTrue(injected)
        self.assert_interrupted_checkpoint(report)
        self.assertEqual(len(self.created), 1)
        self.assertEqual(self.calls, [])
        self.assertNotIn("release_monotonic_s", report)
        self.assertTrue(all(
            request["status"] == "not_released"
            for request in report["requests"]
        ))


if __name__ == "__main__":
    unittest.main()
