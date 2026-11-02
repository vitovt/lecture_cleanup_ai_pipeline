"""One OpenRouter account-credit checker for cleanup and STT scopes."""
from decimal import Decimal, InvalidOperation

from accounting.http import AccountError, get_json
from accounting.models import Balance


def check_account(settings):
    response = get_json(f'{settings.api_base_url.rstrip("/")}/credits',
                        {'Authorization': f'Bearer {settings.api_key}'}, settings.timeout)
    try:
        data = response['data']
        values = []
        for field in ('total_credits', 'total_usage'):
            value = data[field]
            if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
                raise ValueError
            number = Decimal(str(value))
            if not number.is_finite() or number < 0:
                raise ValueError
            values.append(number)
        remaining = values[0] - values[1]
    except (KeyError, TypeError, ValueError, InvalidOperation):
        raise AccountError('invalid_response') from None
    # OpenRouter does not split remaining credits into grants and top-ups.
    return dict(status='ok', available=remaining > 0,
                balances=(Balance('USD', remaining),))
