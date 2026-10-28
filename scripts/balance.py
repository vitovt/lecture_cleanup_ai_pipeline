"""Query the configured cleanup LLM provider without making a generation request."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aiadapters.factory import create_llm_adapter
from scripts.config_loader import load_effective_config
from scripts.llm_accounting import record, report_balance


PROVIDERS = ("deepseek", "openai", "gemini", "groq", "kie", "evolink", "dummy")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Print the cleanup LLM account balance as stable key=value records.",
        epilog="Example: StartMe.sh balance --provider deepseek. Use --help for all options.",
        allow_abbrev=False,
    )
    parser.add_argument("--provider", choices=PROVIDERS,
                        help="Override the effective cleanup LLM provider")
    args = parser.parse_args(argv)
    try:
        root = ROOT
        cfg, _ = load_effective_config(root)
        provider = (args.provider or cfg["llm"]["provider"]).strip().lower()
        if provider not in PROVIDERS:
            raise ValueError("Unknown provider")
        # Stubs need neither credentials nor optional provider SDK dependencies.
        if provider != "deepseek":
            record("LLM_BALANCE", emit=print, provider=provider, phase="check", status="unsupported")
            return 0
        adapter = create_llm_adapter(cfg, provider_override=provider, project_root=root)
    except Exception:
        record("LLM_BALANCE", emit=print, provider=locals().get("provider", "unknown"),
               phase="check", status="error", reason="initialization_failed")
        return 1
    return 1 if report_balance(adapter, "check", emit=print) == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
