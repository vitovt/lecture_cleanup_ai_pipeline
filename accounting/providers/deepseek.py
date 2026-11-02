from decimal import Decimal

from accounting.http import AccountError, get_json
from accounting.models import Balance, BalanceSnapshot


def fetch_balance(api_key, api_base_url='https://api.deepseek.com', timeout=10):
    data = get_json(f'{api_base_url.rstrip("/")}/user/balance',
                    {'Authorization': f'Bearer {api_key}'}, timeout)
    try:
        if type(data.get('is_available')) is not bool:
            raise ValueError
        entries = data['balance_infos']
        if not isinstance(entries, list) or not entries:
            raise ValueError
        balances, currencies = [], set()
        for entry in entries:
            currency = entry['currency']
            if currency not in ('USD', 'CNY') or currency in currencies:
                raise ValueError
            currencies.add(currency)
            values = [Decimal(entry[key]) for key in
                      ('total_balance', 'granted_balance', 'topped_up_balance')]
            if any(not value.is_finite() for value in values):
                raise ValueError
            balances.append(Balance(currency, *values))
        return BalanceSnapshot(data['is_available'], tuple(balances))
    except Exception:
        raise AccountError('invalid_response') from None


def check_account(settings):
    result = fetch_balance(settings.api_key, settings.api_base_url, settings.timeout)
    return dict(status='ok', available=result.available, balances=result.balances)
