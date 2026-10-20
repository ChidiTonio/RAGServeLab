"""Offline provenance checks using temporary local Git repositories."""

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from concurrency_provenance import (
    REQUIRED_FILES, capture_provenance, verify_provenance,
)


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Offline Test")
        self.git("config", "user.email", "offline@example.invalid")
        (self.root / "required.txt").write_bytes(b"fixed\n")
        self.git("add", "--", "required.txt")
        self.git("commit", "-q", "-m", "Offline fixture")

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=True, capture_output=True,
        ).stdout

    def capture(self):
        return capture_provenance(self.root, ("required.txt",))

    def test_clean_commit_records_exact_hash_and_untracked_paths(self):
        (self.root / "unrelated.txt").write_bytes(b"not an input")
        record = self.capture()
        self.assertEqual(
            record["execution_commit"],
            self.git("rev-parse", "HEAD").decode().strip(),
        )
        self.assertEqual(
            record["file_sha256"]["required.txt"],
            hashlib.sha256(b"fixed\n").hexdigest(),
        )
        self.assertEqual(record["untracked_paths"], ["unrelated.txt"])
        self.assertEqual(verify_provenance(self.root, record), record)

    def test_unstaged_and_staged_changes_are_rejected(self):
        (self.root / "required.txt").write_bytes(b"changed\n")
        with self.assertRaisesRegex(ValueError, "Tracked modifications"):
            self.capture()
        self.git("add", "--", "required.txt")
        with self.assertRaisesRegex(ValueError, "Tracked modifications"):
            self.capture()

    def test_untracked_required_file_is_rejected(self):
        (self.root / "new.txt").write_bytes(b"new")
        with self.assertRaisesRegex(ValueError, "absent from execution commit"):
            capture_provenance(self.root, ("required.txt", "new.txt"))

    def test_default_manifest_rejects_uncommitted_batch_validation(self):
        dependency = "concurrency_batch_validation.py"
        self.assertIn(dependency, REQUIRED_FILES)

        for name in REQUIRED_FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"offline provenance fixture\n")
            if name != dependency:
                self.git("add", "--", name)
        self.git("commit", "-q", "-m", "Default manifest except dependency")

        with self.assertRaisesRegex(
            ValueError,
            "absent from execution commit: concurrency_batch_validation",
        ):
            capture_provenance(self.root)

    def test_new_clean_commit_fails_baseline_verification(self):
        baseline = self.capture()
        (self.root / "other.txt").write_bytes(b"new committed file")
        self.git("add", "--", "other.txt")
        self.git("commit", "-q", "-m", "Different revision")
        with self.assertRaisesRegex(ValueError, "provenance changed"):
            verify_provenance(self.root, baseline)

    def test_missing_and_escaping_required_paths_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            capture_provenance(self.root, ("missing.txt",))
        with self.assertRaisesRegex(ValueError, "Invalid"):
            capture_provenance(self.root, ("../outside.txt",))


if __name__ == "__main__":
    unittest.main()
