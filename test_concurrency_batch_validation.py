"""Successful-batch contract tests; simulated HTTP only."""

import copy
import io
import unittest

from concurrency import run_batch, summarize_batch
from concurrency_batch_validation import validate_successful_batch
from probe import build_payload


class BatchValidationTests(unittest.TestCase):
    def setUp(self):
        self.payload = build_payload(
            "test-model", prompt="fixture", num_ctx=4096, num_predict=64
        )

    def fixture(self, concurrency=2, tokens=True):
        raw = (
            b'{"response":"Answer","done":true,"eval_count":2}\n'
            if tokens else b'{"response":"Answer","done":true}\n'
        )
        return run_batch(
            self.payload, concurrency,
            checkpoint=lambda batch: None,
            opener=lambda request, timeout: io.BytesIO(raw),
        )

    def validate(self, batch, concurrency=2):
        validate_successful_batch(batch, self.payload, concurrency)

    def test_accepts_real_worker_records_without_mutation(self):
        for count in (1, 2, 4):
            with self.subTest(concurrency=count):
                batch = self.fixture(count)
                original = copy.deepcopy(batch)
                payload = copy.deepcopy(self.payload)
                self.validate(batch, count)
                self.assertEqual(batch, original)
                self.assertEqual(self.payload, payload)

    def test_missing_token_counts_remain_unknown(self):
        batch = self.fixture(tokens=False)
        self.validate(batch)
        self.assertIsNone(
            batch["metrics"]["aggregate_output_tokens_per_s"]
        )

    def test_rejects_success_shaped_record_without_evidence(self):
        with self.assertRaises(ValueError):
            self.validate({
                "status": "success", "concurrency": 2,
                "requests": [
                    {"request_id": i, "status": "success"}
                    for i in (1, 2)
                ],
            })

    def test_rejects_nonfinite_and_boolean_timestamps(self):
        for value in (float("nan"), float("inf"), -float("inf"), True):
            with self.subTest(value=value):
                batch = self.fixture()
                batch["requests"][0]["completion_monotonic_s"] = value
                with self.assertRaises(ValueError):
                    self.validate(batch)

    def test_rejects_ordering_even_with_recomputed_metrics(self):
        batch = self.fixture()
        batch["requests"][0]["request_started_monotonic_s"] = (
            batch["release_monotonic_s"] - 1
        )
        summarize_batch(batch)
        with self.assertRaisesRegex(ValueError, "out of order"):
            self.validate(batch)

    def test_rejects_inconsistent_derived_durations_and_metrics(self):
        original = self.fixture()
        for scope, field in (
            ("request", "client_total_s"),
            ("request", "release_to_first_text_s"),
            ("batch", "batch_duration_s"),
            ("batch", "dispatch_skew_s"),
            ("batch", "aggregate_output_tokens_per_s"),
        ):
            with self.subTest(scope=scope, field=field):
                batch = copy.deepcopy(original)
                record = (
                    batch["requests"][0] if scope == "request"
                    else batch["metrics"]
                )
                record[field] += 1
                with self.assertRaises(ValueError):
                    self.validate(batch)

    def test_rejects_identity_payload_and_stream_disagreement(self):
        original = self.fixture()
        for kind in ("identity", "payload", "answer", "final", "runtime"):
            with self.subTest(kind=kind):
                batch = copy.deepcopy(original)
                request = batch["requests"][0]
                if kind == "identity":
                    request["request_id"] = True
                elif kind == "payload":
                    batch["request"]["prompt"] = "wrong"
                elif kind == "answer":
                    request["answer"] = "wrong"
                elif kind == "final":
                    request["final_event"] = {"done": False}
                else:
                    request["runtime_metrics"]["eval_count"] = 999
                with self.assertRaises(ValueError):
                    self.validate(batch)


if __name__ == "__main__":
    unittest.main()
