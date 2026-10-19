"""Unit tests for stream completion semantics and reported runtime metrics."""

import json
import unittest

from probe import read_stream, runtime_metrics


def encode_events(*events):
    return [json.dumps(event).encode() + b"\n" for event in events]


class ProbeTests(unittest.TestCase):
    def test_first_text_ignores_empty_events(self):
        ticks = iter([10.25, 11.0])
        result = read_stream(
            encode_events(
                {"response": "", "done": False},
                {"response": "Hello", "done": False},
                {"response": " world", "done": True},
            ),
            started=10.0,
            clock=lambda: next(ticks),
        )
        self.assertEqual(result["answer"], "Hello world")
        self.assertEqual(result["client_first_text_s"], 0.25)
        self.assertEqual(result["client_total_s"], 1.0)

    def test_incomplete_stream_fails(self):
        with self.assertRaisesRegex(RuntimeError, "completion event"):
            read_stream(
                encode_events({"response": "Partial", "done": False}),
                started=0,
                clock=lambda: 1,
            )

    def test_server_error_fails(self):
        with self.assertRaisesRegex(RuntimeError, "model failure"):
            read_stream(
                encode_events({"error": "model failure"}),
                started=0,
            )

    def test_empty_completion_fails(self):
        with self.assertRaisesRegex(RuntimeError, "no generated text"):
            read_stream(
                encode_events({"response": "", "done": True}),
                started=0,
                clock=lambda: 1,
            )

    def test_runtime_units_and_throughput(self):
        metrics = runtime_metrics(
            {"eval_count": 40, "eval_duration": 2_000_000_000}
        )
        self.assertEqual(metrics["eval_duration_s"], 2)
        self.assertEqual(metrics["generation_tokens_per_s"], 20)
        self.assertIsNone(metrics["load_duration_s"])

    def test_cached_prompt_count_preserves_reported_values(self):
        for cached_count in (0, 40):
            with self.subTest(cached_count=cached_count):
                metrics = runtime_metrics(
                    {
                        "prompt_eval_count": 41,
                        "prompt_eval_cached_count": cached_count,
                    }
                )
                self.assertEqual(metrics["prompt_eval_count"], 41)
                self.assertEqual(
                    metrics["prompt_eval_cached_count"], cached_count
                )

    def test_missing_metrics_remain_unknown(self):
        metrics = runtime_metrics({})
        for key in (
            "total_duration_s",
            "load_duration_s",
            "prompt_eval_duration_s",
            "eval_duration_s",
            "prompt_eval_count",
            "prompt_eval_cached_count",
            "eval_count",
            "generation_tokens_per_s",
        ):
            with self.subTest(key=key):
                self.assertIsNone(metrics[key])

    def test_zero_generation_duration_has_no_throughput(self):
        metrics = runtime_metrics(
            {"eval_count": 40, "eval_duration": 0}
        )
        self.assertEqual(metrics["eval_duration_s"], 0)
        self.assertIsNone(metrics["generation_tokens_per_s"])


if __name__ == "__main__":
    unittest.main()
