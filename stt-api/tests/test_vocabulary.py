import tempfile
import unittest
from pathlib import Path

from stt_api.errors import InputError
from stt_api.vocabulary import merge_vocabulary, validate_elevenlabs_keyterms


class VocabularyTests(unittest.TestCase):
    def test_sources_are_merged_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "terms.txt").write_text(
                "# comment\nSicherheitsgruppe\nEC2 Instance\n\n", encoding="utf-8"
            )
            result = merge_vocabulary(
                ["Kubernetes", "ec2 instance"],
                ["terms.txt"],
                ["stateful firewall"],
                [],
                config_base_dir=root,
                cli_base_dir=root,
                limit=1000,
            )
            self.assertEqual(
                result,
                ["Kubernetes", "ec2 instance", "Sicherheitsgruppe", "stateful firewall"],
            )

    def test_provider_limit_is_checked_after_merge(self):
        with self.assertRaises(InputError):
            merge_vocabulary(
                ["one", "two"], [], [], [],
                config_base_dir=Path.cwd(), cli_base_dir=Path.cwd(), limit=1
            )

    def test_markdown_fences_are_ignored_in_vocabulary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "terms.txt"
            path.write_text(
                "```text\nHalbleiter\n```\n~~~\nDiode\n~~~\n", encoding="utf-8"
            )
            result = merge_vocabulary(
                [], [], [], [str(path)],
                config_base_dir=root, cli_base_dir=root, limit=1000,
            )
            self.assertEqual(result, ["Halbleiter", "Diode"])

    def test_elevenlabs_keyterms_are_validated_before_upload(self):
        validate_elevenlabs_keyterms(["Halbleiter", "p-n junction"])
        for term in ("x" * 50, "one two three four five six", "term[bad]"):
            with self.subTest(term=term), self.assertRaises(InputError):
                validate_elevenlabs_keyterms([term])


if __name__ == "__main__":
    unittest.main()
