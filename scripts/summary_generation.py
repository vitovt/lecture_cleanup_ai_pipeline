"""Shared summary prompts, generation, references, and Markdown rendering."""

from __future__ import annotations

import re
import math
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from aiadapters.base import (
    LLMAdapter, LLMAuthError, LLMConnectionError, LLMRateLimitError, LLMUnknownError,
)
from scripts.logging_helper import log_debug, log_trace, log_trace_block, log_warn
from scripts.summary_references import (
    render_long_summary_reference_display, validate_long_summary_references,
)
from scripts.summary_settings import SummarySettings

LONG_SUMMARY_START = "<!-- LECTURE_CLEANUP_LONG_SUMMARY_START -->"
LONG_SUMMARY_END = "<!-- LECTURE_CLEANUP_LONG_SUMMARY_END -->"
SHORT_SUMMARY_START = "<!-- LECTURE_CLEANUP_SHORT_SUMMARY_START -->"
SHORT_SUMMARY_END = "<!-- LECTURE_CLEANUP_SHORT_SUMMARY_END -->"
SUMMARY_BLOCK_NOTICE = (
    "AI NOTICE: This block is an AI-generated summary of the source text, "
    "not additional source material. Do not analyze it as source."
)
LONG_SUMMARY_BLOCK_START = (
    f"<!-- LECTURE_CLEANUP_LONG_SUMMARY_START | {SUMMARY_BLOCK_NOTICE} -->"
)
LONG_SUMMARY_BLOCK_END = "<!-- LECTURE_CLEANUP_LONG_SUMMARY_END -->"
SHORT_SUMMARY_BLOCK_START = (
    f"<!-- LECTURE_CLEANUP_SHORT_SUMMARY_START | {SUMMARY_BLOCK_NOTICE} -->"
)
SHORT_SUMMARY_BLOCK_END = "<!-- LECTURE_CLEANUP_SHORT_SUMMARY_END -->"


def generation_options(cfg, *, provider_override=None, model_override=None,
                       request_delay_override=None, retry_attempts_override=None):
    """Resolve model parameters and retry precedence for both entry points."""
    llm = cfg["llm"]
    provider = (provider_override or llm["provider"]).strip().lower()
    if provider not in llm or not isinstance(llm[provider], dict):
        raise ValueError(f"No LLM configuration for provider {provider}")
    configured = llm[provider]
    model = model_override or configured.get("model")
    if not isinstance(model, str) or not model.strip():
        raise ValueError(f"Missing model in config under llm.{provider}.model")
    retry = {**cfg.get("retry", {}), **configured.get("retry", {})}
    attempts = int(retry_attempts_override if retry_attempts_override is not None else retry.get("attempts", 1))
    pause = float(retry.get("pause_seconds", 0) or 0)
    delay = float(request_delay_override if request_delay_override is not None else llm.get("request_delay_seconds", 0) or 0)
    if attempts < 1 or not math.isfinite(pause) or pause < 0 or not math.isfinite(delay) or delay < 0:
        raise ValueError("Retry attempts must be positive; delay and pause must be finite and non-negative")
    return dict(provider=provider, model=model, temperature=configured.get("temperature"),
                top_p=configured.get("top_p"), attempts=attempts,
                pause_seconds=pause, request_delay=delay)


