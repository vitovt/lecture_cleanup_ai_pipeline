"""ElevenLabs subscription allowance, not a cash or Scribe-specific balance.

Reference: https://elevenlabs.io/docs/api-reference/user/subscription/get
"""
from datetime import datetime, timezone

from accounting.http import AccountError, get_json
from accounting.models import Quota


def check_account(settings):
    data = get_json(f'{settings.api_base_url}/v1/user/subscription',
                    {'xi-api-key': settings.api_key}, settings.timeout)
    used, limit = data.get('character_count'), data.get('character_limit')
    if any(type(value) is not int or value < 0 for value in (used, limit)):
        raise AccountError('invalid_response')
    reset = data.get('next_character_count_reset_unix')
    resets_at = None
    if reset is not None:
        try:
            if type(reset) is not int or reset < 0:
                raise ValueError
            resets_at = datetime.fromtimestamp(reset, timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            raise AccountError('invalid_response') from None
    tier, status = data.get('tier'), data.get('status')
    if any(value is not None and not isinstance(value, str) for value in (tier, status)):
        raise AccountError('invalid_response')
    quota = Quota('subscription_characters', 'characters', used, limit,
                  max(0, limit - used), max(0, used - limit), resets_at)
    return dict(status='partial', reason='monetary_balance_unavailable',
                quotas=(quota,), tier=tier, subscription_status=status)
