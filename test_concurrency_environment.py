"""Offline tests for supplied environment evidence."""

import copy
import json
import unittest
from pathlib import Path

from concurrency_preflight import validate_environment_evidence


ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "tests/fixtures/concurrency-environment-synthetic-v1.json"


class EnvironmentEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_saved_evidence_is_recorded_not_preflight_success(self):
        record = validate_environment_evidence(self.evidence)
        self.assertEqual(record["status"], "recorded")
        self.assertFalse(record["live_enabled"])
        self.assertFalse(record["execution_authorized"])
        self.assertIn(
            "effective_windows_server_parallelism", record["unverified"]
        )

    def test_returned_evidence_is_an_independent_snapshot(self):
        before = copy.deepcopy(self.evidence)
        record = validate_environment_evidence(self.evidence)
        record["evidence"]["observations"].clear()
        self.assertEqual(self.evidence, before)

    def test_missing_observations_are_rejected(self):
        for name in self.evidence["observations"]:
            with self.subTest(name=name):
                changed = copy.deepcopy(self.evidence)
                del changed["observations"][name]
                with self.assertRaises(ValueError):
                    validate_environment_evidence(changed)

    def test_authorization_and_verification_claims_are_rejected(self):
        changes = [
            (("live_enabled",), True),
            (("execution_authorized",), True),
            (("observations", "startup_log", "verified"), True),
            (("observations", "model_recollection",
              "exact_model_tag_verified"), True),
            (("observations", "model_recollection",
              "model_digest_verified"), True),
            (("observations", "ac_power", "source"),
             "independently_verified"),
        ]
        for keys, value in changes:
            with self.subTest(keys=keys):
                changed = copy.deepcopy(self.evidence)
                target = changed
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = value
                with self.assertRaises(ValueError):
                    validate_environment_evidence(changed)

    def test_invalid_timestamp_and_nonfinite_data_are_rejected(self):
        for key, value in (
            ("recorded_at_utc", "2026-10-20T09:00:00"),
            ("extra_numeric_field", float("nan")),
        ):
            with self.subTest(key=key):
                changed = copy.deepcopy(self.evidence)
                changed[key] = value
                with self.assertRaises(ValueError):
                    validate_environment_evidence(changed)


if __name__ == "__main__":
    unittest.main()
