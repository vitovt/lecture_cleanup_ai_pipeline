from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from .checkpoints import CheckpointStore, fingerprint
from .config import get_path, load_config, load_env_file, set_path
from .errors import ConfigError, InputError, SttError
from .formatter import format_events, merge_plain_text, words_to_events
from .languages import normalize_languages
from .media import prepare_audio, probe_duration
from .providers import GeminiProvider
from .vocabulary import merge_vocabulary


PROJECT_DIR = Path(__file__).resolve().parent.parent
LOG = logging.getLogger("stt-api")


def _add_provider_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", choices=("gemini",), help="STT provider override.")
    parser.add_argument("--config", help="YAML override; defaults to stt-api/config.yaml.")
    parser.add_argument("--model", help="Provider model override.")
    parser.add_argument(
        "--language-code", action="append", default=[], metavar="BCP47",
        help="Language hint; repeatable. Accepts uk/de/en/ru aliases or full BCP-47.",
    )
    parser.add_argument(
        "--custom-vocabulary", action="append", default=[], metavar="TERM",
        help="One vocabulary term or phrase; repeatable.",
    )
    parser.add_argument(
        "--custom-vocabulary-file", action="append", default=[], metavar="FILE",
        help="UTF-8 file with one vocabulary entry per line; repeatable.",
    )
    parser.add_argument("--mode", choices=("verbatim", "smart"), help="Transcription mode.")
    parser.add_argument("--timestamps", choices=("on", "off"), help="Word timestamps.")
    parser.add_argument("--diarization", choices=("on", "off"), help="Speaker diarization.")
    parser.add_argument("--resume", choices=("on", "off"), help="Reuse chunk checkpoints.")
    parser.add_argument("--cache-dir", help="Checkpoint directory override.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Provider-neutral speech-to-text API client.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser(
        "validate", help="Validate provider options without reading/uploading media."
    )
    _add_provider_options(validate)

    transcribe = subparsers.add_parser(
        "transcribe", help="Inspect, optionally split, and transcribe one audio file."
    )
    _add_provider_options(transcribe)
    transcribe.add_argument("--input-file", required=True)
    transcribe.add_argument("--output-dir", default=".")
    transcribe.add_argument("--metadata-output")
    transcribe.add_argument("--events-output")
    transcribe.add_argument("--preflight", action="store_true")
    transcribe.add_argument("--preflight-output")
    transcribe.add_argument(
        "--log-level", choices=("quiet", "error", "info", "debug"), help="Console logging."
    )
    return parser


def _apply_overrides(config: dict[str, Any], args: argparse.Namespace) -> None:
    for dotted, value in (
        ("provider", args.provider),
        ("providers.gemini.model", args.model),
        ("transcription.mode.type", args.mode),
        ("processing.resume.enabled", None if args.resume is None else args.resume == "on"),
        ("processing.resume.checkpoint_directory", args.cache_dir),
    ):
        if value is not None:
            set_path(config, dotted, value)
    if args.language_code:
        set_path(config, "transcription.languages.codes", args.language_code)
    if args.timestamps is not None:
        set_path(config, "transcription.timestamps.enabled", args.timestamps == "on")
    if args.diarization is not None:
        set_path(config, "transcription.diarization.enabled", args.diarization == "on")
    if getattr(args, "log_level", None):
        set_path(config, "logging.level", args.log_level)


