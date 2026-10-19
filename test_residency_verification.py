"""Tests for digest-based residency observation and unknown-state handling."""

import unittest

from residency import verify_residency


class ResidencyVerificationTests(unittest.TestCase):
    def run_verification(self, snapshots, expected_present, **options):
        remaining = iter(snapshots)
        calls = []
        sleeps = []

        def query(path):
            calls.append(path)
            value = next(remaining)
            if isinstance(value, Exception):
                raise value
            return value

        record = verify_residency(
            "target-digest",
            expected_present,
            query=query,
            clock=lambda: 0.0,
            sleep=sleeps.append,
            **options,
        )
        return record, calls, sleeps

    def test_present_digest_stops_after_first_match(self):
        record, calls, sleeps = self.run_verification(
            [{"models": [{"digest": "target-digest", "name": "alias"}]}],
            True,
        )
        self.assertEqual(record["status"], "success")
        self.assertIs(record["observations"][0]["present"], True)
        self.assertEqual(calls, ["/api/ps"])
        self.assertEqual(sleeps, [])

    def test_valid_empty_snapshot_verifies_absence(self):
        record, calls, sleeps = self.run_verification(
            [{"models": []}], False
        )
        self.assertEqual(record["status"], "success")
        self.assertIs(record["observations"][0]["present"], False)
        self.assertEqual(len(calls), 1)
        self.assertEqual(sleeps, [])

    def test_query_error_is_retained_before_success(self):
        record, calls, sleeps = self.run_verification(
            [
                OSError("query unavailable"),
                {"models": [{"digest": "target-digest"}]},
            ],
            True,
        )
        self.assertEqual(record["status"], "success")
        first = record["observations"][0]
        self.assertEqual(first["status"], "error")
        self.assertIn("query unavailable", first["error"])
        self.assertNotIn("present", first)
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, [0.25])

    def test_unknown_or_opposite_state_exhausts_budget(self):
        cases = (
            {},
            {"models": [{}]},
            {"models": [{"digest": "target-digest"}]},
        )
        for snapshot in cases:
            with self.subTest(snapshot=snapshot):
                record, calls, sleeps = self.run_verification(
                    [snapshot, snapshot],
                    False,
                    max_attempts=2,
                )
                self.assertEqual(record["status"], "error")
                self.assertEqual(len(calls), 2)
                self.assertEqual(sleeps, [0.25])
                self.assertIn("query budget", record["error"])
                if snapshot != cases[2]:
                    for observation in record["observations"]:
                        self.assertNotIn("present", observation)

    def test_invalid_configuration_is_rejected_before_query(self):
        def query(path):
            self.fail("Invalid configuration must not issue a query.")

        cases = (
            {"digest": ""},
            {"expected_present": "false"},
            {"max_attempts": 0},
            {"interval_s": -1},
            {"interval_s": float("nan")},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                arguments = {
                    "digest": "target-digest",
                    "expected_present": True,
                    "query": query,
                }
                arguments.update(changes)
                with self.assertRaises(ValueError):
                    verify_residency(**arguments)


if __name__ == "__main__":
    unittest.main()
