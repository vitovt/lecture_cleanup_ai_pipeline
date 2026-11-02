"""Provider-neutral account checks usable without a generation adapter."""
from dataclasses import replace
from importlib import import_module

from accounting.credentials import resolve_settings
from accounting.http import AccountError
from accounting.models import AccountSnapshot, utc_now
from accounting.registry import REGISTRY
from scripts.config_loader import load_effective_config


def default_provider(root, scope):
    cfg, _ = load_effective_config(root if scope == 'cleanup' else root / 'stt-api')
    return (cfg['llm']['provider'] if scope == 'cleanup' else cfg['provider']).strip().lower()


def inspect_account(root, spec):
    """No HTTP, no environment mutation, no provider SDK imports."""
    try:
        if not spec.key_env:
            state = 'unsupported'
        else:
            resolve_settings(root, spec)
            state = 'configured'
        reason = None
    except AccountError as exc:
        state = 'not_configured' if exc.reason in ('missing_credentials', 'component_not_installed') else 'error'
        reason = exc.reason
    except Exception:
        state, reason = 'error', 'invalid_configuration'
    return dict(scope=spec.scope, provider=spec.provider, configuration=state,
                reason=reason, money_balance=spec.money_balance,
                subscription_quota=spec.subscription_quota, rate_limits=spec.rate_limits)


def check_account(root, scope, provider):
    spec = REGISTRY[(scope, provider)]
    result = AccountSnapshot(scope, provider, 'unsupported', utc_now())
    # Unsupported checks need no credentials, config, SDK or probing requests.
    if not spec.checker:
        return replace(result, reason='account_check_not_supported')
    try:
        settings = resolve_settings(root, spec)
        module, name = spec.checker.split(':')
        values = getattr(import_module(module), name)(settings)
        return replace(result, **values)
    except AccountError as exc:
        return replace(result, status='not_configured' if exc.reason in ('missing_credentials', 'component_not_installed') else 'error',
                       reason=exc.reason)
    except Exception:
        return replace(result, status='error', reason='invalid_configuration')
