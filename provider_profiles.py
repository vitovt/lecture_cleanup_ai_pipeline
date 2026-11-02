"""Shared YAML-independent provider preset merging for cleanup and STT."""
from copy import deepcopy


def deep_merge(base, override):
    """Merge mappings recursively; replace lists and scalars whole."""
    if isinstance(base, dict) and isinstance(override, dict):
        result = deepcopy(base)
        for key, value in override.items():
            result[key] = deep_merge(result[key], value) if key in result else deepcopy(value)
        return result
    return deepcopy(override)


def resolve_provider_profile(section, profile=None, provider_override=None, *,
                             providers_key=None, label='LLM', provider_flag='--llm-provider'):
    """Select one flat preset, without changing inputs or inheriting presets."""
    result = deepcopy(section)
    selected = profile if profile is not None else (
        None if provider_override else result.get('default_profile')
    )
    if selected is None:
        return result
    profiles = result.get('profiles', {})
    if not isinstance(profiles, dict):
        raise ValueError(f'{label} profiles must be a mapping')
    if not isinstance(selected, str) or selected not in profiles:
        raise ValueError(f'Unknown {label} profile {selected!r}; available: {", ".join(map(str, profiles)) or "none"}')
    preset = profiles[selected]
    if not isinstance(preset, dict):
        raise ValueError(f'{label} profile {selected!r} must be a mapping')
    provider = preset.get('provider')
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError(f'{label} profile {selected!r}.provider is required')
    provider = provider.strip().lower()
    if provider_override and provider_override.strip().lower() != provider:
        raise ValueError(f'{label} profile {selected!r} uses {provider}, conflicting with {provider_flag} {provider_override}')
    providers = result.get(providers_key, {}) if providers_key else result
    if not isinstance(providers, dict) or not isinstance(providers.get(provider), dict):
        raise ValueError(f'No configuration for profile provider {provider}')
    # STT profiles may also select compatible shared transcription options.
    shared_keys = {'transcription'} if providers_key else set()
    providers[provider] = deep_merge(providers[provider], {
        key: value for key, value in preset.items() if key not in {'provider'} | shared_keys
    })
    for key in shared_keys & preset.keys():
        if not isinstance(preset[key], dict):
            raise ValueError(f'{label} profile {selected!r}.{key} must be a mapping')
        result[key] = deep_merge(result.get(key, {}), preset[key])
    result['provider'] = provider
    result['active_profile'] = selected
    return result