def _extract_retry_after_seconds(msg: str) -> Optional[float]:
    """Best-effort parse of provider-suggested retry-after seconds from error text.
    Supports patterns like 'retry in 17.8s' and 'retry_delay { seconds: 17 }'.
    """
    if not msg:
        return None
    m = re.search(r"retry\s+in\s+([0-9]+(?:\.[0-9]+)?)s", msg, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return None
    m2 = re.search(r"retry_delay\s*\{\s*seconds:\s*([0-9]+)\s*\}", msg, re.IGNORECASE)
    if m2:
        try:
            return float(m2.group(1))
        except Exception:
            return None
    return None


def _load_summary_prompt(
    summary_type: str,
    summary_lang: str,
    source_link_prefix: Optional[str] = None,
) -> Tuple[str, str]:
    if summary_type not in ("short", "long"):
        raise ValueError(f"Unsupported summary type: {summary_type}")
    base = Path(__file__).parent.parent
    prefix = "summary" if summary_type == "short" else "long_summary"
    summary_system_path = base / "prompts" / f"{prefix}_system.md"
    summary_user_path = base / "prompts" / f"{prefix}_user.md"
    summary_system_content = summary_system_path.read_text(encoding="utf-8")
    summary_user_content = summary_user_path.read_text(encoding="utf-8")
    prompt_lang = summary_lang.strip().lower() or "default"
    summary_system_content = summary_system_content.replace(
        "{SUMMARY_LANGUAGE}", prompt_lang
    )
    summary_user_content = summary_user_content.replace(
        "{SUMMARY_LANGUAGE}", prompt_lang
    )
    if summary_type == "long":
        if source_link_prefix is not None:
            references_path = base / "prompts" / "long_summary_references.md"
            references_content = references_path.read_text(encoding="utf-8")
            references_content = references_content.replace(
                "{SOURCE_LINK_PREFIX}", source_link_prefix
            )
            summary_system_content = (
                summary_system_content.rstrip()
                + "\n\n"
                + references_content.strip()
                + "\n"
            )
    return summary_system_content, summary_user_content


def _call_summary_request(
    adapter: LLMAdapter,
    model: str,
    full_markdown: str,
    system_content: str,
    user_content: str,
    temperature: float = 1.0,
    top_p: float = None,
    debug: bool = False,
    trace: bool = False,
    label: str = None,
) -> str:
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content + "\n\n<<<\n" + full_markdown + "\n>>>"},
    ]
    trace_label = f" [{label}]" if label else ""
    if trace:
        log_trace(f"Summary request BEGIN{trace_label}")
        log_trace(f"Model: {model} | temperature: {temperature} | top_p: {top_p}")
        log_trace_block("System prompt (summary)", system_content)
        log_trace_block("User prompt (summary)", user_content)
        log_trace_block("Document (full markdown)", full_markdown)
        log_trace(f"Summary request END{trace_label}")
    out_text = adapter.generate(
        messages,
        model=model,
        temperature=temperature,
        top_p=top_p,
        debug=(debug or trace),
        label=label,
    )
    if trace:
        log_trace(f"Summary response BEGIN{trace_label}")
        log_trace_block("Summary response", out_text)
        log_trace(f"Summary response END{trace_label}")
    return out_text


def call_llm_summary(
    adapter: LLMAdapter,
    model: str,
    full_markdown: str,
    temperature: float = 1.0,
    top_p: float = None,
    debug: bool = False,
    trace: bool = False,
    label: str = None,
    summary_type: str = "short",
    summary_lang: str = "",
    source_link_prefix: Optional[str] = None,
) -> str:
    system_content, user_content = _load_summary_prompt(
        summary_type,
        summary_lang,
        source_link_prefix,
    )
    return _call_summary_request(
        adapter,
        model,
        full_markdown,
        system_content,
        user_content,
        temperature=temperature,
        top_p=top_p,
        debug=debug,
        trace=trace,
        label=label,
    )


def _parse_combined_summaries(response: str) -> Dict[str, str]:
    markers = (
        LONG_SUMMARY_START,
        LONG_SUMMARY_END,
        SHORT_SUMMARY_START,
        SHORT_SUMMARY_END,
    )
    if any(response.count(marker) != 1 for marker in markers):
        raise RuntimeError("Combined summary response has missing or duplicate section markers")
    positions = [response.index(marker) for marker in markers]
    if positions != sorted(positions):
        raise RuntimeError("Combined summary response sections are out of order")
    before = response[:positions[0]].strip()
    between = response[positions[1] + len(LONG_SUMMARY_END):positions[2]].strip()
    after = response[positions[-1] + len(SHORT_SUMMARY_END):].strip()
    if before or between or after:
        raise RuntimeError("Combined summary response contains text outside section markers")
    long_summary = response[
        positions[0] + len(LONG_SUMMARY_START):positions[1]
    ].strip()
    short_summary = response[
        positions[2] + len(SHORT_SUMMARY_START):positions[3]
    ].strip()
    if not long_summary or not short_summary:
        raise RuntimeError("Combined summary response contains an empty section")
    return {"long": long_summary, "short": short_summary}


