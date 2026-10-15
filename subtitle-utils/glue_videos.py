#!/usr/bin/env python3
"""Join compatible videos, in argument order, without re-encoding."""

import argparse
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile


class GlueError(Exception):
    """An actionable error to display without a Python traceback."""


# Ignore content-dependent values such as duration, bitrate and packet counts.
# Codec initialization bytes must match too, not just the codec's name.
COMMON_FIELDS = (
    "codec_type", "codec_name", "profile", "codec_tag", "time_base",
    "bits_per_raw_sample", "extradata_size", "extradata_hash",
)
VIDEO_FIELDS = (
    "width", "height", "coded_width", "coded_height", "pix_fmt", "level",
    "sample_aspect_ratio", "display_aspect_ratio", "r_frame_rate",
    "avg_frame_rate", "field_order", "color_range", "color_space",
    "color_transfer", "color_primaries", "chroma_location", "has_b_frames",
    "is_avc", "nal_length_size", "closed_captions", "film_grain", "refs",
)
AUDIO_FIELDS = (
    "sample_fmt", "sample_rate", "channels", "channel_layout",
    "bits_per_sample", "initial_padding", "trailing_padding",
)
MUXER_ALIASES = {
    "mkv": "matroska", "mka": "matroska", "webm": "webm",
    "mp4": "mp4", "m4v": "mp4", "mov": "mov", "3gp": "3gp",
    "3g2": "3g2", "ts": "mpegts", "mts": "mpegts",
    "m2ts": "mpegts", "mpg": "mpeg", "mpeg": "mpeg", "vob": "vob",
    "ogv": "ogg", "ogg": "ogg", "wmv": "asf", "asf": "asf",
}


def run_capture(command, description):
    result = subprocess.run(command, capture_output=True, text=True,
                            errors="replace", stdin=subprocess.DEVNULL)
    if result.returncode or result.stderr.strip():
        details = result.stderr.strip() or result.stdout.strip() or "No details provided."
        raise GlueError(f"{description}\n{details}")
    return result.stdout


def probe(path, ffprobe):
    raw = run_capture(
        [ffprobe, "-v", "error", "-show_format", "-show_streams",
         "-show_data_hash", "sha256", "-of", "json", str(path)],
        f"Cannot inspect video {str(path)!r}; it may be damaged or unsupported.",
    )
    try:
        info = json.loads(raw)
        streams = info["streams"]
        duration = float(info["format"]["duration"])
    except (ValueError, KeyError, TypeError) as exc:
        raise GlueError(f"Incomplete ffprobe information for {str(path)!r}: {exc}") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise GlueError(f"{str(path)!r} has no valid positive duration.")
    if not any(s.get("codec_type") == "video" for s in streams):
        raise GlueError(f"{str(path)!r} contains no video stream.")
    for index, stream in enumerate(streams):
        kind = stream.get("codec_type", "unknown")
        if kind not in {"video", "audio", "subtitle"}:
            raise GlueError(
                f"{str(path)!r}, stream {index}: {kind} streams are not supported.\n"
                "This script joins video, audio and subtitle streams; it cannot safely "
                "concatenate attachments or data streams. No streams will be silently dropped."
            )
        if not stream.get("codec_name") or stream["codec_name"] == "unknown":
            raise GlueError(f"{str(path)!r}, stream {index}: codec could not be identified.")
        if stream.get("disposition", {}).get("attached_pic"):
            raise GlueError(f"{str(path)!r}, stream {index}: cover-art video cannot be concatenated.")
    return info


def container_key(path, info):
    """Disambiguate demuxers shared by multiple container formats."""
    names = info["format"]["format_name"]
    if names == "matroska,webm":
        # EBML DocType is in the header, before any video packets.
        with path.open("rb") as source:
            header = source.read(4096)
        match = re.search(rb"\x42\x82[\x84\x88](webm|matroska)", header)
        if not match:
            raise GlueError(f"Cannot identify the Matroska/WebM DocType in {str(path)!r}.")
        return match.group(1).decode("ascii")
    if "mov" in names.split(","):
        brand = info["format"].get("tags", {}).get("major_brand")
        # MOV/MP4/3GP share a demuxer; also compare their actual major brands.
        return names, brand
    return names


