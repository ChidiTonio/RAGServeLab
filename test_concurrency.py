"""Offline concurrency tests: simulated HTTP only."""

import io
import json
import threading
import unittest
from unittest.mock import patch

from concurrency import measure_request, run_batch, serialize_request
from probe import build_payload


def stream(*events):
    return io.BytesIO(b"".join(
        json.dumps(event).encode() + b"\n" for event in events
    ))


class RequestTests(unittest.TestCase):
    def request(self):
        return serialize_request(build_payload("test-model", prompt="fixture"))

    def test_timing_and_empty_events(self):
        ticks = iter([10, 10.25, 11, 11.1])
        result = measure_request(
            self.request(), 1,
            opener=lambda request, timeout: stream(
                {"response": "", "done": False},
                {"response": "Hello", "done": False},
                {"response": " world", "done": True,
                 "eval_count": 2, "eval_duration": 100000000},
            ),
            clock=lambda: next(ticks),
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["answer"], "Hello world")
        self.assertEqual(result["client_first_text_s"], 0.25)
        self.assertEqual(result["client_total_s"], 1)
        self.assertAlmostEqual(result["client_terminal_s"], 1.1)
        self.assertEqual(result["runtime_metrics"]["generation_tokens_per_s"], 20)

    def test_partial_output_preserved_on_server_error(self):
        result = measure_request(
            self.request(), 1,
            opener=lambda request, timeout: stream(
                {"response": "Partial", "done": False},
                {"error": "server failure"},
            ),
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["answer"], "Partial")
        self.assertEqual(len(result["events"]), 2)
        self.assertIn("server failure", result["error"])

    def test_malformed_json_preserves_partial_output(self):
        result = measure_request(
            self.request(), 1,
            opener=lambda request, timeout: io.BytesIO(
                b'{"response":"Partial","done":false}\nnot-json\n'
            ),
        )
        self.assertEqual(result["answer"], "Partial")
        self.assertIn("JSONDecodeError", result["error"])

    def test_incomplete_and_empty_streams_fail(self):
        for events in (
            ({"response": "Partial", "done": False},),
            ({"response": "", "done": True},),
            (["not an object"],),
        ):
            with self.subTest(events=events):
                result = measure_request(
                    self.request(), 1,
                    opener=lambda request, timeout: stream(*events),
                )
                self.assertEqual(result["status"], "error")
                self.assertIn("terminal_monotonic_s", result)

    def test_transport_failure_is_retained(self):
        def opener(request, timeout):
            self.assertEqual(timeout, 180)
            raise OSError("offline failure")
        result = measure_request(self.request(), 1, opener=opener)
        self.assertEqual(result["status"], "error")
        self.assertIn("offline failure", result["error"])


class BatchTests(unittest.TestCase):
    def payload(self):
        return build_payload(
            "test-model", prompt="fixture", num_ctx=4096, num_predict=64
        )

    def test_independent_workers_and_coordinator_checkpoints(self):
        for count in (1, 2, 4):
            with self.subTest(concurrency=count):
                coordinator = threading.get_ident()
                snapshots, requests, callers = [], [], []
                lock = threading.Lock()
                active = 0

                def checkpoint(batch):
                    self.assertEqual(threading.get_ident(), coordinator)
                    self.assertEqual(active, 0)
                    snapshots.append(batch)

                def opener(request, timeout):
                    nonlocal active
                    with lock:
                        active += 1
                        requests.append(request)
                        callers.append(threading.get_ident())
                    class Response(io.BytesIO):
                        def __exit__(self, *args):
                            nonlocal active
                            try:
                                return super().__exit__(*args)
                            finally:
                                with lock:
                                    active -= 1
                    return Response(
                        b'{"response":"Answer","done":true,"eval_count":2}\n'
                    )

                payload = self.payload()
                batch = run_batch(
                    payload, count, checkpoint=checkpoint, opener=opener
                )
                self.assertEqual(batch["status"], "success")
                self.assertEqual(len(requests), count)
                self.assertEqual(len({id(r) for r in requests}), count)
                self.assertNotIn(coordinator, callers)
                self.assertTrue(all(json.loads(r.data) == payload for r in requests))
                self.assertEqual(len(snapshots), 2)
                self.assertEqual(snapshots[0]["status"], "pending")
                self.assertEqual(batch["metrics"]["successful_requests"], count)
                self.assertGreater(batch["metrics"]["batch_duration_s"], 0)
                self.assertTrue(all(
                    r["release_to_start_s"] >= 0 for r in batch["requests"]
                ))

    def test_failed_workers_are_not_retried(self):
        calls = []
        def opener(request, timeout):
            calls.append(request)
            raise OSError("simulated failure")
        batch = run_batch(
            self.payload(), 4, checkpoint=lambda b: None, opener=opener
        )
        self.assertEqual(len(calls), 4)
        self.assertEqual(batch["status"], "error")
        self.assertEqual(batch["metrics"]["successful_requests"], 0)
        self.assertIsNone(batch["metrics"]["median_first_text_s"])

    def test_missing_token_count_stays_unknown(self):
        batch = run_batch(
            self.payload(), 1, checkpoint=lambda b: None,
            opener=lambda request, timeout: stream(
                {"response": "Answer", "done": True}
            ),
        )
        self.assertEqual(batch["status"], "success")
        self.assertIsNone(batch["metrics"]["aggregate_output_tokens_per_s"])

    def test_checkpoint_failure_prevents_thread_launch(self):
        with patch("concurrency.threading.Thread") as thread:
            with self.assertRaisesRegex(OSError, "storage"):
                run_batch(
                    self.payload(), 2,
                    checkpoint=lambda b: (_ for _ in ()).throw(OSError("storage")),
                )
            thread.assert_not_called()

    def test_readiness_failure_does_not_send_requests(self):
        snapshots = []
        with patch("concurrency.threading.Barrier") as barrier:
            barrier.return_value.wait.side_effect = threading.BrokenBarrierError
            with patch("concurrency.urlopen") as opener:
                batch = run_batch(
                    self.payload(), 2, checkpoint=snapshots.append,
                    opener=opener,
                )
                opener.assert_not_called()
        self.assertEqual(batch["status"], "error")
        self.assertNotIn("release_monotonic_s", batch)
        self.assertTrue(all(
            r["status"] == "not_released" for r in batch["requests"]
        ))

    def test_serialization_failure_precedes_checkpoint(self):
        snapshots = []
        payload = self.payload()
        payload["invalid"] = object()
        with self.assertRaises(TypeError):
            run_batch(payload, 1, checkpoint=snapshots.append)
        self.assertEqual(snapshots, [])

    def test_invalid_concurrency_is_rejected(self):
        for value in (0, 3, True):
            with self.assertRaises(ValueError):
                run_batch(self.payload(), value, checkpoint=lambda b: None)


if __name__ == "__main__":
    unittest.main()
