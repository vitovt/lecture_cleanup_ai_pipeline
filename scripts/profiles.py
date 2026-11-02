#!/usr/bin/env python3
"""List configured model presets without loading SDKs, keys, or making requests."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.config_loader import load_default_and_local, deep_merge


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', choices=('cleanup', 'stt'), default='cleanup')
    args = parser.parse_args(argv)
    try:
        base = ROOT if args.scope == 'cleanup' else ROOT / 'stt-api'
        default, local, _ = load_default_and_local(base)
        config = deep_merge(default, local)
        section = config.get('llm', {}) if args.scope == 'cleanup' else config
        providers = section if args.scope == 'cleanup' else section.get('providers', {})
        profiles = section.get('profiles', {})
        if not isinstance(profiles, dict):
            raise ValueError('profiles must be a mapping')
        print(f"scope={args.scope} default_profile={section.get('default_profile') or 'none'}")
        for name, preset in profiles.items():
            if not isinstance(preset, dict):
                raise ValueError(f'profile {name!r} must be a mapping')
            provider = preset.get('provider', '')
            model = preset.get('model', providers.get(provider, {}).get('model', ''))
            print(f"{name}: provider={provider} model={model}")
        if not profiles:
            print('No profiles configured. Add profiles to config.yaml; see Docs/PROFILES.md.')
        return 0
    except (OSError, ValueError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