def compatibility_errors(reference_path, reference, path, info):
    errors = []
    if path.suffix.lower() != reference_path.suffix.lower():
        errors.append(f"container extension: expected {reference_path.suffix!r}, got {path.suffix!r}")
    if container_key(path, info) != container_key(reference_path, reference):
        errors.append(
            f"container format: expected {container_key(reference_path, reference)!r}, "
            f"got {container_key(path, info)!r}"
        )
    expected, actual = reference["streams"], info["streams"]
    for kind in ("video", "audio", "subtitle"):
        left = sum(s.get("codec_type") == kind for s in expected)
        right = sum(s.get("codec_type") == kind for s in actual)
        if left != right:
            errors.append(f"{kind} track count: expected {left}, got {right}")
    if len(expected) != len(actual):
        errors.append(f"total stream count: expected {len(expected)}, got {len(actual)}")
    for index, (left, right) in enumerate(zip(expected, actual)):
        fields = COMMON_FIELDS
        if left.get("codec_type") == "video":
            fields += VIDEO_FIELDS
        elif left.get("codec_type") == "audio":
            fields += AUDIO_FIELDS
        for field in fields + ("disposition", "side_data_list"):
            if left.get(field) != right.get(field):
                errors.append(
                    f"stream {index} ({left.get('codec_type')}), {field}: "
                    f"expected {left.get(field, '<missing>')!r}, "
                    f"got {right.get(field, '<missing>')!r}"
                )
        for tag in ("title", "language"):
            a, b = left.get("tags", {}).get(tag), right.get("tags", {}).get(tag)
            if a != b:
                errors.append(f"stream {index}, {tag}: expected {a!r}, got {b!r}")
    return errors


def choose_muxer(path, info, ffmpeg):
    extension = path.suffix.lower().lstrip(".")
    muxer = MUXER_ALIASES.get(extension, extension)
    if not re.fullmatch(r"[a-z0-9_]+", muxer):
        raise GlueError(f"Input {str(path)!r} needs a recognized video container extension.")
    result = subprocess.run([ffmpeg, "-hide_banner", "-h", f"muxer={muxer}"],
                            capture_output=True, text=True, errors="replace")
    if result.returncode or not result.stdout.startswith(f"Muxer {muxer} "):
        raise GlueError(f"No installed FFmpeg output muxer for extension {path.suffix!r}.")
    formats = set(info["format"]["format_name"].split(","))
    expected_demuxer = {"mp4": "mov", "3gp": "mov", "3g2": "mov", "vob": "mpeg"}.get(muxer, muxer)
    if expected_demuxer not in formats:
        raise GlueError(
            f"{str(path)!r} has extension {path.suffix!r}, but ffprobe detects "
            f"{info['format']['format_name']!r}. Correct the extension before joining."
        )
    if "mov" in formats:
        brand = info["format"].get("tags", {}).get("major_brand", "qt  ")
        if brand.startswith("qt"):
            actual_muxer = "mov"
        elif brand.startswith("3gp"):
            actual_muxer = "3gp"
        elif brand.startswith("3g2"):
            actual_muxer = "3g2"
        elif brand == "mjp2":
            actual_muxer = "mj2"
        else:
            actual_muxer = "mp4"
        if actual_muxer != muxer:
            raise GlueError(
                f"{str(path)!r} has extension {path.suffix!r}, but its major brand "
                f"{brand!r} identifies a {actual_muxer} container. Correct the extension before joining."
            )
    if "matroska" in formats and container_key(path, info) != muxer:
        raise GlueError(f"{str(path)!r}: its extension does not match its actual Matroska/WebM container.")
    return muxer


def fingerprint(path):
    details = path.stat()
    return details.st_dev, details.st_ino, details.st_size, details.st_mtime_ns


