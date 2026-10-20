"""Offline regression: interrupted release must retain completed evidence."""

import io
import threading
import time
import unittest
from unittest.mock import Mock, patch

import concurrency
from probe import build_payload


class ReleaseInterruptionTests(unittest.TestCase):
    def test_post_set_interruption_retains_completed_worker_result(self):
        payload = build_payload(
            "test-model", prompt="fixture",
            num_ctx=4096, num_predict=64,
        )
        snapshots = []
        opener = Mock(side_effect=lambda request, timeout: io.BytesIO(
            b'{"response":"Complete","done":true,"eval_count":1}\n'
        ))
        coordinator_ident = threading.get_ident()
        real_event = threading.Event
        events = []
        release_armed = False
        injected = False
        worker_finished_before_interrupt = False

        def clock():
            nonlocal release_armed
            if threading.get_ident() == coordinator_ident:
                release_armed = True
            return time.perf_counter()

        class ReleaseGate(real_event):
            def set(self):
                nonlocal injected, worker_finished_before_interrupt
                result = super().set()
                if (
                    threading.get_ident() == coordinator_ident
                    and release_armed
                    and not injected
                ):
                    injected = True
                    # run_batch creates: release_gate, abort, worker_done[0].
                    # worker_done is signaled after results[0] is stored.
                    worker_finished_before_interrupt = events[2].wait(
                        timeout=2
                    )
                    raise KeyboardInterrupt(
                        "Injected after release gate opened"
                    )
                return result

        def event_factory(*args, **kwargs):
            # Only the first event gets the injection hook.
            # All later events, including Thread._started, are ordinary.
            event_class = ReleaseGate if not events else real_event
            event = event_class(*args, **kwargs)
            events.append(event)
            return event

        with patch.object(
            concurrency.threading, "Event", event_factory,
        ):
            report = concurrency.run_batch(
                payload, 1, checkpoint=snapshots.append,
                opener=opener, clock=clock, readiness_timeout_s=1,
            )

        self.assertTrue(injected)
        self.assertTrue(
            worker_finished_before_interrupt,
            "Fixture failed: worker did not store its result before injection.",
        )
        opener.assert_called_once()
        self.assertEqual(report["status"], "interrupted")
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(snapshots[-1], report)
        request = report["requests"][0]
        self.assertEqual(
            request["status"], "success",
            "A completed request was replaced by a not_released record.",
        )
        self.assertEqual(request["answer"], "Complete")
        self.assertIn("terminal_monotonic_s", request)
        self.assertIn("release_monotonic_s", report)
        self.assertTrue(any(
            entry["phase"] == "release"
            and entry["status"] == "interrupted"
            for entry in report["coordinator_errors"]
        ))


if __name__ == "__main__":
    unittest.main()
