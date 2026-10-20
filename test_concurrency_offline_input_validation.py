"""Offline input validation; temporary files only, no server operations."""

import hashlib
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import concurrency_preflight as preflight
import concurrency_run_store as run_store


class OfflineInputValidationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(
            tempfile.TemporaryDirectory()
        ))

        protocol = self.root / "docs/concurrency-protocol-v1.md"
        protocol.parent.mkdir(parents=True)
        protocol.write_bytes(b"synthetic test protocol\n")

        fixture = self.root / run_store.FIXTURE
        fixture.parent.mkdir(parents=True)
        self.prompt = b"synthetic offline fixture\n"
        fixture.write_bytes(self.prompt)

        self.manifest = self.root / run_store.MANIFEST
        self.evidence = self.root / "evidence.json"
        self.evidence.write_text("{}", encoding="utf-8")

        # Test-only pins; production constants remain unchanged.
        self.stack.enter_context(patch.object(
            run_store, "PROTOCOL_HASH",
            hashlib.sha256(protocol.read_bytes()).hexdigest(),
        ))
        self.stack.enter_context(patch.object(
            run_store, "PROMPT_HASH",
            hashlib.sha256(self.prompt).hexdigest(),
        ))

    def valid_entry(self):
        return {
            "file": run_store.FIXTURE.name,
            "prompt_sha256": hashlib.sha256(self.prompt).hexdigest(),
            "utf8_bytes": len(self.prompt),
            "characters": len(self.prompt.decode("utf-8")),
        }

    def malformed_manifests(self):
        cases = [
            ("non_object", []),
            ("missing_fixtures", {}),
            ("non_list_fixtures", {"fixtures": {}}),
            ("non_object_entry", {"fixtures": [None]}),
            ("missing_file", {"fixtures": [{}]}),
            ("blank_file", {"fixtures": [{"file": " "}]}),
            ("missing_target", {"fixtures": []}),
            ("duplicate_target", {
                "fixtures": [self.valid_entry(), self.valid_entry()],
            }),
        ]
        missing_hash = self.valid_entry()
        del missing_hash["prompt_sha256"]
        cases.append(("missing_hash", {"fixtures": [missing_hash]}))
        for name, field, value in (
            ("boolean_length", "utf8_bytes", True),
            ("negative_length", "characters", -1),
            ("wrong_hash_type", "prompt_sha256", 123),
        ):
            entry = self.valid_entry()
            entry[field] = value
            cases.append((name, {"fixtures": [entry]}))
        return cases

    def write_manifest(self, value):
        self.manifest.write_text(
            json.dumps(value, allow_nan=False), encoding="utf-8"
        )

    def read_saved_report(self, directory):
        return json.loads(
            (directory / "preflight.json").read_text(encoding="utf-8")
        )

    def test_valid_manifest_preserves_offline_plan(self):
        self.write_manifest({"fixtures": [self.valid_entry()]})
        for mode, batches, requests in (
            ("calibration", 3, 7),
            ("measured", 18, 42),
        ):
            with self.subTest(mode=mode):
                plan = run_store.offline_plan(self.root, mode)
                self.assertIs(plan["live_enabled"], False)
                self.assertEqual(plan["batch_count"], batches)
                self.assertEqual(plan["request_count"], requests)
                self.assertEqual(
                    plan["payload"]["prompt"],
                    self.prompt.decode("utf-8"),
                )

    def test_malformed_manifests_raise_value_error(self):
        for name, manifest in self.malformed_manifests():
            with self.subTest(case=name):
                self.write_manifest(manifest)
                with self.assertRaises(ValueError):
                    run_store.offline_plan(self.root)

    def test_malformed_manifests_are_persisted_as_failed_reports(self):
        # Isolate evidence schema and Git checks. Exercise the real
        # planner failure through the real persistence function.
        def planning_only(root, mode):
            return run_store.offline_plan(root, mode)

        with patch.object(
            preflight, "validate_environment_evidence",
            return_value={"status": "recorded"},
        ), patch.object(
            preflight, "build_offline_execution_preflight",
            side_effect=planning_only,
        ):
            for name, manifest in self.malformed_manifests():
                with self.subTest(case=name):
                    self.write_manifest(manifest)
                    directory = self.root / f"failed-manifest-{name}"
                    report = preflight.persist_offline_preflight(
                        self.root, self.evidence, directory
                    )
                    saved = self.read_saved_report(directory)
                    self.assertEqual(saved, report)
                    self.assertEqual(saved["status"], "failed")
                    self.assertEqual(saved["error"]["type"], "ValueError")
                    self.assertEqual(
                        saved["error"]["stage"],
                        "planning_and_execution_provenance",
                    )
                    self.assertIs(saved["execution_authorized"], False)
                    self.assertIs(saved["live_enabled"], False)

    def test_nonfinite_evidence_is_rejected_before_retention(self):
        with patch.object(
            preflight, "validate_environment_evidence"
        ) as validate, patch.object(
            preflight, "build_offline_execution_preflight"
        ) as planning:
            for index, constant in enumerate(
                ("NaN", "Infinity", "-Infinity")
            ):
                with self.subTest(constant=constant):
                    raw = ('{"value": ' + constant + "}").encode("utf-8")
                    self.evidence.write_bytes(raw)
                    directory = self.root / f"nonfinite-{index}"
                    report = preflight.persist_offline_preflight(
                        self.root, self.evidence, directory
                    )
                    saved = self.read_saved_report(directory)
                    self.assertEqual(saved, report)
                    self.assertEqual(saved["status"], "failed")
                    self.assertEqual(saved["error"]["type"], "ValueError")
                    self.assertEqual(
                        saved["error"]["stage"], "environment_evidence"
                    )
                    self.assertEqual(
                        saved["environment_evidence_sha256"],
                        hashlib.sha256(raw).hexdigest(),
                    )
                    self.assertNotIn("supplied_environment_evidence", saved)
                    self.assertIsNone(saved["environment_evidence"])
                    self.assertIs(saved["execution_authorized"], False)
                    self.assertIs(saved["live_enabled"], False)

            validate.assert_not_called()
            planning.assert_not_called()


if __name__ == "__main__":
    unittest.main()
