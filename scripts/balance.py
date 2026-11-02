"""One CLI for cleanup/STT account balances and subscription quotas."""

import argparse
from dataclasses import asdict
from decimal import Decimal
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from accounting.models import AccountSnapshot, utc_now
from accounting.registry import REGISTRY
from accounting.service import check_account, default_provider, inspect_account
from scripts.llm_accounting import record


def emit_snapshot(snapshot):
    """Keep the existing cleanup event and amount fields backward compatible."""
    event = 'LLM_BALANCE' if snapshot.scope == 'cleanup' else 'ACCOUNT_BALANCE'
    fields = dict(scope=snapshot.scope, provider=snapshot.provider, phase='check',
                  status=snapshot.status, checked_at=snapshot.checked_at)
    if snapshot.reason:
        fields['reason'] = snapshot.reason
    if snapshot.available is not None:
        fields['available'] = str(snapshot.available).lower()
    if snapshot.tier is not None:
        fields['tier'] = snapshot.tier
    if snapshot.subscription_status is not None:
        fields['subscription_status'] = snapshot.subscription_status
    if snapshot.balances:
        for balance in snapshot.balances:
            record(event, emit=print, **fields, currency=balance.currency,
                   total=format(balance.total, 'f'), granted=format(balance.granted, 'f'),
                   topped_up=format(balance.topped_up, 'f'))
    else:
        record(event, emit=print, **fields)
    for quota in snapshot.quotas:
        record('ACCOUNT_QUOTA', emit=print, scope=snapshot.scope, provider=snapshot.provider,
               checked_at=snapshot.checked_at, **{
                   key: value if value is not None else 'unknown'
                   for key, value in asdict(quota).items()})


def json_default(value):
    if isinstance(value, Decimal):
        return format(value, 'f')
    raise TypeError(type(value).__name__)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Check cleanup/STT accounts without generation or transcription requests.',
        epilog=('Examples: StartMe.sh balance; StartMe.sh balance --scope stt --provider elevenlabs; '
                'StartMe.sh balance --all --format json. Without --scope, --all/--list cover both scopes.'),
        allow_abbrev=False,
    )
    parser.add_argument('--scope', choices=('cleanup', 'stt'),
                        help='Credential/configuration scope; default for a single check: cleanup')
    parser.add_argument('--provider', choices=sorted({provider for _, provider in REGISTRY}),
                        help='Provider in the selected scope; omitted: configured default provider')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--all', action='store_true', help='Check configured accounts; report unconfigured entries too')
    selection.add_argument('--list', action='store_true', help='List capabilities and configuration state without HTTP')
    parser.add_argument('--format', choices=('text', 'json'), default='text',
                        help='key=value records (default) or a JSON array; decimals are strings')
    args = parser.parse_args(argv)
    if args.provider and (args.all or args.list):
        parser.error('--provider cannot be combined with --all or --list')
    specs = [spec for spec in REGISTRY.values() if args.scope is None or spec.scope == args.scope]
    if args.list:
        entries = [inspect_account(ROOT, spec) for spec in specs]
        if args.format == 'json':
            print(json.dumps(entries, ensure_ascii=False))
        else:
            for entry in entries:
                record('ACCOUNT_PROVIDER', emit=print, **{
                    key: str(value).lower() if isinstance(value, bool) else value if value is not None else 'none'
                    for key, value in entry.items()})
        return int(any(entry['configuration'] == 'error' for entry in entries))
    if args.all:
        results = []
        for spec in specs:
            state = inspect_account(ROOT, spec)
            if state['configuration'] in ('not_configured', 'error'):
                results.append(AccountSnapshot(spec.scope, spec.provider, state['configuration'],
                                               utc_now(), reason=state['reason']))
            else:
                results.append(check_account(ROOT, spec.scope, spec.provider))
    else:
        scope = args.scope or 'cleanup'
        try:
            provider = args.provider or default_provider(ROOT, scope)
        except Exception:
            results = [AccountSnapshot(scope, 'unknown', 'error', utc_now(), reason='invalid_configuration')]
        else:
            if (scope, provider) not in REGISTRY:
                if args.provider:
                    parser.error(f'provider {provider} is not registered in scope {scope}')
                results = [AccountSnapshot(scope, provider, 'error', utc_now(), reason='unregistered_provider')]
            else:
                results = [check_account(ROOT, scope, provider)]
    if args.format == 'json':
        print(json.dumps([asdict(result) for result in results], default=json_default, ensure_ascii=False))
    else:
        for result in results:
            emit_snapshot(result)
    # Missing credentials are expected in an inventory, but fail an explicit check.
    failed = {'error'} if args.all else {'error', 'not_configured'}
    return int(any(result.status in failed for result in results))


if __name__ == '__main__':
    raise SystemExit(main())
