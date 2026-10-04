from __future__ import annotations

import copy
import unittest

from scripts.summary_generation import generation_options


class SummaryRequestSettingsTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "llm": {
                "provider": "primary",
                "request_delay_seconds": 2,
                "primary": {
                    "model": "configured-model", "temperature": 0.3, "top_p": 0.8,
                    "retry": {"attempts": 3, "pause_seconds": 4},
                },
                "secondary": {"model": "other-model"},
            },
            "retry": {"attempts": 1, "pause_seconds": 1},
        }

    def test_provider_retry_overrides_global_and_cli_overrides_provider(self):
        settings = generation_options(self.cfg)
        self.assertEqual((settings["attempts"], settings["pause_seconds"]), (3, 4))
        settings = generation_options(
            self.cfg, retry_attempts_override=5, request_delay_override=0, model_override="new-model",
        )
        self.assertEqual((settings["attempts"], settings["request_delay"], settings["model"]), (5, 0, "new-model"))
        self.assertEqual((settings["temperature"], settings["top_p"]), (0.3, 0.8))

    def test_provider_override_inherits_global_retry_without_mutating_config(self):
        before = copy.deepcopy(self.cfg)
        settings = generation_options(self.cfg, provider_override=" SECONDARY ")
        self.assertEqual(settings["model"], "other-model")
        self.assertEqual((settings["attempts"], settings["pause_seconds"]), (1, 1))
        self.assertEqual(self.cfg, before)

    def test_invalid_attempts_and_nonfinite_delays_fail_before_request(self):
        for overrides in (
            {"retry_attempts_override": 0},
            {"request_delay_override": -1},
            {"request_delay_override": float("nan")},
            {"request_delay_override": float("inf")},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                generation_options(self.cfg, **overrides)


if __name__ == "__main__":
    unittest.main()