def output_state(path):
    if not os.path.lexists(path):
        return None
    if path.is_symlink():
        raise GlueError(f"Output {str(path)!r} is a symbolic link; choose a regular output path.")
    if not path.is_file():
        raise GlueError(f"Output {str(path)!r} exists and is not a regular file.")
    return fingerprint(path)


def check_output_is_not_input(output, inputs):
    for source in inputs:
        if output == source or (output.exists() and os.path.samefile(output, source)):
            raise GlueError(f"Output {str(output)!r} refers to input {str(source)!r}. Sources cannot be overwritten.")


def confirm_overwrite(output, overwrite):
    if overwrite:
        return
    try:
        answer = input(f"Output {str(output)!r} already exists. Overwrite? [y/n] ").strip().lower()
        while answer not in {"y", "yes", "n", "no"}:
            answer = input("Please answer y or n: ").strip().lower()
    except EOFError as exc:
        raise GlueError("Cannot read overwrite confirmation. Use --overwrite to allow replacement.") from exc
    if answer in {"n", "no"}:
        raise GlueError("Cancelled. Existing output was left intact.")


def segment_durations(inputs, infos, ffprobe):
    """Account for encoder delay that container durations can exclude (AAC/MP4).

    Inspect the beginning and end without decoding or scanning whole recordings.
    Concat shifts packets by segment_duration - container_start_time. Ensure the
    next packet in each track cannot overlap the previous track's final packet.
    """
    timings = []
    durations = [float(info["format"]["duration"]) for info in infos]
    for path, info, duration in zip(inputs, infos, durations):
        raw = run_capture(
            [ffprobe, "-v", "error", "-read_intervals", f"%+1,{max(0, duration - 2):.6f}%",
             "-show_packets", "-show_entries", "packet=stream_index,dts_time,pts_time,duration_time",
             "-of", "json", str(path)],
            f"Cannot inspect packet timing at the beginning/end of {str(path)!r}.",
        )
        try:
            packets = json.loads(raw).get("packets", [])
            start = float(info["format"].get("start_time", 0))
            first, last = {}, {}
            for packet in packets:
                timestamp = packet.get("dts_time", packet.get("pts_time"))
                if timestamp is None:
                    continue
                timestamp = float(timestamp) - start
                end = timestamp + float(packet.get("duration_time", 0))
                if not math.isfinite(timestamp) or not math.isfinite(end):
                    raise ValueError("non-finite packet timestamp")
                index = packet["stream_index"]
                first[index] = min(first.get(index, timestamp), timestamp)
                last[index] = max(last.get(index, end), end)
        except (ValueError, KeyError, TypeError) as exc:
            raise GlueError(f"Invalid packet timing in {str(path)!r}: {exc}") from exc
        for index, stream in enumerate(info["streams"]):
            if stream["codec_type"] in {"video", "audio"} and index not in first:
                raise GlueError(f"{str(path)!r}, stream {index}: no timestamped packets near its beginning/end.")
        timings.append((first, last))
    for index in range(len(inputs) - 1):
        next_first, previous_last = timings[index + 1][0], timings[index][1]
        minimum = max((end - next_first[track] for track, end in previous_last.items()
                       if track in next_first), default=durations[index])
        if minimum > durations[index]:
            # FFconcat durations use microseconds; round up to prevent overlap.
            durations[index] = math.ceil(minimum * 1_000_000 + 1) / 1_000_000
    return durations


