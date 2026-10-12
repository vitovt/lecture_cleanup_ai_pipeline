#!/usr/bin/env python3
"""Select native subtitles using original audio metadata, never table order."""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def normalized(code):
    return code.removesuffix("-orig").replace("_", "-").lower()


def native_entries(entries, automatic):
    return [e for e in entries if "tlang" not in parse_qs(urlsplit(e.get("url", "")).query)
            and (not automatic or parse_qs(urlsplit(e.get("url", "")).query).get("kind") == ["asr"])]


def select(info, language=None, source="auto"):
    tracks = []
    for kind, field in (("manual", "subtitles"), ("auto", "automatic_captions")):
        for code, entries in (info.get(field) or {}).items():
            entries = native_entries(entries, kind == "auto")
            if entries:
                tracks.append((code, kind, entries))
    available = ", ".join(f"{code} ({kind})" for code, kind, _ in tracks) or "none"

    def fail(reason):
        raise ValueError(f"{reason}\nAvailable native subtitles: {available}\n"
                         "Specify --lang CODE and --subtitle-source auto|manual|prefer-manual.")

    if not language or language == "auto":
        originals = {normalized(f["language"]) for f in info.get("formats", [])
                     if f.get("language") and f.get("language_preference") == 10
                     and f.get("acodec", "none") != "none"}
        if len(originals) == 1:
            language = originals.pop()
        elif not originals:
            native = {normalized(code) for code, kind, _ in tracks if kind == "auto"}
            if len(native) != 1:
                fail("Cannot reliably determine the original audio language.")
            language = native.pop()
        else:
            fail("Multiple original audio languages are reported.")
    wanted = normalized(language)
    variants = {normalized(code) for code, _, _ in tracks}
    if wanted in variants:
        variant = wanted
    else:
        base = wanted.split("-")[0]
        script = next((p for p in wanted.split("-")[1:] if len(p) == 4), None)
        compatible = {v for v in variants if v.split("-")[0] == base
                      and (not script or not any(len(p) == 4 for p in v.split("-")[1:])
                           or script in v.split("-")[1:])}
        if base in compatible:
            variant = base
        elif len(compatible) == 1:
            variant = compatible.pop()
        else:
            fail(f"Subtitle language {language!r} is unavailable or ambiguous.")
    matches = [t for t in tracks if normalized(t[0]) == variant]
    kinds = ("manual", "auto") if source == "prefer-manual" else (source,)
    for kind in kinds:
        candidates = [t for t in matches if t[1] == kind]
        if language.endswith("-orig"):
            candidates = [t for t in candidates if t[0] == language]
        # The plain auto key can repeat the same native ASR as its -orig key.
        originals = [t for t in candidates if t[0].endswith("-orig")]
        if originals:
            candidates = originals
        if not candidates:
            continue
        if len(candidates) != 1:
            fail(f"Multiple {kind} subtitle tracks match {language!r}.")
        code, kind, entries = candidates[0]
        identities = {(e.get("name", ""), tuple(parse_qs(urlsplit(e["url"]).query).get("lang", [])),
                       tuple(parse_qs(urlsplit(e["url"]).query).get("vssId", []))) for e in entries}
        if len(identities) > 1:
            fail(f"Multiple named subtitle tracks match {code!r}: "
                 + ", ".join(sorted({e.get("name", "unnamed") for e in entries})))
        return code, kind, entries
    fail(f"No {source} subtitles are available for {language!r}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--lang")
    parser.add_argument("--subtitle-source", choices=("auto", "manual", "prefer-manual"))
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    try:
        from config_loader import load_effective_config
        config, _ = load_effective_config(ROOT)
        settings = config.get("autoyoutube") or {}
        if not isinstance(settings, dict):
            raise ValueError("autoyoutube configuration must be a mapping.")
        source = args.subtitle_source or settings.get("subtitle_source", "auto")
        language = args.lang if args.lang is not None else settings.get("lang")
        if source not in ("auto", "manual", "prefer-manual"):
            raise ValueError("Invalid autoyoutube.subtitle_source; use auto, manual or prefer-manual.")
        if language is not None and (not isinstance(language, str) or not language):
            raise ValueError("autoyoutube.lang must be a language code, auto or null.")
        command = ["yt-dlp", "--no-playlist", "--no-download-archive", "--simulate",
                   "--dump-single-json", "--write-auto-subs", "--write-subs", args.url]
        if args.debug:
            command.insert(1, "--verbose")
        else:
            command[1:1] = ["--quiet", "--no-warnings"]
        result = subprocess.run(command, stdout=subprocess.PIPE, text=True, check=True)
        info = json.loads(result.stdout)
        code, kind, entries = select(info, language, source)
        # Freeze the filtered entries so downloading cannot pick a translation.
        info["subtitles"] = {code: entries} if kind == "manual" else {}
        info["automatic_captions"] = {code: entries} if kind == "auto" else {}
        info.pop("requested_subtitles", None)
        # yt-dlp otherwise retries failed info-file downloads by re-extracting
        # the URL, which would discard our translation filtering.
        info.pop("webpage_url", None)
        Path(args.metadata).write_text(json.dumps(info), encoding="utf-8")
        date = info.get("upload_date") or ""
        if re.fullmatch(r"\d{8}", date):
            date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
        for key, value in (("AUTO_LANG", code), ("LANG", code.removesuffix("-orig")),
                           ("SELECTED_SUBTITLE_SOURCE", kind), ("YOUTUBE_UPLOAD_DATE", date)):
            print(f"{key}={shlex.quote(value)}")
    except (ValueError, OSError, subprocess.CalledProcessError, ImportError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
