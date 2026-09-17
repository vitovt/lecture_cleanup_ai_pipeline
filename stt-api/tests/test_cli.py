import os
import unittest
from unittest.mock import patch

from stt_api.cli import main


class CliValidationTests(unittest.TestCase):
    def test_validate_requires_provider_credentials(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False):
            self.assertEqual(main(["validate", "--language-code", "uk"]), 2)

    def test_option_conflict_is_reported_before_credentials(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False):
            self.assertEqual(
                main(
                    [
                        "validate",
                        "--language-code", "uk",
                        "--custom-vocabulary", "Kubernetes",
                    ]
                ),
                2,
            )

    def test_valid_options_pass_with_credentials(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}, clear=False):
            self.assertEqual(
                main(
                    [
                        "validate",
                        "--language-code", "uk",
                        "--language-code", "de-DE",
                        "--timestamps", "off",
                        "--custom-vocabulary", "Sicherheitsgruppe",
                    ]
                ),
                0,
            )


if __name__ == "__main__":
    unittest.main()
