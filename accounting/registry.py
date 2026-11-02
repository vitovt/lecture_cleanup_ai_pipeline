"""Provider capabilities and credential locations; no SDKs or requests here."""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AccountSpec:
    scope: str
    provider: str
    directory: str
    config_section: str
    key_env: Optional[str] = None
    default_api_base_url: str = ''
    checker: Optional[str] = None
    money_balance: bool = False
    subscription_quota: bool = False
    rate_limits: str = 'unsupported'


REGISTRY = {}


def register(spec):
    identity = (spec.scope, spec.provider)
    if identity in REGISTRY:
        raise ValueError(f'Duplicate account provider: {identity}')
    REGISTRY[identity] = spec


for provider, key in (
    ('deepseek', 'DEEPSEEK_API_KEY'), ('openai', 'OPENAI_API_KEY'),
    ('gemini', 'GOOGLE_API_KEY'), ('groq', 'GROQ_API_KEY'),
    ('kie', 'KIE_API_KEY'), ('evolink', 'EVOLINK_API_KEY'),
    ('openai_compatible', 'OPENAI_COMPATIBLE_API_KEY'), ('dummy', None),
):
    register(AccountSpec('cleanup', provider, '.', f'llm.{provider}', key,
                         default_api_base_url='https://api.deepseek.com' if provider == 'deepseek' else '',
                         checker='accounting.providers.deepseek:check_account' if provider == 'deepseek' else None,
                         money_balance=provider == 'deepseek',
                         rate_limits='response_headers' if provider == 'groq' else 'unsupported'))

register(AccountSpec('stt', 'groq', 'groq-api', 'api', 'GROQ_API_KEY',
                     rate_limits='response_headers'))
register(AccountSpec('stt', 'speechcore', 'speechcoreai-api', '', None))
register(AccountSpec('stt', 'gemini', 'stt-api', 'providers.gemini', 'GEMINI_API_KEY'))
register(AccountSpec('stt', 'elevenlabs', 'stt-api', 'providers.elevenlabs', 'ELEVENLABS_API_KEY',
                     default_api_base_url='https://api.elevenlabs.io',
                     checker='accounting.providers.elevenlabs:check_account', subscription_quota=True))
