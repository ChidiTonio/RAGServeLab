"""Tests for shared benchmark request construction."""

import unittest

from probe import PROMPT, build_payload


class PayloadTests(unittest.TestCase):
    def test_payload_preserves_probe_settings(self):
        self.assertEqual(
            build_payload("test-model"),
            {
                "model": "test-model",
                "prompt": PROMPT,
                "stream": True,
                "keep_alive": "5m",
                "options": {
                    "temperature": 0,
                    "seed": 42,
                    "num_ctx": 2048,
                    "num_predict": 128,
                },
            },
        )

    def test_payloads_have_independent_nested_options(self):
        first = build_payload("test-model")
        second = build_payload("test-model")
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertIsNot(first["options"], second["options"])

        first["options"]["num_ctx"] = 4096
        self.assertEqual(second["options"]["num_ctx"], 2048)


if __name__ == "__main__":
    unittest.main()
