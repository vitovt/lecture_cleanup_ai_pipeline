"""Verify the dummy provider works with shipped defaults."""
from pathlib import Path
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


class DummyProviderTests(unittest.TestCase):
    def test_dummy_with_default_configuration(self):
        import yaml
        from aiadapters.factory import create_llm_adapter
        cfg = yaml.safe_load((PROJECT / 'config.default.yaml').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            adapter = create_llm_adapter(cfg, provider_override='dummy', project_root=Path(tmp))
        self.assertEqual(adapter.name(), 'dummy')
