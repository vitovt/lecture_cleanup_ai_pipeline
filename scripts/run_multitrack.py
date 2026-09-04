#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from multitrack.manifest import (  # noqa: E402
    LANGUAGE_RE,
    ManifestError,
    load_manifest,
    manifest_from_files,
    write_manifest,
)
from multitrack.merging import documents_from_manifest, merge_to_outputs  # noqa: E402
from multitrack.providers import create_provider  # noqa: E402
from multitrack.transcription import transcribe_manifest  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Transcribe, merge, and clean a simultaneous multitrack session."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest", type=Path)
    source.add_argument("--no-manifest", action="store_true")
    parser.add_argument("--file", type=Path, action="append", default=[])
    parser.add_argument("--lang")
    parser.add_argument("--provider", default="groq")
    parser.add_argument("--provider-config", type=Path)
    parser.add_argument("--workdir", type=Path, default=Path("multitrack-work"))
    parser.add_argument("--name")
    parser.add_argument("--cleanup-outdir", type=Path, default=Path("output/multitrack"))
    parser.add_argument("--cleanup-lang")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--log-level",
        choices=("quiet", "error", "info", "debug", "trace"),
        default="info",
    )
    parser.add_argument("--cleanup-args", nargs=argparse.REMAINDER, default=[])
    return parser


def _cleanup_language(manifest, documents, override: str | None) -> str:
    if override:
        language = override.strip().lower()
        if not LANGUAGE_RE.fullmatch(language):
            raise ManifestError("--cleanup-lang must be a two-letter language code")
        return language
    if manifest.language and manifest.language != "auto":
        return manifest.language
    detected = {doc.detected_language for doc in documents if doc.detected_language}
    if len(detected) == 1:
        language = detected.pop().strip().lower()
        if LANGUAGE_RE.fullmatch(language):
            return language
    raise ManifestError(
        "cannot infer one cleanup language from the tracks; pass --cleanup-lang CODE"
    )


def _output_name(value: str) -> str:
    if value in {"", ".", ".."} or Path(value).name != value:
        raise ManifestError("--name must be a filename, not a path")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.no_manifest:
            if not args.file or not args.lang:
                parser.error(
                    "--no-manifest requires --lang CODE|auto and repeatable --file FILE"
                )
            manifest = manifest_from_files(
                args.file, args.lang, args.provider, Path.cwd()
            )
            default_name = "multitrack-session"
        else:
            if args.file or args.lang:
                parser.error("--file and --lang are only valid with --no-manifest")
            manifest = load_manifest(args.manifest)
            default_name = args.manifest.stem

        workdir = args.workdir.expanduser().resolve()
        providers = {}

        def provider_factory(name: str):
            if name not in providers:
                providers[name] = create_provider(
                    name,
                    PROJECT_ROOT,
                    config_path=args.provider_config,
                    log_level=args.log_level,
                )
            return providers[name]

        resolved = transcribe_manifest(
            manifest,
            workdir,
            provider_factory,
            overwrite=args.overwrite,
        )
        resolved_path = write_manifest(resolved, workdir / "resolved-manifest.yaml")
        documents = documents_from_manifest(resolved)
        name = _output_name(args.name or default_name)
        output_base = workdir / "combined" / name
        outputs = merge_to_outputs(
            documents,
            output_base,
            ["events", "txt", "srt"],
        )
        events_path = outputs["events"]
        txt_path = outputs["txt"]
        srt_path = outputs["srt"]
        cleanup_language = _cleanup_language(resolved, documents, args.cleanup_lang)
        command = [
            str(PROJECT_ROOT / "lecture_cleanup.sh"),
            "--input",
            str(txt_path),
            "--lang",
            cleanup_language,
            "--outdir",
            str(args.cleanup_outdir.expanduser().resolve()),
            *args.cleanup_args,
        ]
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            return result.returncode
    except (ManifestError, OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Resolved manifest: {resolved_path}")
    print(f"Combined events: {events_path}")
    print(f"Combined TXT: {txt_path}")
    print(f"Combined SRT: {srt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