def check_space(inputs, output):
    required = sum(path.stat().st_size for path in inputs)
    required += max(required // 20, 16 * 1024 * 1024)
    free = shutil.disk_usage(output.parent).free
    if free < required:
        raise GlueError(
            f"Insufficient free space in {str(output.parent)!r}: "
            f"{free / 1024**3:.2f} GiB available, approximately {required / 1024**3:.2f} GiB needed.\n"
            "The old output is retained until the new file is complete."
        )
    return required, free


def describe_input(index, path, info):
    print(f"\nInput {index}: {str(path)!r}")
    print(f"  Container: {info['format']['format_name']}; extension: {path.suffix}")
    print(f"  Size: {path.stat().st_size:,} bytes")
    print(f"  Duration: {float(info['format']['duration']):.6f} seconds; "
          f"start time: {info['format'].get('start_time', 'unknown')}")
    brand = info['format'].get('tags', {}).get('major_brand')
    if brand:
        print(f"  Major brand: {brand!r}")
    for index, stream in enumerate(info['streams']):
        print(f"  Stream {index}: {stream['codec_type']}")
        fields = COMMON_FIELDS
        if stream['codec_type'] == 'video':
            fields += VIDEO_FIELDS
        elif stream['codec_type'] == 'audio':
            fields += AUDIO_FIELDS
        for field in fields + ('duration', 'bit_rate', 'disposition', 'side_data_list'):
            if field in stream:
                print(f"    {field}: {json.dumps(stream[field], ensure_ascii=False)}")
        for key, value in stream.get('tags', {}).items():
            if key.upper().startswith(('DURATION', 'NUMBER_OF_', '_STATISTICS')):
                continue
            print(f"    tag {key}: {json.dumps(value, ensure_ascii=False)}")


def describe_plan(inputs, output, infos, muxer, ffprobe, snapshots, initial_output):
    durations = segment_durations(inputs, infos, ffprobe)
    for path, snapshot in zip(inputs, snapshots):
        if fingerprint(path) != snapshot:
            raise GlueError(f"Input {str(path)!r} changed during inspection; run again.")
    total = sum(durations)
    hours, remainder = divmod(round(total * 1000), 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds = remainder / 1000
    print("\nJoin plan:")
    print(f"  Inputs: {len(inputs)}, in the order listed above")
    print(f"  Output: {str(output)!r}" if output is not None else "  Output: not specified")
    print(f"  Container/muxer: {muxer}")
    print("  Method: stream copy; no re-encoding; audio tracks remain separate")
    print(f"  Streams: {len(infos[0]['streams'])}; "
          f"audio tracks: {sum(s['codec_type'] == 'audio' for s in infos[0]['streams'])}")
    print(f"  Input durations total: {sum(float(i['format']['duration']) for i in infos):.6f} seconds")
    print(f"  Estimated output duration: {total:.6f} seconds ({hours:02d}:{minutes:02d}:{seconds:06.3f})")
    for index, duration in enumerate(durations, 1):
        print(f"  Segment {index} concat duration: {duration:.6f} seconds")
    if output is not None:
        if not os.access(output.parent, os.W_OK):
            raise GlueError(f"Output directory {str(output.parent)!r} is not writable.")
        required, free = check_space(inputs, output)
        print(f"  Space: approximately {required:,} bytes required; {free:,} bytes available")
        print("  Existing output: would require replacement; not modified and no prompt in dry-run"
              if initial_output is not None else "  Existing output: absent; a new file would be created")
        if output_state(output) != initial_output:
            raise GlueError("Output changed during inspection; run again.")
    print("Dry-run: no files were created or changed.")


def glue(inputs, output, infos, muxer, ffmpeg, ffprobe, initial_output, snapshots):
    check_space(inputs, output)
    durations = segment_durations(inputs, infos, ffprobe)
    with tempfile.TemporaryDirectory(prefix=".glue-videos-", dir=output.parent) as work:
        directory = Path(work)
        manifest = directory / "inputs.ffconcat"
        # Simple symlink names avoid FFconcat quoting pitfalls, including newlines
        # and apostrophes in source paths. Only local files are permitted.
        with manifest.open("w", encoding="utf-8") as listing:
            listing.write("ffconcat version 1.0\n")
            for index, source in enumerate(inputs):
                name = f"input-{index:08d}{source.suffix.lower()}"
                (directory / name).symlink_to(source)
                listing.write(f"file '{name}'\n")
                listing.write(f"duration {durations[index]:.6f}\n")
        temporary_output = directory / ("joined" + output.suffix.lower())
        command = [
            ffmpeg, "-hide_banner", "-nostdin", "-v", "warning", "-stats",
            "-xerror", "-err_detect", "explode", "-f", "concat", "-safe", "1",
            "-auto_convert", "0", "-protocol_whitelist", "file", "-i", str(manifest),
            "-map", "0", "-c", "copy", "-map_metadata", "0", "-map_chapters", "-1",
        ]
        for index, stream in enumerate(infos[0]["streams"]):
            flags = "+".join(k for k, v in stream.get("disposition", {}).items() if v)
            command += [f"-disposition:{index}", flags or "0"]
            for key, value in stream.get("tags", {}).items():
                if key.upper().startswith(("DURATION", "NUMBER_OF_", "_STATISTICS")):
                    continue
                command += [f"-metadata:s:{index}", f"{key}={value}"]
        if muxer in {"mov", "mp4", "3gp", "3g2"}:
            brand = infos[0]["format"].get("tags", {}).get("major_brand")
            if brand:
                command += ["-brand", brand]
        command += ["-f", muxer, "-n", str(temporary_output)]
        # Keep a bounded log in memory; FFmpeg's detailed diagnostics go to disk.
        with (directory / "ffmpeg.log").open("w+") as log:
            process = subprocess.Popen(command, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                       stdin=subprocess.DEVNULL, text=True, errors="replace")
            try:
                for line in process.stderr:
                    log.write(line)
                    print(line.rstrip(), file=sys.stderr, flush=True)
                returncode = process.wait()
            except BaseException:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise
            finally:
                process.stderr.close()
            log.flush()
            if returncode:
                log.seek(max(0, log.tell() - 12000))
                raise GlueError(
                    f"FFmpeg could not join the videos (exit {returncode}).\n{log.read()}\n"
                    "The incomplete temporary output was removed; sources and existing output were left intact."
                )
        if not temporary_output.is_file() or not temporary_output.stat().st_size:
            raise GlueError("FFmpeg produced no usable output.")
        joined = probe(temporary_output, ffprobe)
        before = infos[0]["streams"]
        after = joined["streams"]
        if len(before) != len(after) or any(
            a.get("codec_type") != b.get("codec_type") or a.get("codec_name") != b.get("codec_name")
            for a, b in zip(before, after)
        ):
            raise GlueError("Output verification failed: stream count, order or codecs changed.")
        expected_duration = sum(durations)
        if abs(float(joined["format"]["duration"]) - expected_duration) > max(1.0, len(inputs) * 0.1):
            raise GlueError("Output verification failed: duration does not match the sum of the input durations.")
        for path, snapshot in zip(inputs, snapshots):
            if fingerprint(path) != snapshot:
                raise GlueError(f"Input {str(path)!r} changed during joining; output will not be published.")
        check_output_is_not_input(output, inputs)
        if output_state(output) != initial_output:
            raise GlueError("Output changed while joining. It was left intact; run again to review replacement.")
        if initial_output is None:
            # Atomic no-clobber publication, even if another process creates output.
            try:
                os.link(temporary_output, output)
            except FileExistsError as exc:
                raise GlueError("Output appeared while joining; it was not overwritten.") from exc
        else:
            os.replace(temporary_output, output)


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments:
        print('Join compatible videos in the supplied order without re-encoding, keeping audio tracks separate.')
        print('Omit --output or use --dry-run to inspect videos and preview the join without writing files.')
        print('\nExample: python3 subtitle-utils/glue_videos.py part1.mkv part2.mkv -o joined.mkv')
        print('\nRun python3 subtitle-utils/glue_videos.py --help for more information.')
        return 0
    parser = argparse.ArgumentParser(
        description=__doc__, fromfile_prefix_chars="@",
        allow_abbrev=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Inputs are joined in the exact order supplied (never sorted).\n"
               "Containers and stream properties must match; audio tracks stay separate.\n"
               "Use @arguments.txt for very long lists, with one argument per line.\n"
               "Requires Python 3, ffmpeg and ffprobe. Existing chapters are omitted.\n"
               "Existing output requires confirmation unless --overwrite is supplied.\n"
               "Sources cannot be overwritten; the output directory must already exist.\n\n"
               "Omitting --output implies --dry-run: inspect inputs and show the join plan.\n\n"
               "Examples:\n"
               "  python3 subtitle-utils/glue_videos.py part1.mkv part2.mkv -o joined.mkv\n"
               "  python3 subtitle-utils/glue_videos.py part1.mp4 part2.mp4 -o joined.mp4 --overwrite\n"
               "  python3 subtitle-utils/glue_videos.py @arguments.txt\n"
               "  python3 subtitle-utils/glue_videos.py part1.mkv part2.mkv -o joined.mkv --dry-run\n"
               "  python3 subtitle-utils/glue_videos.py part1.mkv part2.mkv",
    )
    parser.add_argument("videos", nargs="+", help="Input videos, in playback order")
    parser.add_argument("-o", "--output", help="Output file; same extension/container as inputs; omission implies --dry-run")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs and print their properties and join plan without writing files")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing output without prompting")
    # Intermixed parsing accepts options between inputs; ordinary parsing keeps
    # the explicit '--' separator useful for filenames beginning with '-'.
    args = parser.parse_args(arguments) if "--" in arguments else parser.parse_intermixed_args(arguments)
    dry_run = args.dry_run or args.output is None
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise GlueError("Both ffmpeg and ffprobe must be installed and available on PATH.")
    inputs = []
    for filename in args.videos:
        try:
            path = Path(filename).expanduser().resolve(strict=True)
        except RuntimeError as exc:
            raise GlueError(f"Cannot resolve input {filename!r}: {exc}") from exc
        if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
            raise GlueError(f"Input {filename!r} is not a regular file.")
        if not path.stat().st_size:
            raise GlueError(f"Input {filename!r} is empty.")
        with path.open("rb"):
            pass
        inputs.append(path)
    snapshots = [fingerprint(path) for path in inputs]
    # Resolve only the parent, so an existing output symlink cannot disguise itself.
    output = None
    initial_output = None
    if args.output is not None:
        requested = Path(args.output).expanduser().absolute()
        try:
            output = requested.parent.resolve(strict=True) / requested.name
        except RuntimeError as exc:
            raise GlueError(f"Cannot resolve output directory {str(requested.parent)!r}: {exc}") from exc
        if not output.parent.is_dir():
            raise GlueError(f"Output parent {str(output.parent)!r} is not a directory.")
        check_output_is_not_input(output, inputs)
        initial_output = output_state(output)
        if output.suffix.lower() != inputs[0].suffix.lower():
            raise GlueError(
                f"Output extension must be {inputs[0].suffix!r} to preserve the original container; "
                f"got {output.suffix or '<none>'!r}."
            )
    infos = []
    failures = []
    for index, path in enumerate(inputs):
        print(f"Checking {index + 1}/{len(inputs)}: {path.name}", flush=True)
        info = probe(path, ffprobe)
        if dry_run:
            describe_input(index + 1, path, info)
        if infos:
            differences = compatibility_errors(inputs[0], infos[0], path, info)
            if differences:
                failures.append(f"File {str(path)!r}:\n  " + "\n  ".join(differences))
        infos.append(info)
    if failures:
        raise GlueError(
            f"Videos are incompatible with reference {str(inputs[0])!r}:\n" + "\n".join(failures)
            + "\nNo output was written. Each stream must match at the same position; "
              "audio tracks are joined by position, never mixed."
        )
    muxer = choose_muxer(inputs[0], infos[0], ffmpeg)
    if dry_run:
        describe_plan(inputs, output, infos, muxer, ffprobe, snapshots, initial_output)
        return 0
    if initial_output is not None:
        confirm_overwrite(output, args.overwrite)
    tracks = sum(s["codec_type"] == "audio" for s in infos[0]["streams"])
    print(f"Joining {len(inputs)} videos with {tracks} separate audio tracks (stream copy).", flush=True)
    glue(inputs, output, infos, muxer, ffmpeg, ffprobe, initial_output, snapshots)
    print(f"Created: {output}")
    return 0


def interrupted(signum, frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupted)
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled. Sources and existing output were left intact.", file=sys.stderr)
        sys.exit(130)
    except (GlueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
