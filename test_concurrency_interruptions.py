"""Worker-interruption tests; simulated HTTP only."""

import io
import unittest

from concurrency import measure_request, run_batch, serialize_request
from concurrency_experiment import run_schedule
from probe import build_payload


class InterruptedStream(io.BytesIO):
    def __init__(self, exception):
        super().__init__(b'{"response":"Partial","done":false}\n')
        self.exception = exception
        self.delivered = False

    def __next__(self):
        if not self.delivered:
            self.delivered = True
            return super().__next__()
        raise self.exception("Injected interruption")


class InterruptionTests(unittest.TestCase):
    def payload(self):
        return build_payload(
            "test-model", prompt="fixture",
            num_ctx=4096, num_predict=64,
        )

    def test_request_interruptions_preserve_partial_evidence_and_timing(self):
        for exception in (KeyboardInterrupt, SystemExit):
            with self.subTest(exception=exception):
                ticks = iter([10, 10.25, 11])
                result = measure_request(
                    serialize_request(self.payload()), 1,
                    opener=lambda request, timeout: InterruptedStream(
                        exception
                    ),
                    clock=lambda: next(ticks),
                )
                self.assertEqual(result["status"], "interrupted")
                self.assertEqual(result["answer"], "Partial")
                self.assertEqual(len(result["events"]), 1)
                self.assertEqual(result["client_first_text_s"], 0.25)
                self.assertEqual(result["client_terminal_s"], 1)
                self.assertIsNone(result["client_total_s"])
                self.assertIsNone(result["final_event"])
                self.assertIn(exception.__name__, result["error"])
                self.assertNotIn("completion_monotonic_s", result)

    def test_interrupted_batch_collects_workers_without_retry(self):
        calls = []
        snapshots = []

        def opener(request, timeout):
            calls.append(request)
            return InterruptedStream(KeyboardInterrupt)

        batch = run_batch(
            self.payload(), 2,
            checkpoint=snapshots.append, opener=opener,
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(batch["status"], "interrupted")
        self.assertTrue(all(
            result["status"] == "interrupted"
            and result["answer"] == "Partial"
            and "terminal_monotonic_s" in result
            for result in batch["requests"]
        ))
        self.assertEqual(batch["metrics"]["successful_requests"], 0)
        self.assertIsNone(batch["metrics"]["median_first_text_s"])
        self.assertEqual(snapshots[-1]["status"], "interrupted")

    def test_interrupted_prepared_outcome_stops_schedule(self):
        calls = []

        def runner(payload, digest, concurrency, *, checkpoint):
            calls.append(concurrency)
            report = {
                "status": "interrupted", "concurrency": concurrency,
            }
            checkpoint(report)
            return report

        summary = run_schedule(
            self.payload(), "test-digest",
            checkpoint=lambda report: None,
            prepared_runner=runner,
        )
        self.assertEqual(summary["status"], "stopped")
        self.assertEqual(calls, [1])
        self.assertEqual(summary["batches"][0]["status"], "interrupted")


if __name__ == "__main__":
    unittest.main()
