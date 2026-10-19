"""Offline workload override and validation tests."""

import hashlib
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from benchmark import main, run_benchmark
from experiment import run_trial
from probe import build_payload
import test_benchmark


class WorkloadBenchmarkTests(unittest.TestCase):
    setUp = test_benchmark.BenchmarkTests.setUp
    complete_trial = test_benchmark.BenchmarkTests.complete_trial
    run_offline = test_benchmark.BenchmarkTests.run_offline
    read_report = test_benchmark.BenchmarkTests.read_report
    # Reuse the existing fake server/controller and storage assertions.
    def test_overrides_are_persisted_hashed_and_passed_to_every_trial(self):
        prompt = "  Evidence: café.\r\nQuestion: what?\r\n"
        report = self.run_offline(
            trials=2, prompt=prompt, num_ctx=4096, num_predict=32
        )
        expected = build_payload(
            "test-model", prompt=prompt, num_ctx=4096, num_predict=32
        )
        self.assertEqual(report["request"], expected)
        self.assertEqual(
            report["prompt_sha256"],
            hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(self.read_report(), report)
        for call in self.runner.call_args_list:
            self.assertEqual(call.args[0], expected)

    def test_invalid_workloads_stop_before_storage_or_queries(self):
        store = Mock()
        cases = [
            {"prompt": ""}, {"prompt": " \r\n"}, {"prompt": None},
            {"prompt": 123},
        ]
        for key in ("num_ctx", "num_predict"):
            cases.extend({key: value} for value in (0, -1, True, 1.5, "32"))
        for overrides in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    self.run_offline(store_factory=store, **overrides)
        store.assert_not_called()
        self.query.assert_not_called()
        self.runner.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_custom_context_reaches_preload_and_same_payload_reaches_abc(self):
        payload = build_payload(
            "test-model", prompt="Evidence and question.",
            num_ctx=4096, num_predict=32,
        )
        control = Mock(return_value={"status": "success"})
        verify = Mock(return_value={"status": "success"})
        generation = Mock(return_value={
            "answer": "Answer.",
            "final_event": {},
        })
        trial = run_trial(
            payload, "test-digest", checkpoint=Mock(),
            control=control, verify=verify, generation=generation,
        )
        self.assertEqual(trial["status"], "success")
        control.assert_any_call("test-model", "load", num_ctx=4096)
        self.assertEqual(generation.call_count, 3)
        for call in generation.call_args_list:
            self.assertIs(call.args[0], payload)


class WorkloadCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.out = self.root / "report.json"

    def test_cli_preserves_utf8_crlf_and_passes_overrides(self):
        source = self.root / "prompt.txt"
        prompt = "  Evidence: café.\r\nQuestion?\r\n"
        source.write_bytes(prompt.encode("utf-8"))
        report = {
            "status": "success", "requested_trials": 1, "trials": [],
        }
        with patch(
            "benchmark.run_benchmark", return_value=report
        ) as run, redirect_stdout(io.StringIO()):
            code = main([
                "--out", str(self.out), "--trials", "1",
                "--prompt-file", str(source),
                "--num-ctx", "4096", "--num-predict", "32",
            ])
        self.assertEqual(code, 0)
        run.assert_called_once_with(
            "qwen2.5:3b", self.out, trials=1,
            prompt=prompt, num_ctx=4096, num_predict=32,
        )

    def test_unreadable_or_invalid_utf8_prompt_stops_before_benchmark(self):
        missing = self.root / "missing.txt"
        invalid = self.root / "invalid.txt"
        invalid.write_bytes(b"\xff")
        for source in (missing, invalid, self.root):
            with self.subTest(source=source):
                with patch("benchmark.run_benchmark") as run:
                    with redirect_stderr(io.StringIO()):
                        code = main([
                            "--out", str(self.out),
                            "--prompt-file", str(source),
                        ])
                self.assertEqual(code, 1)
                run.assert_not_called()
                self.assertFalse(self.out.exists())

    def test_invalid_numeric_cli_options_stop_before_benchmark(self):
        for option in ("--num-ctx", "--num-predict"):
            for value in ("0", "-1", "abc"):
                with self.subTest(option=option, value=value):
                    with patch("benchmark.run_benchmark") as run:
                        with redirect_stderr(io.StringIO()):
                            with self.assertRaises(SystemExit) as raised:
                                main([
                                    "--out", str(self.out), option, value,
                                ])
                    self.assertEqual(raised.exception.code, 2)
                    run.assert_not_called()
                    self.assertFalse(self.out.exists())


if __name__ == "__main__":
    unittest.main()
