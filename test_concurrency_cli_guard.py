"""CLI rejection tests; no planning, transports, or model operations."""

import importlib.util
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent


class CliGuardTests(unittest.TestCase):
    def test_live_is_rejected_before_planning_in_both_modes(self):
        spec = importlib.util.spec_from_file_location(
            "concurrency_cli_guard_target",
            ROOT / "scripts" / "run_concurrency.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for mode in ("measured", "calibration"):
            with self.subTest(mode=mode):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with patch.object(
                    module, "offline_plan",
                    side_effect=AssertionError("Planning must not start"),
                ) as plan, redirect_stdout(stdout), redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as raised:
                        module.main(["--mode", mode, "--live"])

                self.assertEqual(raised.exception.code, 2)
                self.assertIn(
                    "Live execution is disabled", stderr.getvalue()
                )
                self.assertEqual(stdout.getvalue(), "")
                plan.assert_not_called()


if __name__ == "__main__":
    unittest.main()