def _effective_settings(
    config: dict[str, Any], args: argparse.Namespace, config_base: Path
) -> dict[str, Any]:
    provider = str(get_path(config, "provider", "")).strip()
    if provider != "gemini":
        raise ConfigError(f"unsupported provider '{provider}'; currently available: gemini")
    model = str(get_path(config, "providers.gemini.model", "")).strip()
    if not model:
        raise ConfigError("providers.gemini.model cannot be empty")

    raw_languages = get_path(config, "transcription.languages.codes", [])
    if not isinstance(raw_languages, list):
        raise ConfigError("transcription.languages.codes must be a list")
    languages = normalize_languages([str(value) for value in raw_languages])

    config_terms = get_path(config, "transcription.vocabulary.terms", [])
    config_files = get_path(config, "transcription.vocabulary.files", [])
    if not isinstance(config_terms, list) or not isinstance(config_files, list):
        raise ConfigError("transcription.vocabulary terms and files must be lists")
    vocabulary = merge_vocabulary(
        config_terms,
        config_files,
        args.custom_vocabulary,
        args.custom_vocabulary_file,
        base_dir=config_base,
        limit=1000,
    )

    mode = str(get_path(config, "transcription.mode.type", "verbatim")).lower()
    timestamps = bool(get_path(config, "transcription.timestamps.enabled", True))
    diarization = bool(get_path(config, "transcription.diarization.enabled", False))
    if mode not in {"verbatim", "smart"}:
        raise ConfigError("transcription.mode.type must be verbatim or smart")
    conflicts: list[str] = []
    if vocabulary and timestamps:
        conflicts.append("custom vocabulary cannot be combined with word timestamps")
    if vocabulary and diarization:
        conflicts.append("custom vocabulary cannot be combined with speaker diarization")
    if mode == "smart" and timestamps:
        conflicts.append("smart mode cannot be combined with word timestamps")
    if mode == "smart" and diarization:
        conflicts.append("smart mode cannot be combined with speaker diarization")
    if conflicts:
        raise InputError("; ".join(conflicts))

    max_seconds = float(
        get_path(
            config,
            "media.chunking.timed_chunk_seconds" if (timestamps or diarization)
            else "media.chunking.untimed_chunk_seconds",
            1500 if (timestamps or diarization) else 3300,
        )
    )
    overlap = float(get_path(config, "media.chunking.overlap_seconds", 5))
    if max_seconds <= 0:
        raise ConfigError("media chunk duration must be positive")
    return {
        "provider": provider,
        "model": model,
        "language_codes": languages,
        "vocabulary": vocabulary,
        "mode": mode,
        "timestamps": timestamps,
        "diarization": diarization,
        "max_seconds": max_seconds,
        "overlap": overlap,
    }


