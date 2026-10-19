"""Offline report-storage tests using temporary directories."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from report_store import ReportStore


class ReportStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "reports" / "trial.json"

    def read_report(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_initial_creation_makes_parents_and_writes_report(self):
        initial = {"status": "running", "trials": []}
        ReportStore(self.path, initial)
        self.assertEqual(self.read_report(), initial)
        self.assertTrue(
            self.path.read_text(encoding="utf-8").endswith("\n")
        )

    def test_existing_output_is_not_overwritten(self):
        ReportStore(self.path, {"status": "original"})
        original = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            ReportStore(self.path, {"status": "replacement"})
        self.assertEqual(self.path.read_bytes(), original)

    def test_checkpoint_replaces_complete_report_and_cleans_temporary(self):
        store = ReportStore(self.path, {"status": "running"})
        completed = {"status": "success", "trials": [{"trial_number": 1}]}
        store.checkpoint(completed)
        self.assertEqual(self.read_report(), completed)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_serialization_failure_preserves_previous_checkpoint(self):
        store = ReportStore(self.path, {"status": "running"})
        original = self.path.read_bytes()
        for invalid in ({"bad": object()}, {"bad": float("nan")}):
            with self.subTest(invalid=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    store.checkpoint(invalid)
                self.assertEqual(self.path.read_bytes(), original)
                self.assertEqual(
                    list(self.path.parent.iterdir()), [self.path]
                )

    def test_replace_failure_preserves_previous_checkpoint(self):
        store = ReportStore(self.path, {"status": "running"})
        original = self.path.read_bytes()
        with patch(
            "report_store.os.replace",
            side_effect=OSError("replacement unavailable"),
        ):
            with self.assertRaisesRegex(OSError, "replacement unavailable"):
                store.checkpoint({"status": "success"})
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])


if __name__ == "__main__":
    unittest.main()
