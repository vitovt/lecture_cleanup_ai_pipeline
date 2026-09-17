import tempfile
import unittest
from pathlib import Path

from stt_api.errors import InputError
from stt_api.vocabulary import merge_vocabulary


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
                base_dir=root,
                limit=1000,
            )
            self.assertEqual(
                result,
                ["Kubernetes", "ec2 instance", "Sicherheitsgruppe", "stateful firewall"],
            )

    def test_provider_limit_is_checked_after_merge(self):
        with self.assertRaises(InputError):
            merge_vocabulary(
                ["one", "two"], [], [], [], base_dir=Path.cwd(), limit=1
            )


if __name__ == "__main__":
    unittest.main()