def call_llm_combined_summaries(
    adapter: LLMAdapter,
    model: str,
    full_markdown: str,
    long_summary_lang: str,
    temperature: float = 1.0,
    top_p: float = None,
    debug: bool = False,
    trace: bool = False,
    label: str = None,
    source_link_prefix: Optional[str] = None,
    short_summary_lang: str = "default",
) -> Dict[str, str]:
    long_system, long_user = _load_summary_prompt(
        "long",
        long_summary_lang,
        source_link_prefix,
    )
    short_system, short_user = _load_summary_prompt("short", short_summary_lang)
    system_content = f"""Complete two independent summarization tasks in one response.

Analyze the source lecture directly and independently for each task. Do not derive the short summary from the long summary, or the long summary from the short summary. Apply each task's instructions with the same care as if it were a separate request. The long-summary instructions apply only to the long section, and the short-summary instructions apply only to the short section. Each section must follow its own language and formatting requirements independently; neither section's language, heading style, or structure overrides the other section's instructions.

[LONG SUMMARY SYSTEM INSTRUCTIONS]
{long_system}

[SHORT SUMMARY SYSTEM INSTRUCTIONS]
{short_system}
"""
    user_content = f"""Complete both tasks below from the single source document supplied after these instructions.

[LONG SUMMARY USER INSTRUCTIONS]
{long_user}

[SHORT SUMMARY USER INSTRUCTIONS]
{short_user}

Return the long summary first and the short summary second. Output exactly these four marker lines and the Markdown between them. Do not use a surrounding code fence or write anything outside the markers.

{LONG_SUMMARY_START}
<long summary Markdown>
{LONG_SUMMARY_END}
{SHORT_SUMMARY_START}
<short summary Markdown>
{SHORT_SUMMARY_END}
"""
    response = _call_summary_request(
        adapter,
        model,
        full_markdown,
        system_content,
        user_content,
        temperature=temperature,
        top_p=top_p,
        debug=debug,
        trace=trace,
        label=label,
    )
    return _parse_combined_summaries(response)


def _append_summaries(
    full_markdown: str,
    summaries: Dict[str, str],
    settings: SummarySettings,
) -> str:
    sections = []
    if summaries.get("long", "").strip() and settings.long.output == "append":
        sections.append(
            _summary_block("long", summaries["long"], settings.long.heading)
        )
    if summaries.get("short", "").strip() and settings.short.output == "append":
        sections.append(
            _summary_block("short", summaries["short"], settings.short.heading)
        )
    if not sections:
        return full_markdown
    return full_markdown.rstrip() + "\n\n" + "\n\n".join(sections) + "\n"


def _summary_block(summary_type: str, summary: str, heading: str) -> str:
    if summary_type == "long":
        start, end = LONG_SUMMARY_BLOCK_START, LONG_SUMMARY_BLOCK_END
    elif summary_type == "short":
        start, end = SHORT_SUMMARY_BLOCK_START, SHORT_SUMMARY_BLOCK_END
    else:
        raise ValueError(f"Unsupported summary type: {summary_type}")
    return f"{start}\n{heading}\n\n{summary.strip()}\n{end}"


def _standalone_summary(summary_type: str, summary: str, heading: str) -> str:
    return _summary_block(summary_type, summary, heading) + "\n"