def _provider(config: dict[str, Any], settings: dict[str, Any]) -> GeminiProvider:
    env_name = str(get_path(config, "providers.gemini.api_key_env", "GEMINI_API_KEY"))
    api_key = os.environ.get(env_name, "").strip()
    if not api_key:
        raise ConfigError(
            f"{env_name} is not set; add it to stt-api/.env or the process environment"
        )
    attempts = int(get_path(config, "processing.retry.attempts", 4))
    if attempts < 1:
        raise ConfigError("processing.retry.attempts must be at least 1")
    return GeminiProvider(
        api_key,
        attempts=attempts,
        initial_delay=float(get_path(config, "processing.retry.initial_delay_seconds", 2)),
        multiplier=float(get_path(config, "processing.retry.backoff_multiplier", 2)),
        max_delay=float(get_path(config, "processing.retry.max_delay_seconds", 30)),
        jitter=float(get_path(config, "processing.retry.jitter_seconds", 0.25)),
        request_timeout=float(get_path(config, "providers.gemini.request.timeout_seconds", 180)),
    )


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _preflight(input_path: Path, settings: dict[str, Any]) -> dict[str, Any]:
    duration = probe_duration(input_path)
    step = settings["max_seconds"] - settings["overlap"]
    if duration <= settings["max_seconds"]:
        chunks = 1
    else:
        chunks = 1 + int((duration - settings["max_seconds"] + step - 0.000001) // step)
    return {
        "input_file": str(input_path),
        "duration_seconds": round(duration, 3),
        "provider": settings["provider"],
        "model": settings["model"],
        "language_codes": settings["language_codes"],
        "timestamps": settings["timestamps"],
        "diarization": settings["diarization"],
        "vocabulary_entries": len(settings["vocabulary"]),
        "planned_chunks": chunks,
    }


def transcribe(config: dict[str, Any], args: argparse.Namespace, settings: dict[str, Any]) -> int:
    input_path = Path(args.input_file).expanduser().resolve()
    if not input_path.is_file():
        raise InputError(f"input file not found: {input_path}")
    if args.preflight_output and not args.preflight:
        raise InputError("--preflight-output requires --preflight")
    if args.preflight:
        payload = _preflight(input_path, settings)
        if args.preflight_output:
            _write_json(Path(args.preflight_output), payload)
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    base = input_path.stem
    transcript_path = output_dir / f"{base}.txt"
    events_path = Path(args.events_output).expanduser().resolve() if args.events_output else output_dir / f"{base}.events.json"
    raw_path = output_dir / f"{base}.raw.json"
    cache_value = get_path(config, "processing.resume.checkpoint_directory")
    cache_dir = Path(cache_value).expanduser().resolve() if cache_value else output_dir / ".stt-cache"
    resume = bool(get_path(config, "processing.resume.enabled", True))
    store = CheckpointStore(cache_dir, resume)
    provider = _provider(config, settings)
    prepared = prepare_audio(
        input_path, max_seconds=settings["max_seconds"], overlap_seconds=settings["overlap"]
    )
    all_events: list[dict[str, Any]] = []
    plain_parts: list[str] = []
    raw_parts: list[dict[str, Any]] = []
    try:
        for index, part in enumerate(prepared.parts):
            checkpoint_settings = {**settings, "offset": part.offset, "duration": part.duration}
            key = fingerprint(part.path, checkpoint_settings)
            result = store.read(key)
            if result is None:
                LOG.info("Transcribing part %d/%d", index + 1, len(prepared.parts))
                result = provider.transcribe(
                    part.path,
                    model=settings["model"],
                    language_codes=settings["language_codes"],
                    vocabulary=settings["vocabulary"],
                    mode=settings["mode"],
                    timestamps=settings["timestamps"],
                    diarization=settings["diarization"],
                )
                store.write(key, result)
            else:
                LOG.info("Reusing checkpoint for part %d/%d", index + 1, len(prepared.parts))
            raw_parts.append(result)
            words = result.get("words") or []
            if words:
                adjusted: list[dict[str, Any]] = []
                for word in words:
                    item = dict(word)
                    item["start"] = float(item["start"]) + part.offset
                    item["end"] = float(item["end"]) + part.offset
                    midpoint = (item["start"] + item["end"]) / 2
                    if part.owned_start <= midpoint <= part.owned_end:
                        adjusted.append(item)
                all_events.extend(words_to_events(adjusted))
            else:
                plain_parts.append(str(result.get("text") or ""))
    finally:
        prepared.cleanup()

    transcript = format_events(all_events) if all_events else merge_plain_text(plain_parts)
    transcript_path.write_text(transcript, encoding="utf-8")
    if bool(get_path(config, "output.write_events", True)):
        _write_json(events_path, all_events)
    if bool(get_path(config, "output.save_raw_response", True)):
        _write_json(raw_path, {"provider": "gemini", "parts": raw_parts})

    metadata = {
        "provider": "gemini",
        "model": settings["model"],
        "language_codes": settings["language_codes"],
        "detected_language": "",
        "transcript_file": str(transcript_path),
        "events_file": str(events_path) if events_path.is_file() else "",
        "raw_response_file": str(raw_path) if raw_path.is_file() else "",
        "duration_seconds": prepared.duration,
        "chunk_count": len(prepared.parts),
        "timestamps": settings["timestamps"],
        "diarization": settings["diarization"],
        "vocabulary_entries": len(settings["vocabulary"]),
    }
    if args.metadata_output:
        _write_json(Path(args.metadata_output).expanduser().resolve(), metadata)
    print(json.dumps(metadata, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        load_env_file(PROJECT_DIR / ".env")
        override = Path(args.config).expanduser().resolve() if args.config else None
        config = load_config(PROJECT_DIR, override)
        _apply_overrides(config, args)
        config_base = override.parent if override else PROJECT_DIR
        settings = _effective_settings(config, args, config_base)
        if args.command == "validate":
            print(
                "VALID status=ok provider={provider} model={model} languages={langs} "
                "timestamps={timestamps} diarization={diarization} vocabulary={vocabulary}".format(
                    provider=settings["provider"],
                    model=settings["model"],
                    langs=",".join(settings["language_codes"]) or "auto",
                    timestamps="on" if settings["timestamps"] else "off",
                    diarization="on" if settings["diarization"] else "off",
                    vocabulary=len(settings["vocabulary"]),
                )
            )
            return 0
        level = str(get_path(config, "logging.level", "info")).upper()
        logging.basicConfig(
            level=getattr(logging, level, logging.INFO), format="[%(levelname)s] %(message)s"
        )
        return transcribe(config, args, settings)
    except SttError as exc:
        print(f"ERROR code={exc.__class__.__name__} message={json.dumps(str(exc))}", file=sys.stderr)
        return exc.exit_code
    except (OSError, ValueError) as exc:
        print(f"ERROR code=runtime_error message={json.dumps(str(exc))}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
