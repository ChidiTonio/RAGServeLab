"""Offline tests for trial sequencing, gating, and checkpoints."""

import copy
import unittest

from experiment import run_trial
from probe import build_payload


class ExperimentTests(unittest.TestCase):
    def execute(self, *, failed_control=None, failed_verify=None,
                failed_generation=None):
        events = []
        snapshots = []
        payload = build_payload("test-model")
        counts = {"control": 0, "verify": 0, "generation": 0}

        def control(model, action, **kwargs):
            counts["control"] += 1
            events.append(("control", action, kwargs))
            self.assertEqual(model, payload["model"])
            return {
                "status": (
                    "error" if counts["control"] == failed_control
                    else "success"
                ),
                "client_total_s": 0.1,
            }

        def verify(digest, present):
            counts["verify"] += 1
            events.append(("verify", present))
            self.assertEqual(digest, "test-digest")
            return {
                "status": (
                    "error" if counts["verify"] == failed_verify
                    else "success"
                ),
                "observations": [],
            }

        def generation(request):
            counts["generation"] += 1
            events.append(("generation",))
            self.assertIs(request, payload)
            # A synchronous checkpoint must precede every generation.
            current = snapshots[-1]["conditions"]
            self.assertEqual(
                sum(item["status"] == "running" for item in current), 1
            )
            if counts["generation"] == failed_generation:
                raise OSError("generation unavailable")
            return {
                "answer": "test answer",
                "client_first_text_s": 0.2,
                "client_total_s": 0.5,
                "final_event": {
                    "done": True,
                    "eval_count": 2,
                    "eval_duration": 500_000_000,
                },
            }

        trial = run_trial(
            payload,
            "test-digest",
            checkpoint=lambda record: snapshots.append(copy.deepcopy(record)),
            control=control,
            verify=verify,
            generation=generation,
        )
        return trial, events, snapshots

    def test_successful_sequence_resets_between_a_and_b(self):
        trial, events, snapshots = self.execute()
        self.assertEqual(events, [
            ("control", "unload", {}),
            ("verify", False),
            ("generation",),
            ("control", "unload", {}),
            ("verify", False),
            ("control", "load", {"num_ctx": 2048}),
            ("verify", True),
            ("generation",),
            ("verify", True),
            ("generation",),
        ])
        self.assertEqual(trial["status"], "success")
        self.assertEqual(snapshots[0]["status"], "running")
        self.assertEqual(snapshots[-1], trial)
        for condition in trial["conditions"]:
            self.assertEqual(
                condition["runtime_metrics"]["generation_tokens_per_s"], 4.0
            )

    def test_a_preparation_failure_does_not_prevent_independent_b(self):
        trial, events, snapshots = self.execute(failed_control=1)
        a, b, c = trial["conditions"]
        self.assertEqual(a["status"], "skipped")
        self.assertEqual(len(a["preparation"]), 1)
        self.assertEqual(b["status"], "success")
        self.assertEqual(c["status"], "success")
        self.assertEqual(events.count(("generation",)), 2)
        self.assertEqual(trial["status"], "error")

    def test_b_preparation_failure_skips_b_and_c(self):
        trial, events, snapshots = self.execute(failed_verify=2)
        a, b, c = trial["conditions"]
        self.assertEqual(a["status"], "success")
        self.assertEqual(b["status"], "skipped")
        self.assertEqual(c["status"], "skipped")
        self.assertEqual(events.count(("generation",)), 1)
        self.assertFalse(any(
            event[:2] == ("control", "load") for event in events
        ))

    def test_b_generation_failure_skips_c(self):
        trial, events, snapshots = self.execute(failed_generation=2)
        a, b, c = trial["conditions"]
        self.assertEqual(b["status"], "error")
        self.assertIn("generation unavailable", b["error"])
        self.assertEqual(c["status"], "skipped")
        self.assertEqual(events.count(("generation",)), 2)

    def test_c_verification_failure_prevents_repetition(self):
        trial, events, snapshots = self.execute(failed_verify=4)
        self.assertEqual(trial["conditions"][2]["status"], "skipped")
        self.assertEqual(events.count(("generation",)), 2)
        self.assertEqual(trial["status"], "error")

    def test_checkpoint_failure_propagates_before_operations(self):
        def checkpoint(record):
            raise OSError("report storage unavailable")

        def forbidden(*args, **kwargs):
            self.fail("Operations must not run after checkpoint failure.")

        with self.assertRaisesRegex(OSError, "report storage unavailable"):
            run_trial(
                build_payload("test-model"),
                "test-digest",
                checkpoint=checkpoint,
                control=forbidden,
                verify=forbidden,
                generation=forbidden,
            )


if __name__ == "__main__":
    unittest.main()