def _write_separate_summaries(
    outdir: Path,
    filename_stem: str,
    summaries: Dict[str, str],
    settings: SummarySettings,
) -> List[Path]:
    paths = []
    if summaries.get("long", "").strip() and settings.long.output == "separate":
        long_summary_path = outdir / (
            f"{filename_stem}{settings.long.file_suffix}.md"
        )
        long_summary_path.write_text(
            _standalone_summary("long", summaries["long"], settings.long.heading),
            encoding="utf-8",
        )
        paths.append(long_summary_path)
    if summaries.get("short", "").strip() and settings.short.output == "separate":
        short_summary_path = outdir / (
            f"{filename_stem}{settings.short.file_suffix}.md"
        )
        short_summary_path.write_text(
            _standalone_summary("short", summaries["short"], settings.short.heading),
            encoding="utf-8",
        )
        paths.append(short_summary_path)
    return paths


def generate_summaries(
    adapter: LLMAdapter,
    model: str,
    source: str,
    settings: SummarySettings,
    *,
    temperature: Optional[float] = 1.0,
    top_p: Optional[float] = None,
    attempts: int = 1,
    pause_seconds: float = 0.0,
    request_delay: float = 0.0,
    source_note: str = "",
    debug: bool = False,
    trace: bool = False,
) -> Dict[str, str]:
    """Generate and validate enabled summaries; propagate the final failure.

    Both consumers use the same combined request, retry rules, and reference
    validation. The pipeline may still save cleaned Markdown after a summary
    failure; the standalone tool decides when it is safe to publish changes.
    """
    kinds = settings.enabled_types()
    if not kinds:
        return {}
    prefix = source_note + "#" if settings.long.references.enabled else None
    description = "both summaries" if len(kinds) == 2 else f"{kinds[0]} summary"
    attempts = max(1, attempts)
    for attempt in range(1, attempts + 1):
        if attempt == 1 and request_delay > 0:
            if debug:
                log_debug(f"Sleeping {request_delay}s before summary request")
            time.sleep(request_delay)
        try:
            options = dict(
                temperature=temperature, top_p=top_p, debug=debug, trace=trace,
                label=f"{description} (attempt {attempt}/{attempts})",
            )
            if len(kinds) == 2:
                summaries = call_llm_combined_summaries(
                    adapter, model, source, settings.long.lang,
                    short_summary_lang=settings.short.lang,
                    source_link_prefix=prefix, **options,
                )
            else:
                kind = kinds[0]
                result = call_llm_summary(
                    adapter, model, source, summary_type=kind,
                    summary_lang=getattr(settings, kind).lang,
                    source_link_prefix=prefix if kind == "long" else None,
                    **options,
                )
                summaries = {kind: (result or "").strip()}
            for kind, body in summaries.items():
                if not body.strip():
                    raise RuntimeError(f"Empty response text ({kind} summary)")
                if "LECTURE_CLEANUP_" in body:
                    raise RuntimeError("Summary response contains reserved document markers")
            if settings.long.references.enabled and "long" in summaries:
                validate_long_summary_references(
                    summaries["long"], source, source_note=source_note,
                )
                summaries["long"] = render_long_summary_reference_display(
                    summaries["long"], source, settings.long.references.display,
                    link_style=settings.long.references.link_style,
                )
            return summaries
        except (LLMAuthError, LLMUnknownError):
            raise
        except (LLMRateLimitError, LLMConnectionError, RuntimeError) as exc:
            if attempt == attempts:
                raise
            suggested = (
                _extract_retry_after_seconds(str(exc))
                if isinstance(exc, LLMRateLimitError) else None
            )
            wait = max(0.0, (suggested or 0.0) + pause_seconds)
            log_warn(
                f"{adapter.name()} summary error (attempt {attempt}/{attempts}): "
                f"{exc}. Retrying after {wait}s…"
            )
            if wait:
                time.sleep(wait)
    raise RuntimeError("Summary generation exhausted its attempts")
