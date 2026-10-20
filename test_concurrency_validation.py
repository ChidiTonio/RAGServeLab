"""Offline tests for strict residency-record validation."""

import copy
import unittest

from concurrency_validation import validate_residency_record


DIGEST = "target-digest"


def record(present=True):
    return {
        "model_digest": DIGEST,
        "expected_present": present,
        "status": "success",
        "observations": [{
            "status": "success",
            "present": present,
            "response": {"models": [
                {"digest": DIGEST, "context_length": 4096}
            ] if present else []},
        }],
    }


class ResidencyContractTests(unittest.TestCase):
    def check(self, value, present=True):
        validate_residency_record(value, DIGEST, present, 4096)

    def test_accepts_presence_and_absence_without_mutation(self):
        for present in (True, False):
            value = record(present)
            original = copy.deepcopy(value)
            self.check(value, present)
            self.assertEqual(value, original)

    def test_rejects_wrong_record_identity_or_status(self):
        for field, value in (
            ("model_digest", "other"),
            ("expected_present", False),
            ("expected_present", 1),
            ("status", "error"),
        ):
            with self.subTest(field=field, value=value):
                candidate = record()
                candidate[field] = value
                with self.assertRaises(RuntimeError):
                    self.check(candidate)

    def test_requires_final_successful_observation(self):
        candidate = record()
        candidate["observations"].append({"status": "error"})
        with self.assertRaises(RuntimeError):
            self.check(candidate)

    def test_rejects_malformed_records_and_snapshots(self):
        candidates = [None, {}, record(), record(), record(), record()]
        candidates[2]["observations"] = []
        candidates[3]["observations"][-1]["response"] = []
        candidates[4]["observations"][-1]["response"] = {"models": None}
        candidates[5]["observations"][-1]["response"] = {"models": [{}]}
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                with self.assertRaises(RuntimeError):
                    self.check(candidate)

    def test_rejects_observation_snapshot_disagreement(self):
        candidate = record(False)
        candidate["observations"][-1]["response"]["models"] = [
            {"digest": DIGEST}
        ]
        with self.assertRaises(RuntimeError):
            self.check(candidate, False)

    def test_requires_exact_integer_context(self):
        for context in (None, 2048, "4096", 4096.0, True):
            with self.subTest(context=context):
                candidate = record()
                models = candidate["observations"][-1]["response"]["models"]
                models[0]["context_length"] = context
                with self.assertRaises(RuntimeError):
                    self.check(candidate)

    def test_validates_every_entry_even_for_absence(self):
        candidate = record(False)
        candidate["observations"][-1]["response"]["models"] = [
            {"digest": "other"}, {"digest": ""}
        ]
        with self.assertRaises(RuntimeError):
            self.check(candidate, False)

    def test_allows_other_models_but_checks_all_target_entries(self):
        candidate = record()
        models = candidate["observations"][-1]["response"]["models"]
        models.append({"digest": "other", "context_length": 2048})
        self.check(candidate)
        models.append({"digest": DIGEST, "context_length": 2048})
        with self.assertRaises(RuntimeError):
            self.check(candidate)


if __name__ == "__main__":
    unittest.main()