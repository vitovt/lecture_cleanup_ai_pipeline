import copy
from pathlib import Path
import tempfile
import unittest

import yaml

from scripts.config_loader import load_effective_config, resolve_llm_profile
from scripts.summary_generation import generation_options


class LlmProfileTests(unittest.TestCase):
    def config(self):
        return {'llm': {'provider': 'dummy', 'default_profile': 'quality',
            'dummy': {'model': 'dummy'},
            'remote': {'model': 'base', 'retry': {'attempts': 3, 'pause_seconds': 1},
                       'routing': {'order': ['a', 'b'], 'allow_fallbacks': True}},
            'profiles': {'quality': {'provider': 'remote', 'model': 'quality/model',
                'retry': {'attempts': 2}, 'routing': {'order': ['c']}}}}}

    def test_profile_merges_nested_settings_without_mutating_input(self):
        cfg = self.config()
        original = copy.deepcopy(cfg)
        effective = resolve_llm_profile(cfg)
        self.assertEqual(cfg, original)
        self.assertEqual(effective['llm']['provider'], 'remote')
        self.assertEqual(effective['llm']['active_profile'], 'quality')
        self.assertEqual(effective['llm']['remote']['routing'], {'order': ['c'], 'allow_fallbacks': True})
        self.assertEqual(effective['llm']['remote']['retry'], {'attempts': 2, 'pause_seconds': 1})
        options = generation_options(effective, retry_attempts_override=5)
        self.assertEqual(options['model'], 'quality/model')
        self.assertEqual(options['attempts'], 5)

    def test_explicit_provider_bypasses_default_profile(self):
        cfg = resolve_llm_profile(self.config(), provider_override='dummy')
        self.assertEqual(cfg['llm']['remote']['model'], 'base')
        self.assertNotIn('active_profile', cfg['llm'])

    def test_explicit_profile_accepts_matching_provider_only(self):
        self.assertEqual(resolve_llm_profile(self.config(), 'quality', 'remote')['llm']['provider'], 'remote')
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            resolve_llm_profile(self.config(), 'quality', 'dummy')

    def test_invalid_profiles_fail_early_with_available_names(self):
        for value, pattern in [('absent', 'available: quality'), ('', 'Unknown LLM profile')]:
            with self.assertRaisesRegex(ValueError, pattern):
                resolve_llm_profile(self.config(), value)
        for preset in [None, [], {}, {'provider': 'unknown'}]:
            cfg = self.config()
            cfg['llm']['profiles']['quality'] = preset
            with self.assertRaises(ValueError):
                resolve_llm_profile(cfg)

    def test_cli_selection_replaces_default_after_both_files_merge(self):
        cfg = self.config()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config.default.yaml').write_text(yaml.safe_dump(cfg))
            (root / 'config.yaml').write_text(yaml.safe_dump({'llm': {'profiles': {
                'quality': {'model': 'local/model'},
                'offline': {'provider': 'dummy', 'model': 'test-model'}}}}))
            effective, local = load_effective_config(root)
            self.assertTrue(local)
            self.assertEqual(effective['llm']['remote']['model'], 'local/model')
            selected, _ = load_effective_config(root, llm_profile='offline')
            self.assertEqual(selected['llm']['dummy']['model'], 'test-model')

    def test_no_profile_preserves_legacy_configuration(self):
        cfg = self.config()
        cfg['llm']['default_profile'] = None
        self.assertEqual(resolve_llm_profile(cfg), cfg)


if __name__ == '__main__':
    unittest.main()
