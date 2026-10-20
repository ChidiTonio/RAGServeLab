"""Offline CLI and storage tests."""

import copy
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from concurrency_run_store import (
    FIXTURE, MANIFEST, RunReports, file_hash, offline_plan,
)


ROOT = Path(__file__).resolve().parent


class PlanTests(unittest.TestCase):
    def test_exact_fixture_payload_and_schedule(self):
        plan = offline_plan(ROOT)
        self.assertFalse(plan["live_enabled"])
        self.assertEqual(plan["batch_count"], 18)
        self.assertEqual(plan["request_count"], 42)
        self.assertEqual(
            plan["payload"]["prompt"].encode("utf-8"),
            (ROOT / FIXTURE).read_bytes(),
        )
        self.assertEqual(plan["payload"]["options"], {
            "temperature": 0, "seed": 42,
            "num_ctx": 4096, "num_predict": 64,
        })
        calibration = offline_plan(ROOT, "calibration")
        self.assertEqual(calibration["batch_count"], 3)
        self.assertEqual(calibration["request_count"], 7)

    def test_changed_fixture_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / FIXTURE).parent.mkdir(parents=True)
            (root / FIXTURE).write_bytes(
                (ROOT / FIXTURE).read_bytes() + b"\n"
            )
            (root / MANIFEST).write_bytes((ROOT / MANIFEST).read_bytes())
            (root / "docs").mkdir()
            (root / "docs/concurrency-protocol-v1.md").write_bytes(
                (ROOT / "docs/concurrency-protocol-v1.md").read_bytes()
            )
            with self.assertRaisesRegex(ValueError, "Fixture"):
                offline_plan(root)

    def test_cli_defaults_offline_and_refuses_live(self):
        script = ROOT / "scripts/run_concurrency.py"
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, check=True,
        )
        self.assertFalse(json.loads(result.stdout)["live_enabled"])
        refused = subprocess.run(
            [sys.executable, str(script), "--live"],
            capture_output=True, text=True,
        )
        self.assertEqual(refused.returncode, 2)
        self.assertIn("Live execution is disabled", refused.stderr)


class StorageTests(unittest.TestCase):
    def report(self):
        return {
            "block": 1, "position": 1, "concurrency": 1,
            "status": "pending", "batch": None,
        }

    def test_checkpoints_journal_and_final_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = RunReports(Path(temporary) / "run", {"commit": "offline"})
            report = self.report()
            store.checkpoint(report)
            initial = copy.deepcopy(report)
            report["status"] = "success"
            store.checkpoint(report)
            store.finish({"status": "complete"})
            journal = json.loads(store.journal_store.path.read_text())
            self.assertEqual(journal["status"], "complete")
            self.assertEqual(len(journal["batches"]), 1)
            self.assertEqual(len(journal["events"]), 2)
            name = journal["batches"][0]["file"]
            self.assertEqual(
                journal["report_sha256"][name],
                file_hash(store.directory / name),
            )
            self.assertNotIn("checkpoint_at_utc", initial)
            self.assertNotIn("checkpoint_at_utc", report)
            self.assertEqual(list(store.directory.glob("*.tmp")), [])

    def test_existing_directory_is_never_reused(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(FileExistsError):
                RunReports(temporary, {})

    def test_changed_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = RunReports(Path(temporary) / "run", {})
            report = self.report()
            store.checkpoint(report)
            report["concurrency"] = 2
            with self.assertRaisesRegex(ValueError, "concurrency changed"):
                store.checkpoint(report)

    def test_worker_cannot_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = RunReports(Path(temporary) / "run", {})
            errors = []
            def worker():
                try:
                    store.checkpoint(self.report())
                except RuntimeError as exc:
                    errors.append(str(exc))
            thread = threading.Thread(target=worker)
            thread.start()
            thread.join()
            self.assertEqual(len(errors), 1)
            self.assertEqual(store.journal["events"], [])



class ProtocolIntegrityTests(unittest.TestCase):
    def test_plan_records_pinned_protocol_hash(self):
        from concurrency_run_store import PROTOCOL_HASH
        plan = offline_plan(ROOT)
        self.assertEqual(plan["protocol_sha256"], PROTOCOL_HASH)
        self.assertEqual(
            PROTOCOL_HASH,
            file_hash(ROOT / "docs/concurrency-protocol-v1.md"),
        )

    def test_changed_protocol_is_rejected_in_both_modes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "docs").mkdir()
            (root / "docs/concurrency-protocol-v1.md").write_bytes(
                (ROOT / "docs/concurrency-protocol-v1.md").read_bytes()
                + b"\n"
            )
            (root / FIXTURE).parent.mkdir(parents=True)
            (root / FIXTURE).write_bytes((ROOT / FIXTURE).read_bytes())
            (root / MANIFEST).write_bytes((ROOT / MANIFEST).read_bytes())
            for mode in ("measured", "calibration"):
                with self.subTest(mode=mode):
                    with self.assertRaisesRegex(ValueError, "Protocol"):
                        offline_plan(root, mode)

    def test_missing_protocol_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(FileNotFoundError):
                offline_plan(Path(temporary))


if __name__ == "__main__":
    unittest.main()
