import contextlib
import io
import json
import os
import subprocess
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from aiadapters.accounting import Balance, BalanceSnapshot
from aiadapters.base import LLMAdapter, LLMConnectionError, LLMUnknownError
from aiadapters.deepseek_adapter import DeepSeekAdapter
from scripts import balance
from scripts.llm_accounting import balance_session, generate_with_usage, report_balance
from scripts.run_pipeline import call_llm
from scripts.summary_generation import (
    generate_summaries, LONG_SUMMARY_START, LONG_SUMMARY_END,
    SHORT_SUMMARY_START, SHORT_SUMMARY_END,
)
from scripts.summary_settings import resolve_summary_settings


ROOT = Path(__file__).resolve().parents[1]
USAGE = dict(prompt_tokens=100, completion_tokens=30, total_tokens=130,
             prompt_cache_hit_tokens=40, prompt_cache_miss_tokens=60,
             completion_tokens_details=dict(reasoning_tokens=20))


def response(value):
    result = contextlib.nullcontext(io.BytesIO(json.dumps(value).encode()))
    return result


def fields(line):
    return dict(field.split("=", 1) for field in line.split()[1:])


class AccountingTests(unittest.TestCase):
    def setUp(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "secret"}):
            self.adapter = DeepSeekAdapter(model="test-model")

    def generate(self, value):
        with patch("aiadapters.openai_compatible_adapter.urllib_request.urlopen",
                   return_value=response(value)):
            return generate_with_usage(self.adapter, [], stage="cleanup", model="test-model",
                                       label="chunk 2/3 (attempt 1/2)")

    def test_real_adapter_records_usage_without_changing_text(self):
        lines = []
        with patch("scripts.llm_accounting.record", side_effect=lambda event, **kw: lines.append((event, kw))):
            result = self.generate(dict(usage=USAGE, choices=[dict(message=dict(content="Result"))]))
        self.assertEqual(result, "Result")
        usage = lines[0][1]
        self.assertEqual(usage["status"], "ok")
        self.assertEqual(usage["total_tokens"], 130)
        self.assertEqual(usage["reasoning_tokens"], 20)
        self.assertEqual(usage["cache_hit_tokens"], 40)

    def test_missing_usage_does_not_reuse_previous_request(self):
        self.generate(dict(usage=USAGE))
        self.generate(dict(choices=[]))
        self.assertIsNone(self.adapter.last_usage)

    def test_cleanup_reports_numeric_part_and_attempt_without_changing_prompts(self):
        lines = []
        with patch("aiadapters.openai_compatible_adapter.urllib_request.urlopen",
                   return_value=response(dict(usage=USAGE, choices=[dict(message=dict(content="Clean"))]))), \
             patch("scripts.llm_accounting.record", side_effect=lambda event, **kw: lines.append(kw)):
            result = call_llm(self.adapter, "test-model", "System", "Text", "en", [], "italic", [], "",
                              usage_context=dict(part=2, parts=4, attempt=1, attempts=2))
        self.assertEqual(result, "Clean")
        self.assertEqual(lines[0]["stage"], "cleanup")
        self.assertEqual(lines[0]["part"], 2)
        self.assertEqual(lines[0]["attempt"], 1)

    def test_combined_summary_reports_usage_for_rejected_and_successful_response(self):
        settings = resolve_summary_settings({"summary": {
            "short": {"enabled": True}, "long": {"enabled": True}}}, "en")
        good = f"{LONG_SUMMARY_START}\nLong\n{LONG_SUMMARY_END}\n{SHORT_SUMMARY_START}\nShort\n{SHORT_SUMMARY_END}"
        values = [dict(usage=USAGE, choices=[dict(message=dict(content=text))])
                  for text in ("Invalid markers", good)]
        lines = []
        with patch("aiadapters.openai_compatible_adapter.urllib_request.urlopen",
                   side_effect=[response(value) for value in values]), \
             patch("scripts.llm_accounting.record", side_effect=lambda event, **kw: lines.append(kw)):
            result = generate_summaries(self.adapter, "test-model", "Document", settings,
                                        attempts=2, pause_seconds=0, request_delay=0)
        self.assertEqual(result, {"long": "Long", "short": "Short"})
        self.assertEqual([line["attempt"] for line in lines], [1, 2])
        self.assertEqual([line["summary"] for line in lines], ["both", "both"])
        self.assertEqual(sum(line["total_tokens"] for line in lines), 260)

    def test_transport_failure_omits_missing_usage_instead_of_zero_or_stale_usage(self):
        self.adapter._record_response(dict(usage=USAGE))
        lines = []
        with patch("aiadapters.openai_compatible_adapter.urllib_request.urlopen", side_effect=URLError("secret")), \
             patch("scripts.llm_accounting.record", side_effect=lambda event, **kw: lines.append(kw)):
            with self.assertRaises(LLMConnectionError):
                generate_with_usage(self.adapter, [], stage="summary")
        self.assertEqual(lines, [])
        self.assertIsNone(self.adapter.last_usage)

    def test_invalid_usage_is_unknown_and_reasoning_is_not_added_twice(self):
        for value in (-1, True, "100"):
            self.adapter._record_response(dict(usage={**USAGE, "prompt_tokens": value}))
            self.assertIsNone(self.adapter.last_usage)
        self.adapter._record_response(dict(usage={**USAGE, "total_tokens": 999}))
        self.assertIsNone(self.adapter.last_usage)
        self.adapter._record_response(dict(usage=USAGE))
        self.assertEqual(self.adapter.last_usage.total_tokens, 130)

    def test_balance_uses_configured_endpoint_and_decimal_values(self):
        value = dict(is_available=True, balance_infos=[dict(currency=currency,
                     total_balance="1.234567890", granted_balance="0.234567890", topped_up_balance="1.0")
                     for currency in ("USD", "CNY")])
        self.adapter._api_base = "https://example.invalid/v1"
        with patch("accounting.http.urllib_request.urlopen", return_value=response(value)) as call:
            result = self.adapter.get_balance()
        self.assertEqual(call.call_args.args[0].full_url, "https://example.invalid/v1/user/balance")
        self.assertEqual(call.call_args.kwargs["timeout"], 10)
        self.assertEqual(result.balances[0].total, Decimal("1.234567890"))
        self.assertEqual(len(result.balances), 2)

    def test_bad_balance_is_not_reported_as_zero(self):
        for value in ({}, dict(is_available=True, balance_infos=[]),
                      dict(is_available=True, balance_infos=[dict(currency="USD", total_balance="NaN",
                           granted_balance="0", topped_up_balance="0")])):
            with self.subTest(value=value), patch("accounting.http.urllib_request.urlopen",
                                                 return_value=response(value)):
                with self.assertRaises(LLMUnknownError):
                    self.adapter.get_balance()

    def test_final_balance_runs_even_when_generation_fails(self):
        lines = []
        with patch("scripts.llm_accounting.report_balance", side_effect=lambda adapter, phase: lines.append(phase)):
            with self.assertRaisesRegex(RuntimeError, "original"):
                with balance_session(self.adapter):
                    raise RuntimeError("original")
        self.assertEqual(lines, ["before", "after"])

    def test_balance_outage_is_nonfatal_and_does_not_leak_details(self):
        lines = []
        with patch.object(self.adapter, "get_balance", side_effect=RuntimeError("secret key")):
            self.assertEqual(report_balance(self.adapter, "before", emit=lines.append), "error")
        self.assertNotIn("secret", lines[0])
        self.assertEqual(fields(lines[0])["status"], "error")

    def test_balance_output_preserves_currency_and_precision(self):
        lines = []
        snapshot = BalanceSnapshot(False, (Balance("USD", Decimal("0.000001"), Decimal("0"), Decimal("0.000001")),))
        with patch.object(self.adapter, "get_balance", return_value=snapshot):
            report_balance(self.adapter, "check", emit=lines.append)
        parsed = fields(lines[0])
        self.assertEqual(parsed["total"], "0.000001")
        self.assertEqual(parsed["available"], "false")

    def test_base_class_stubs_require_no_implementation(self):
        class Stub(LLMAdapter):
            def name(self):
                return "stub"

            def generate(self, messages, **options):
                return "result"

        stub = Stub()
        self.assertIsNone(stub.get_balance())
        lines = []
        self.assertEqual(report_balance(stub, "before", emit=lines.append), "unsupported")
        with patch("scripts.llm_accounting.record") as record:
            self.assertEqual(generate_with_usage(stub, [], stage="cleanup"), "result")
        record.assert_not_called()
        self.assertEqual(lines, [])

    def test_balance_cli_default_override_and_failure_exit_codes(self):
        from accounting.models import AccountSnapshot
        snapshot = AccountSnapshot('cleanup', 'deepseek', 'ok', 'now',
                                   balances=(Balance('USD', Decimal('1.25'), Decimal('0'), Decimal('1.25')),))
        with patch.object(balance, "default_provider", return_value="deepseek"), \
             patch.object(balance, "check_account", return_value=snapshot) as check:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(balance.main([]), 0)
            check.assert_called_once_with(balance.ROOT, "cleanup", "deepseek")
            self.assertEqual(fields(output.getvalue())["total"], "1.25")
            check.reset_mock()
            check.return_value = AccountSnapshot('cleanup', 'gemini', 'unsupported', 'now')
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(balance.main(["--provider", "gemini"]), 0)
            check.assert_called_once_with(balance.ROOT, "cleanup", "gemini")
            self.assertEqual(fields(output.getvalue())["status"], "unsupported")
            check.return_value = AccountSnapshot('cleanup', 'deepseek', 'error', 'now')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(balance.main([]), 1)

    def test_launcher_help_and_strict_options_work_outside_repo(self):
        for args, expected in ((["balance", "--help"], 0),
                               (["help", "balance"], 0),
                               (["balance", "--provider", "dummy"], 0),
                               (["balance", "--provid", "deepseek"], 2)):
            result = subprocess.run([str(ROOT / "StartMe.sh"), *args], cwd="/tmp",
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, expected, result.stderr)
            if "dummy" in args:
                self.assertIn("status=unsupported", result.stdout)


if __name__ == "__main__":
    unittest.main()
