"""Offline regression for interruption before worker identity publication."""

import threading
import unittest
from unittest.mock import Mock, patch

import concurrency
from probe import build_payload


class LaunchWindowTests(unittest.TestCase):
    def test_launched_worker_finishes_before_final_checkpoint(self):
        payload = build_payload(
            "test-model", prompt="fixture",
            num_ctx=4096, num_predict=64,
        )
        real_event = threading.Event
        real_thread = threading.Thread
        real_start = real_thread.start
        real_join = real_thread.join
        coordinator_ident = threading.get_ident()
        bootstrap_entered = real_event()
        allow_bootstrap = real_event()
        events = []
        created = []
        snapshots = []
        completion_at_checkpoint = []
        ident_at_interrupt = []
        native_ident_at_interrupt = []
        injected = False
        opener = Mock(side_effect=AssertionError("HTTP must not be called"))

        class WorkerDoneEvent(real_event):
            def wait(self, *args, **kwargs):
                if threading.get_ident() == coordinator_ident:
                    # A correct cleanup path reaches this wait even when
                    # the launched worker has not published its identity.
                    allow_bootstrap.set()
                return super().wait(*args, **kwargs)

        def event_factory(*args, **kwargs):
            # run_batch creates release_gate, abort, then worker_done[0].
            # Thread._started and other events remain ordinary Events.
            event_class = WorkerDoneEvent if len(events) == 2 else real_event
            event = event_class(*args, **kwargs)
            events.append(event)
            return event

        class HeldBootstrapThread(real_thread):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                created.append(self)

            def _set_ident(self):
                bootstrap_entered.set()
                allow_bootstrap.wait()
                return super()._set_ident()

            def start(self):
                nonlocal injected
                original_wait = self._started.wait

                def interrupted_started_wait(*args, **kwargs):
                    nonlocal injected
                    if threading.get_ident() != coordinator_ident:
                        return original_wait(*args, **kwargs)
                    if not bootstrap_entered.wait(timeout=2):
                        raise AssertionError(
                            "Fixture failed: bootstrap did not enter."
                        )
                    ident_at_interrupt.append(self.ident)
                    native_ident_at_interrupt.append(
                        self._os_thread_handle.ident
                    )
                    injected = True
                    raise KeyboardInterrupt(
                        "Injected before worker identity publication"
                    )

                # Patch only this Thread's bootstrap acknowledgement.
                self._started.wait = interrupted_started_wait
                try:
                    return real_start(self)
                finally:
                    self._started.wait = original_wait

        def checkpoint(snapshot):
            snapshots.append(snapshot)
            if len(snapshots) == 2:
                completion_at_checkpoint.append(events[2].is_set())

        try:
            with patch.object(
                concurrency.threading, "Event", event_factory,
            ), patch.object(
                concurrency.threading, "Thread", HeldBootstrapThread,
            ):
                report = concurrency.run_batch(
                    payload, 1, checkpoint=checkpoint,
                    opener=opener, readiness_timeout_s=0.2,
                )
        finally:
            # Do not leave a bootstrap-held worker behind after failure.
            allow_bootstrap.set()
            for thread in created:
                if not thread._started.wait(timeout=2):
                    self.fail("Fixture teardown: bootstrap did not finish.")
                real_join(thread, timeout=2)
                self.assertFalse(
                    thread.is_alive(),
                    "Fixture teardown: worker remained alive.",
                )

        self.assertTrue(injected, f"Injection not reached; report={report!r}; bootstrap_entered={bootstrap_entered.is_set()}; events={len(events)}")
        self.assertEqual(ident_at_interrupt, [None])
        self.assertEqual(len(native_ident_at_interrupt), 1)
        self.assertNotEqual(
            native_ident_at_interrupt[0], 0,
            "Native handle did not expose launch evidence.",
        )
        self.assertEqual(len(created), 1)
        opener.assert_not_called()
        self.assertEqual(report["status"], "interrupted")
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(snapshots[-1], report)
        self.assertNotIn("release_monotonic_s", report)
        self.assertEqual(report["requests"][0]["status"], "not_released")
        self.assertTrue(any(
            entry["phase"] == "thread_start"
            and entry["status"] == "interrupted"
            for entry in report["coordinator_errors"]
        ))
        self.assertEqual(
            completion_at_checkpoint, [True],
            "Final checkpoint occurred before the launched worker finished.",
        )


    def test_failed_start_before_launch_does_not_wait_for_worker(self):
        payload = build_payload(
            "test-model", prompt="fixture",
            num_ctx=4096, num_predict=64,
        )
        for exception_type, expected_status in (
            (RuntimeError, "error"),
            (KeyboardInterrupt, "interrupted"),
        ):
            with self.subTest(exception_type=exception_type.__name__):
                snapshots = []
                opener = Mock(
                    side_effect=AssertionError("HTTP must not be called")
                )
                with patch.object(
                    concurrency.threading.Thread, "start",
                    side_effect=exception_type(
                        "Injected failure before native launch"
                    ),
                ) as start:
                    report = concurrency.run_batch(
                        payload, 1, checkpoint=snapshots.append,
                        opener=opener, readiness_timeout_s=0.2,
                    )

                start.assert_called_once_with()
                opener.assert_not_called()
                self.assertEqual(report["status"], expected_status)
                self.assertEqual(len(snapshots), 2)
                self.assertEqual(snapshots[-1], report)
                self.assertNotIn("release_monotonic_s", report)
                self.assertEqual(
                    report["requests"][0]["status"], "not_released"
                )
                self.assertTrue(any(
                    entry["phase"] == "thread_start"
                    and entry["status"] == expected_status
                    and "Injected failure before native launch"
                    in entry["error"]
                    for entry in report["coordinator_errors"]
                ))


if __name__ == "__main__":
    unittest.main()
