"""Deterministic tests for control requests and failure telemetry."""

import io
import json
import unittest

from probe import BASE_URL
from residency import control_model


class ResidencyControlTests(unittest.TestCase):
    def test_control_payloads_and_empty_completion(self):
        for action in ("load", "unload"):
            with self.subTest(action=action):
                calls = []
                ticks = iter([10.0, 12.0])

                def opener(request, timeout):
                    calls.append((request, timeout))
                    return io.BytesIO(b'{"response": "", "done": true}')

                record = control_model(
                    "test-model",
                    action,
                    num_ctx=4096,
                    opener=opener,
                    clock=lambda: next(ticks),
                )

                self.assertEqual(record["status"], "success")
                self.assertEqual(record["client_total_s"], 2.0)
                self.assertEqual(len(calls), 1)
                request, timeout = calls[0]
                self.assertEqual(request.full_url, BASE_URL + "/api/generate")
                self.assertEqual(request.get_method(), "POST")
                self.assertEqual(timeout, 180)

                payload = json.loads(request.data)
                self.assertEqual(payload, record["request"])
                self.assertEqual(payload["model"], "test-model")
                self.assertEqual(payload["prompt"], "")
                self.assertIs(payload["stream"], False)
                if action == "load":
                    self.assertEqual(payload["keep_alive"], "5m")
                    self.assertEqual(payload["options"], {"num_ctx": 4096})
                else:
                    self.assertEqual(payload["keep_alive"], 0)
                    self.assertNotIn("options", payload)

    def test_transport_failure_retains_elapsed_time(self):
        ticks = iter([10.0, 13.0])

        def opener(request, timeout):
            raise OSError("connection unavailable")

        record = control_model(
            "test-model",
            "load",
            opener=opener,
            clock=lambda: next(ticks),
        )
        self.assertEqual(record["status"], "error")
        self.assertIn("connection unavailable", record["error"])
        self.assertEqual(record["client_total_s"], 3.0)

    def test_invalid_responses_are_recorded_as_failures(self):
        cases = (
            (b'{"error": "model failure"}', "model failure"),
            (b'{"done": false}', "completion event"),
            (b'[]', "JSON object"),
            (b'not json', "JSONDecodeError"),
        )
        for body, expected_error in cases:
            with self.subTest(body=body):
                def opener(request, timeout):
                    return io.BytesIO(body)

                record = control_model(
                    "test-model",
                    "load",
                    opener=opener,
                    clock=lambda: 0.0,
                )
                self.assertEqual(record["status"], "error")
                self.assertIn(expected_error, record["error"])
                self.assertEqual(record["client_total_s"], 0.0)

    def test_invalid_action_is_rejected_before_transport(self):
        def opener(request, timeout):
            self.fail("Invalid actions must not reach the transport.")

        with self.assertRaisesRegex(ValueError, "Unsupported control action"):
            control_model("test-model", "invalid", opener=opener)


if __name__ == "__main__":
    unittest.main()
