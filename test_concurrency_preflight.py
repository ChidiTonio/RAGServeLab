"""Offline tests: no server requests or model control operations."""

import copy
import unittest

from concurrency_preflight import (
    EXPECTED_SERVER_VERSION,
    validate_server_metadata,
)
from concurrency_run_store import MODEL, DIGEST


class ServerMetadataTests(unittest.TestCase):
    def setUp(self):
        self.version = {"version": EXPECTED_SERVER_VERSION}
        self.tags = {
            "models": [{
                "name": MODEL,
                "digest": DIGEST,
                "details": {"parameter_size": "3.1B"},
            }]
        }

    def test_valid_responses_retain_evidence_without_enabling_live(self):
        record = validate_server_metadata(self.version, self.tags)
        self.assertEqual(record["status"], "success")
        self.assertFalse(record["live_enabled"])
        self.assertEqual(record["server_version_response"], self.version)
        self.assertEqual(record["model_tags_response"], self.tags)
        self.assertEqual(
            record["selected_model_metadata"], self.tags["models"][0]
        )

    def test_version_mismatch_and_malformed_responses_are_rejected(self):
        for version in (
            None, [], {}, {"version": "different"}, {"version": 0.406}
        ):
            with self.subTest(version=version):
                with self.assertRaises(ValueError):
                    validate_server_metadata(version, self.tags)

    def test_missing_and_duplicate_target_models_are_rejected(self):
        for models in (
            [],
            [{"name": "other:latest", "digest": "other-digest"}],
            self.tags["models"] * 2,
        ):
            with self.subTest(models=models):
                with self.assertRaisesRegex(ValueError, "exactly one"):
                    validate_server_metadata(
                        self.version, {"models": models}
                    )

    def test_wrong_target_digest_is_rejected(self):
        tags = copy.deepcopy(self.tags)
        tags["models"][0]["digest"] = "wrong-digest"
        with self.assertRaisesRegex(ValueError, "digest does not match"):
            validate_server_metadata(self.version, tags)

    def test_malformed_tags_and_entries_are_rejected(self):
        for tags in (
            None, [], {}, {"models": None}, {"models": {}},
            {"models": [None]},
            {"models": [{"name": MODEL}]},
            {"models": [{"name": "", "digest": DIGEST}]},
            {"models": [{"name": MODEL, "digest": 123}]},
            {"models": self.tags["models"] + [{"name": "other"}]},
        ):
            with self.subTest(tags=tags):
                with self.assertRaises(ValueError):
                    validate_server_metadata(self.version, tags)

    def test_inputs_and_returned_evidence_are_independent(self):
        original = copy.deepcopy(self.tags)
        record = validate_server_metadata(self.version, self.tags)
        record["selected_model_metadata"]["details"]["parameter_size"] = "X"
        self.assertEqual(self.tags, original)
        self.assertEqual(record["model_tags_response"], original)
        self.tags["models"][0]["details"]["parameter_size"] = "Y"
        self.version["version"] = "changed"
        self.assertEqual(record["model_tags_response"], original)
        self.assertEqual(
            record["server_version_response"]["version"],
            EXPECTED_SERVER_VERSION,
        )


if __name__ == "__main__":
    unittest.main()
