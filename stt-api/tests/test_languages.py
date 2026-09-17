import unittest

from stt_api.errors import InputError
from stt_api.languages import normalize_language, normalize_languages


class LanguageTests(unittest.TestCase):
    def test_shortcuts_and_case_are_normalized(self):
        self.assertEqual(normalize_language("uk"), "uk-UA")
        self.assertEqual(normalize_language("de-DE"), "de-DE")
        self.assertEqual(normalize_language("RU-ru"), "ru-RU")

    def test_auto_is_an_empty_hint_list(self):
        self.assertEqual(normalize_languages(["auto"]), [])

    def test_auto_cannot_be_combined(self):
        with self.assertRaises(InputError):
            normalize_languages(["auto", "de"])

    def test_invalid_language_is_rejected(self):
        with self.assertRaises(InputError):
            normalize_language("german")


if __name__ == "__main__":
    unittest.main()
