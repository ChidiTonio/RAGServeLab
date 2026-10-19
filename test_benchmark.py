"""Offline CLI orchestration tests; no live server access."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from benchmark import main, run_benchmark
from experiment import run_trial
from report_store import ReportStore


def successful_trial(number):
    return {
        "trial_number": number,
        "status": "success",
        "conditions": [
            {"condition": label, "status": "success", "preparation": []}
            for label in ("A", "B", "C")
        ],
    }


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "report.json"
        self.query = Mock(side_effect=[
            {"version": "test-version"},
            {"models": [{"name": "test-model", "digest": "test-digest"}]},
        ])
        self.runner = Mock(side_effect=self.complete_trial)

    def complete_trial(self, payload, digest, *, checkpoint, trial_number):
        trial = successful_trial(trial_number)
        checkpoint(trial)
        return trial

    def run_offline(self, **kwargs):
        return run_benchmark(
            "test-model",
            self.path,
            query=self.query,
            runner=self.runner,
            **kwargs,
        )

    def read_report(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_defaults_run_five_sequential_trials_and_persist_report(self):
        report = self.run_offline()
        self.assertEqual(report["status"], "success")
        self.assertEqual(report["requested_trials"], 5)
        self.assertEqual(self.read_report(), report)
        self.assertEqual(
            [call.kwargs["trial_number"] for call in self.runner.call_args_list],
            [1, 2, 3, 4, 5],
        )
        self.assertEqual(
            self.query.call_args_list,
            [unittest.mock.call("/api/version"),
             unittest.mock.call("/api/tags")],
        )
        for call in self.runner.call_args_list:
            self.assertEqual(call.args[0]["model"], "test-model")
            self.assertEqual(call.args[1], "test-digest")

    def test_custom_count_continues_after_recorded_trial_failure(self):
        def runner(payload, digest, *, checkpoint, trial_number):
            trial = successful_trial(trial_number)
            if trial_number == 1:
                trial["status"] = "error"
                trial["conditions"][0]["status"] = "error"
            checkpoint(trial)
            return trial

        self.runner.side_effect = runner
        report = self.run_offline(trials=2)
        self.assertEqual(self.runner.call_count, 2)
        self.assertEqual(report["status"], "error")
        self.assertEqual(self.read_report(), report)

    def test_incomplete_conditions_cannot_produce_success(self):
        self.runner.side_effect = lambda *args, **kwargs: {
            "trial_number": kwargs["trial_number"],
            "status": "success",
            "conditions": [],
        }
        report = self.run_offline(trials=1)
        self.assertEqual(report["status"], "error")

    def test_existing_output_is_preserved_before_any_query(self):
        self.path.write_text("existing report", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self.run_offline()
        self.assertEqual(
            self.path.read_text(encoding="utf-8"), "existing report"
        )
        self.query.assert_not_called()
        self.runner.assert_not_called()

    def test_invalid_configuration_is_rejected_before_creation(self):
        store = Mock()
        for model, trials in (
            ("", 5), ("   ", 5), ("test-model", 0),
            ("test-model", True), ("test-model", 1.5),
        ):
            with self.subTest(model=model, trials=trials):
                with self.assertRaises(ValueError):
                    run_benchmark(
                        model, self.path, trials=trials,
                        query=self.query, runner=self.runner,
                        store_factory=store,
                    )
        store.assert_not_called()
        self.query.assert_not_called()
        self.runner.assert_not_called()

    def test_invalid_metadata_is_persisted_without_running_trials(self):
        valid_version = {"version": "test-version"}
        valid_model = {"name": "test-model", "digest": "test-digest"}
        cases = [
            ([], {}),
            ({"version": ""}, {}),
            (valid_version, []),
            (valid_version, {"models": {}}),
            (valid_version, {"models": [None]}),
            (valid_version, {"models": []}),
            (valid_version, {"models": [valid_model, valid_model]}),
            (valid_version, {"models": [{"name": "test-model"}]}),
            (valid_version, {
                "models": [{"name": "test-model", "digest": "   "}]
            }),
        ]
        for index, (version, tags) in enumerate(cases):
            with self.subTest(index=index):
                path = self.path.with_name(f"invalid-{index}.json")
                query = Mock(side_effect=[version, tags])
                report = run_benchmark(
                    "test-model", path, query=query, runner=self.runner
                )
                self.assertEqual(report["status"], "error")
                self.assertEqual(report["trials"], [])
                self.assertIn("error", report)
                self.assertEqual(
                    json.loads(path.read_text(encoding="utf-8")), report
                )
        self.runner.assert_not_called()

    def test_metadata_transport_error_is_persisted(self):
        self.query.side_effect = OSError("server unavailable")
        report = self.run_offline()
        self.assertEqual(report["status"], "error")
        self.assertIn("server unavailable", report["error"])
        self.assertEqual(self.read_report(), report)
        self.runner.assert_not_called()

    def test_creation_failure_stops_before_queries(self):
        store_factory = Mock(side_effect=OSError("creation failed"))
        with self.assertRaisesRegex(OSError, "creation failed"):
            self.run_offline(store_factory=store_factory)
        self.query.assert_not_called()
        self.runner.assert_not_called()

    def test_metadata_checkpoint_failure_stops_before_trials(self):
        store = Mock()
        store.checkpoint.side_effect = OSError("checkpoint failed")
        with self.assertRaisesRegex(OSError, "checkpoint failed"):
            self.run_offline(store_factory=Mock(return_value=store))
        self.assertEqual(self.query.call_count, 2)
        store.checkpoint.assert_called_once()
        self.runner.assert_not_called()

    def test_mid_trial_checkpoint_failure_stops_further_operations(self):
        store = ReportStore(self.path, {"status": "initial"})
        original_checkpoint = store.checkpoint
        writes = 0

        def checkpoint(report):
            nonlocal writes
            writes += 1
            if writes == 3:
                raise OSError("mid-trial storage failure")
            original_checkpoint(report)

        store.checkpoint = Mock(side_effect=checkpoint)
        control = Mock(return_value={"status": "success"})
        verify = Mock()
        generation = Mock()

        def runner(payload, digest, **kwargs):
            return run_trial(
                payload, digest,
                control=control, verify=verify, generation=generation,
                **kwargs,
            )

        self.runner.side_effect = runner
        with self.assertRaisesRegex(OSError, "mid-trial storage failure"):
            self.run_offline(store_factory=Mock(return_value=store))
        self.assertEqual(store.checkpoint.call_count, 3)
        self.runner.assert_called_once()
        control.assert_called_once_with("test-model", "unload")
        verify.assert_not_called()
        generation.assert_not_called()
        persisted = self.read_report()
        self.assertEqual(persisted["status"], "running")
        self.assertEqual(len(persisted["trials"]), 1)
        self.assertEqual(
            persisted["trials"][0]["conditions"][0]["preparation"], []
        )

    def test_runner_exception_leaves_incomplete_report(self):
        self.runner.side_effect = RuntimeError("controller stopped")
        with self.assertRaisesRegex(RuntimeError, "controller stopped"):
            self.run_offline()
        self.runner.assert_called_once()
        self.assertEqual(self.read_report()["status"], "running")

    def test_main_default_count_and_success_error_exit_codes(self):
        for status, expected in (("success", 0), ("error", 1)):
            with self.subTest(status=status):
                report = {
                    "status": status,
                    "requested_trials": 5,
                    "trials": [],
                }
                with patch(
                    "benchmark.run_benchmark", return_value=report
                ) as run, redirect_stdout(io.StringIO()):
                    code = main(["--out", str(self.path)])
                self.assertEqual(code, expected)
                run.assert_called_once_with(
                    "qwen2.5:3b", self.path, trials=5
                )

    def test_main_storage_failure_and_interrupt_exit_codes(self):
        for error, expected in (
            (OSError("disk failure"), 1),
            (KeyboardInterrupt(), 130),
        ):
            with self.subTest(error=type(error).__name__):
                with patch(
                    "benchmark.run_benchmark", side_effect=error
                ) as run, redirect_stderr(io.StringIO()):
                    code = main(["--out", str(self.path)])
                self.assertEqual(code, expected)
                run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
