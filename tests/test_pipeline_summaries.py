from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from aiadapters.base import LLMConnectionError
from scripts.run_pipeline import (
    LONG_SUMMARY_BLOCK_END,
    LONG_SUMMARY_BLOCK_START,
    LONG_SUMMARY_END,
    LONG_SUMMARY_START,
    SHORT_SUMMARY_BLOCK_END,
    SHORT_SUMMARY_BLOCK_START,
    SHORT_SUMMARY_END,
    SHORT_SUMMARY_START,
    LongSummarySettings,
    ShortSummarySettings,
    SummarySettings,
    _append_summaries,
    _parse_combined_summaries,
    _resolve_summary_settings,
    _validate_summary_reference_dependencies,
    _write_separate_summaries,
    call_llm_combined_summaries,
    call_llm_summary,
    main,
)


PROJECT = Path(__file__).resolve().parents[1]


class RecordingAdapter:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = []

    def generate(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.response


class PipelineAdapter:
    def __init__(self) -> None:
        self.calls = []

    def name(self) -> str:
        return "test"

    def generate(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if str(kwargs.get("label", "")).startswith("chunk"):
            return "### Cleaned lecture\n\nCleaned content."
        return (
            f"{LONG_SUMMARY_START}\nLong result\n{LONG_SUMMARY_END}\n"
            f"{SHORT_SUMMARY_START}\nShort result\n{SHORT_SUMMARY_END}"
        )


class ReferencePipelineAdapter(PipelineAdapter):
    def generate(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if str(kwargs.get("label", "")).startswith("chunk"):
            return (
                "### Timed — [00:00:05](#t=00:00:05)\n\n"
                "### Untimed\n\nCleaned content."
            )
        return (
            f"{LONG_SUMMARY_START}\nLong result\n{LONG_SUMMARY_END}\n"
            f"{SHORT_SUMMARY_START}\nShort result\n{SHORT_SUMMARY_END}"
        )


class TraceabilityPipelineAdapter(ReferencePipelineAdapter):
    def generate(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if str(kwargs.get("label", "")).startswith("chunk"):
            return (
                "### Timed — [00:00:05](#t=00:00:05)\n\n"
                "### Untimed\n\nCleaned content."
            )
        return (
            f"{LONG_SUMMARY_START}\n"
            "### 0️⃣ Timed topic\n"
            "↩ [[lecture#^src-5|Source · 00:00:05]]\n\n"
            "#### 0️⃣.0️⃣ Untimed detail\n"
            "↩ [[lecture#^txt-1|Source]]\n"
            f"{LONG_SUMMARY_END}\n"
            f"{SHORT_SUMMARY_START}\nShort result\n{SHORT_SUMMARY_END}"
        )


class RetryingPipelineAdapter:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def name(self) -> str:
        return "dummy"

    def generate(self, messages, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise LLMConnectionError("incomplete response")
        return "### Cleaned lecture\n\nCleaned content."


class SummarySettingsTests(unittest.TestCase):
    def test_new_defaults_keep_summary_generation_disabled(self) -> None:
        self.assertEqual(
            _resolve_summary_settings({}, "uk"),
            SummarySettings(
                short=ShortSummarySettings(
                    False,
                    "## Summary (не авторський)",
                    "append",
                    "-summary",
                ),
                long=LongSummarySettings(
                    False,
                    "## Long summary (не авторський)",
                    "uk",
                    "append",
                    "-longsummary",
                    False,
                ),
            ),
        )

    def test_short_and_long_have_independent_settings(self) -> None:
        cfg = {
            "summary": {
                "short": {
                    "enabled": True,
                    "heading": "## Brief",
                    "output": "append",
                    "file_suffix": "-brief",
                },
                "long": {
                    "enabled": True,
                    "heading": "## Detailed",
                    "lang": "uk",
                    "output": "separate",
                    "file_suffix": "-detailed",
                    "references": True,
                },
            }
        }
        settings = _resolve_summary_settings(cfg, "de")

        self.assertEqual(settings.enabled_types(), ("long", "short"))
        self.assertEqual(settings.short.heading, "## Brief")
        self.assertEqual(settings.long.lang, "uk")
        self.assertEqual(settings.long.output, "separate")
        self.assertTrue(settings.long.references)

    def test_cli_overrides_each_summary_independently(self) -> None:
        settings = _resolve_summary_settings(
            {},
            "en",
            cli_short_enabled=True,
            cli_long_enabled=True,
            cli_short_output="separate",
            cli_long_lang="uk",
            cli_long_references=True,
        )

        self.assertTrue(settings.short.enabled)
        self.assertEqual(settings.short.output, "separate")
        self.assertTrue(settings.long.enabled)
        self.assertEqual(settings.long.lang, "uk")
        self.assertTrue(settings.long.references)

    def test_removed_flat_config_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Removed summary configuration"):
            _resolve_summary_settings({"summary_mode": "long"}, "en")

    def test_empty_file_suffix_is_rejected(self) -> None:
        cfg = {"summary": {"long": {"file_suffix": ""}}}
        with self.assertRaisesRegex(ValueError, "summary.long.file_suffix"):
            _resolve_summary_settings(cfg, "en")
        with self.assertRaisesRegex(ValueError, "summary.long.file_suffix"):
            _resolve_summary_settings({}, "en", cli_long_suffix="")

    def test_colliding_separate_file_suffixes_are_rejected(self) -> None:
        cfg = {
            "summary": {
                "short": {
                    "enabled": True,
                    "output": "separate",
                    "file_suffix": "-same",
                },
                "long": {
                    "enabled": True,
                    "output": "separate",
                    "file_suffix": "-same",
                },
            }
        }
        with self.assertRaisesRegex(ValueError, "must differ"):
            _resolve_summary_settings(cfg, "en")

    def test_references_require_both_source_id_options(self) -> None:
        settings = _resolve_summary_settings(
            {"summary": {"long": {"references": True}}},
            "en",
        )

        with self.assertRaisesRegex(ValueError, "include_src_block_ids=true"):
            _validate_summary_reference_dependencies(
                settings,
                include_src_block_ids=False,
                include_txt_block_ids_for_untimed=True,
            )
        _validate_summary_reference_dependencies(
            settings,
            include_src_block_ids=True,
            include_txt_block_ids_for_untimed=True,
        )


class SummaryPromptTests(unittest.TestCase):
    def test_short_mode_keeps_existing_prompt_and_call_shape(self) -> None:
        adapter = RecordingAdapter("short result")
        result = call_llm_summary(
            adapter,
            "test-model",
            "SOURCE DOCUMENT",
            0.25,
            0.9,
        )

        self.assertEqual(result, "short result")
        self.assertEqual(len(adapter.calls), 1)
        messages, kwargs = adapter.calls[0]
        expected_system = (PROJECT / "prompts/summary_system.md").read_text(
            encoding="utf-8"
        )
        expected_user = (PROJECT / "prompts/summary_user.md").read_text(
            encoding="utf-8"
        )
        self.assertEqual(messages[0]["content"], expected_system)
        self.assertEqual(
            messages[1]["content"],
            expected_user + "\n\n<<<\nSOURCE DOCUMENT\n>>>",
        )
        self.assertEqual(kwargs["temperature"], 0.25)
        self.assertEqual(kwargs["top_p"], 0.9)

    def test_long_mode_injects_requested_language(self) -> None:
        adapter = RecordingAdapter("long result")
        call_llm_summary(
            adapter,
            "test-model",
            "SOURCE DOCUMENT",
            summary_type="long",
            summary_lang="de",
        )

        messages, _ = adapter.calls[0]
        prompt_text = "\n".join(message["content"] for message in messages)
        self.assertIn("code `de`", prompt_text)
        self.assertNotIn("{SUMMARY_LANGUAGE}", prompt_text)

    def test_long_reference_fragment_is_added_only_when_requested(self) -> None:
        plain_adapter = RecordingAdapter("long result")
        referenced_adapter = RecordingAdapter("long result")

        call_llm_summary(
            plain_adapter,
            "test-model",
            "SOURCE DOCUMENT",
            summary_type="long",
            summary_lang="en",
        )
        call_llm_summary(
            referenced_adapter,
            "test-model",
            "SOURCE DOCUMENT",
            summary_type="long",
            summary_lang="en",
            source_link_prefix="lecture#",
        )

        plain_system = plain_adapter.calls[0][0][0]["content"]
        referenced_system = referenced_adapter.calls[0][0][0]["content"]
        self.assertNotIn("Source traceability", plain_system)
        self.assertIn("Source traceability", referenced_system)
        self.assertIn("[[lecture#^src-NNNN", referenced_system)
        self.assertNotIn("{SOURCE_LINK_PREFIX}", referenced_system)

    def test_long_prompt_requires_continuous_hierarchical_numbering(self) -> None:
        prompt = (PROJECT / "prompts/long_summary_system.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("continuous top-level sequence", prompt)
        self.assertIn("Never restart this sequence", prompt)
        self.assertIn("#### 1️⃣.0️⃣ First detail", prompt)
        self.assertIn("#### 2️⃣.0️⃣ First detail of the next topic", prompt)

    def test_both_mode_uses_one_call_and_analyzes_source_for_each_task(self) -> None:
        response = (
            f"{LONG_SUMMARY_START}\nLong result\n{LONG_SUMMARY_END}\n"
            f"{SHORT_SUMMARY_START}\nShort result\n{SHORT_SUMMARY_END}"
        )
        adapter = RecordingAdapter(response)

        summaries = call_llm_combined_summaries(
            adapter,
            "test-model",
            "UNIQUE SOURCE DOCUMENT",
            "uk",
        )

        self.assertEqual(summaries, {"long": "Long result", "short": "Short result"})
        self.assertEqual(len(adapter.calls), 1)
        messages, _ = adapter.calls[0]
        combined_prompt = "\n".join(message["content"] for message in messages)
        self.assertEqual(combined_prompt.count("UNIQUE SOURCE DOCUMENT"), 1)
        self.assertIn("Do not derive the short summary from the long summary", combined_prompt)
        self.assertIn("expert academic summarization engine", combined_prompt)
        self.assertIn("expert lecture reconstruction", combined_prompt)
        self.assertLess(
            combined_prompt.index(LONG_SUMMARY_START),
            combined_prompt.index(SHORT_SUMMARY_START),
        )

    def test_combined_parser_rejects_unmarked_text(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "section markers"):
            _parse_combined_summaries("Long result\nShort result")

    def test_combined_parser_rejects_text_between_sections(self) -> None:
        response = (
            f"{LONG_SUMMARY_START}\nLong result\n{LONG_SUMMARY_END}\n"
            f"unexpected text\n{SHORT_SUMMARY_START}\nShort result\n{SHORT_SUMMARY_END}"
        )
        with self.assertRaisesRegex(RuntimeError, "outside section markers"):
            _parse_combined_summaries(response)


class SummaryOutputTests(unittest.TestCase):
    def settings(
        self,
        *,
        short_output: str = "append",
        long_output: str = "append",
        short_suffix: str = "-summary",
        long_suffix: str = "-longsummary",
    ) -> SummarySettings:
        return _resolve_summary_settings(
            {
                "summary": {
                    "short": {
                        "enabled": True,
                        "heading": "## Short",
                        "output": short_output,
                        "file_suffix": short_suffix,
                    },
                    "long": {
                        "enabled": True,
                        "heading": "## Long",
                        "output": long_output,
                        "file_suffix": long_suffix,
                    },
                }
            },
            "en",
        )

    def test_both_summaries_are_appended_long_then_short(self) -> None:
        output = _append_summaries(
            "Lecture",
            {"short": "Short body", "long": "Long body"},
            self.settings(),
        )

        self.assertEqual(
            output,
            f"Lecture\n\n{LONG_SUMMARY_BLOCK_START}\n"
            f"## Long\n\nLong body\n{LONG_SUMMARY_BLOCK_END}\n\n"
            f"{SHORT_SUMMARY_BLOCK_START}\n"
            f"## Short\n\nShort body\n{SHORT_SUMMARY_BLOCK_END}\n",
        )

    def test_summary_start_markers_warn_ai_inside_html_comment(self) -> None:
        for marker in (LONG_SUMMARY_BLOCK_START, SHORT_SUMMARY_BLOCK_START):
            with self.subTest(marker=marker):
                self.assertTrue(marker.startswith("<!-- LECTURE_CLEANUP_"))
                self.assertTrue(marker.endswith(" -->"))
                self.assertIn("AI-generated summary", marker)
                self.assertIn("Do not analyze it as source", marker)

    def test_separate_summaries_use_expected_sibling_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            outdir = Path(directory)
            paths = _write_separate_summaries(
                outdir,
                "lecture",
                {"short": "Short body", "long": "Long body"},
                self.settings(
                    short_output="separate",
                    long_output="separate",
                ),
            )

            self.assertEqual(
                paths,
                [outdir / "lecture-longsummary.md", outdir / "lecture-summary.md"],
            )
            self.assertEqual(
                (outdir / "lecture-longsummary.md").read_text(encoding="utf-8"),
                f"{LONG_SUMMARY_BLOCK_START}\n"
                f"## Long\n\nLong body\n{LONG_SUMMARY_BLOCK_END}\n",
            )
            self.assertEqual(
                (outdir / "lecture-summary.md").read_text(encoding="utf-8"),
                f"{SHORT_SUMMARY_BLOCK_START}\n"
                f"## Short\n\nShort body\n{SHORT_SUMMARY_BLOCK_END}\n",
            )

    def test_each_summary_can_use_a_different_output(self) -> None:
        settings = self.settings(
            short_output="append",
            long_output="separate",
            long_suffix="-details",
        )
        output = _append_summaries(
            "Lecture",
            {"short": "Short body", "long": "Long body"},
            settings,
        )

        with tempfile.TemporaryDirectory() as directory:
            paths = _write_separate_summaries(
                Path(directory),
                "lecture",
                {"short": "Short body", "long": "Long body"},
                settings,
            )

        self.assertIn("Short body", output)
        self.assertNotIn("Long body", output)
        self.assertEqual([path.name for path in paths], ["lecture-details.md"])

    def test_pipeline_writes_both_separate_summaries_from_one_call(self) -> None:
        cfg = yaml.safe_load(
            (PROJECT / "config.default.yaml").read_text(encoding="utf-8")
        )
        cfg["llm"]["provider"] = "dummy"
        cfg["llm"]["dummy"] = {
            "model": "test-model",
            "temperature": 0.0,
            "top_p": 1.0,
        }
        cfg["llm"]["request_delay_seconds"] = 0
        cfg["retry"]["attempts"] = 1
        cfg["summary"]["short"]["enabled"] = True
        cfg["summary"]["short"]["output"] = "separate"
        cfg["summary"]["long"]["enabled"] = True
        cfg["summary"]["long"]["output"] = "separate"
        cfg["suppress_edit_comments"] = True
        cfg["qc_report_mode"] = "off"
        cfg["txt_chunk_chars"] = 10000
        cfg["logging"]["level"] = "quiet"
        adapter = PipelineAdapter()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "lecture.txt"
            input_path.write_text(
                "A sufficiently long lecture sentence for pipeline testing. " * 4,
                encoding="utf-8",
            )
            outdir = root / "output"
            argv = [
                "run_pipeline.py",
                "--input",
                str(input_path),
                "--outdir",
                str(outdir),
                "--lang",
                "de",
            ]

            with patch("scripts.run_pipeline.load_effective_config", return_value=(cfg, True)), patch(
                "scripts.run_pipeline.create_llm_adapter", return_value=adapter
            ), patch("sys.argv", argv):
                result = main()

            self.assertEqual(result, 0)
            self.assertEqual(len(adapter.calls), 2)
            self.assertIn("both summaries", adapter.calls[1][1]["label"])
            main_markdown = (outdir / "lecture.md").read_text(encoding="utf-8")
            self.assertNotIn("Long result", main_markdown)
            self.assertNotIn("Short result", main_markdown)
            self.assertIn("Long result", (outdir / "lecture-longsummary.md").read_text(encoding="utf-8"))
            self.assertIn("Short result", (outdir / "lecture-summary.md").read_text(encoding="utf-8"))

    def test_references_are_rendered_before_summary_generation(self) -> None:
        cfg = yaml.safe_load(
            (PROJECT / "config.default.yaml").read_text(encoding="utf-8")
        )
        cfg["llm"]["provider"] = "dummy"
        cfg["llm"]["dummy"] = {
            "model": "test-model",
            "temperature": 0.0,
            "top_p": 1.0,
        }
        cfg["llm"]["request_delay_seconds"] = 0
        cfg["retry"]["attempts"] = 1
        cfg["summary"]["short"]["enabled"] = True
        cfg["summary"]["short"]["output"] = "append"
        cfg["summary"]["long"]["enabled"] = True
        cfg["summary"]["long"]["output"] = "append"
        cfg["suppress_edit_comments"] = True
        cfg["qc_report_mode"] = "off"
        cfg["txt_chunk_chars"] = 10000
        cfg["logging"]["level"] = "quiet"
        cfg["include_timecodes_in_headings"] = False
        cfg["include_timecodes_below_headings"] = True
        cfg["include_src_block_ids"] = True
        cfg["include_txt_block_ids_for_untimed"] = True
        cfg["process_timecodes_by_ai"] = True
        adapter = ReferencePipelineAdapter()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "lecture.txt"
            input_path.write_text(
                "[00:00:05,000] A sufficiently long timestamped lecture "
                "sentence for reference rendering. " * 4,
                encoding="utf-8",
            )
            outdir = root / "output"
            argv = [
                "run_pipeline.py",
                "--input",
                str(input_path),
                "--outdir",
                str(outdir),
                "--lang",
                "en",
            ]

            with patch(
                "scripts.run_pipeline.load_effective_config",
                return_value=(cfg, True),
            ), patch(
                "scripts.run_pipeline.create_llm_adapter",
                return_value=adapter,
            ), patch("sys.argv", argv):
                result = main()

            output = (outdir / "lecture.md").read_text(encoding="utf-8")

        self.assertEqual(result, 0)
        self.assertEqual(len(adapter.calls), 2)
        chunk_prompt = adapter.calls[0][0][1]["content"]
        summary_prompt = adapter.calls[1][0][1]["content"]
        self.assertIn("[00:00:05,000]", chunk_prompt)
        self.assertIn("### Timed ^src-5\n[🎥 00:00:05](#)", summary_prompt)
        self.assertIn("### Untimed ^txt-1", summary_prompt)
        self.assertNotIn("### Timed — [00:00:05]", summary_prompt)
        self.assertIn("### Timed ^src-5\n[🎥 00:00:05](#)", output)
        self.assertEqual(output.count("^txt-1"), 1)

    def test_long_summary_references_use_external_links_in_separate_file(self) -> None:
        cfg = yaml.safe_load(
            (PROJECT / "config.default.yaml").read_text(encoding="utf-8")
        )
        cfg["llm"]["provider"] = "dummy"
        cfg["llm"]["dummy"] = {
            "model": "test-model",
            "temperature": 0.0,
            "top_p": 1.0,
        }
        cfg["llm"]["request_delay_seconds"] = 0
        cfg["retry"]["attempts"] = 1
        cfg["summary"]["short"]["enabled"] = True
        cfg["summary"]["short"]["output"] = "append"
        cfg["summary"]["long"]["enabled"] = True
        cfg["summary"]["long"]["output"] = "separate"
        cfg["summary"]["long"]["references"] = True
        cfg["suppress_edit_comments"] = True
        cfg["qc_report_mode"] = "off"
        cfg["txt_chunk_chars"] = 10000
        cfg["logging"]["level"] = "quiet"
        cfg["include_timecodes_in_headings"] = False
        cfg["include_timecodes_below_headings"] = True
        cfg["include_src_block_ids"] = True
        cfg["include_txt_block_ids_for_untimed"] = True
        cfg["process_timecodes_by_ai"] = True
        adapter = TraceabilityPipelineAdapter()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "lecture.txt"
            input_path.write_text(
                "[00:00:05,000] A sufficiently long timestamped lecture "
                "sentence for reference rendering. " * 4,
                encoding="utf-8",
            )
            outdir = root / "output"
            argv = [
                "run_pipeline.py",
                "--input",
                str(input_path),
                "--outdir",
                str(outdir),
                "--lang",
                "en",
            ]

            with patch(
                "scripts.run_pipeline.load_effective_config",
                return_value=(cfg, True),
            ), patch(
                "scripts.run_pipeline.create_llm_adapter",
                return_value=adapter,
            ), patch("sys.argv", argv):
                result = main()

            main_output = (outdir / "lecture.md").read_text(encoding="utf-8")
            long_output = (outdir / "lecture-longsummary.md").read_text(
                encoding="utf-8"
            )

        self.assertEqual(result, 0)
        self.assertIn("Short result", main_output)
        self.assertNotIn("Timed topic", main_output)
        self.assertIn("[[lecture#^src-5|Source · 00:00:05]]", long_output)
        summary_system = adapter.calls[1][0][0]["content"]
        self.assertIn("[[lecture#^src-NNNN", summary_system)

    def test_pipeline_rejects_reference_dependencies_before_llm_creation(self) -> None:
        cfg = yaml.safe_load(
            (PROJECT / "config.default.yaml").read_text(encoding="utf-8")
        )
        cfg["summary"]["long"]["references"] = True
        cfg["include_src_block_ids"] = False
        cfg["include_txt_block_ids_for_untimed"] = True
        argv = [
            "run_pipeline.py",
            "--input",
            "unused.txt",
            "--outdir",
            "unused-output",
            "--lang",
            "en",
        ]

        with patch(
            "scripts.run_pipeline.load_effective_config",
            return_value=(cfg, True),
        ), patch("scripts.run_pipeline.create_llm_adapter") as create_adapter, patch(
            "sys.argv", argv
        ):
            result = main()

        self.assertEqual(result, 2)
        create_adapter.assert_not_called()

    def test_cli_can_render_chunk_start_references_without_ai_assignment(self) -> None:
        cfg = yaml.safe_load(
            (PROJECT / "config.default.yaml").read_text(encoding="utf-8")
        )
        cfg["llm"]["provider"] = "dummy"
        cfg["llm"]["dummy"] = {
            "model": "test-model",
            "temperature": 0.0,
            "top_p": 1.0,
        }
        cfg["llm"]["request_delay_seconds"] = 0
        cfg["retry"]["attempts"] = 1
        cfg["summary"]["short"]["enabled"] = False
        cfg["summary"]["long"]["enabled"] = False
        cfg["suppress_edit_comments"] = True
        cfg["qc_report_mode"] = "off"
        cfg["txt_chunk_chars"] = 10000
        cfg["logging"]["level"] = "quiet"
        adapter = PipelineAdapter()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "lecture.txt"
            input_path.write_text(
                "[00:00:05,000] "
                + "A sufficiently long timestamped lecture sentence for "
                "chunk-start reference rendering. "
                * 4,
                encoding="utf-8",
            )
            outdir = root / "output"
            argv = [
                "run_pipeline.py",
                "--input",
                str(input_path),
                "--outdir",
                str(outdir),
                "--lang",
                "en",
                "--no-include-timecodes",
                "--include-timecodes-below-headings",
                "--include-src-block-ids",
                "--no-process-timecodes-by-ai",
            ]

            with patch(
                "scripts.run_pipeline.load_effective_config",
                return_value=(cfg, True),
            ), patch(
                "scripts.run_pipeline.create_llm_adapter",
                return_value=adapter,
            ), patch("sys.argv", argv):
                result = main()

            output = (outdir / "lecture.md").read_text(encoding="utf-8")

        self.assertEqual(result, 0)
        self.assertEqual(len(adapter.calls), 1)
        chunk_prompt = adapter.calls[0][0][1]["content"]
        self.assertNotIn("[00:00:05,000]", chunk_prompt)
        self.assertIn("### Cleaned lecture ^src-5\n[🎥 00:00:05](#)", output)
        self.assertNotIn("### Cleaned lecture — [00:00:05]", output)


class PipelineRetryTests(unittest.TestCase):
    def _config(self) -> dict:
        cfg = yaml.safe_load(
            (PROJECT / "config.default.yaml").read_text(encoding="utf-8")
        )
        cfg["llm"]["provider"] = "dummy"
        cfg["llm"]["dummy"] = {
            "model": "test-model",
            "temperature": 0.0,
            "top_p": 1.0,
        }
        cfg["llm"]["request_delay_seconds"] = 0
        cfg["retry"] = {"attempts": 3, "pause_seconds": 0}
        cfg["summary"]["short"]["enabled"] = False
        cfg["summary"]["long"]["enabled"] = False
        cfg["suppress_edit_comments"] = True
        cfg["qc_report_mode"] = "off"
        cfg["txt_chunk_chars"] = 10000
        cfg["logging"]["level"] = "quiet"
        return cfg

    def _run_pipeline(self, root: Path, adapter: RetryingPipelineAdapter) -> int:
        input_path = root / "lecture.txt"
        input_path.write_text(
            "A sufficiently long lecture sentence for retry testing. " * 4,
            encoding="utf-8",
        )
        argv = [
            "run_pipeline.py",
            "--input",
            str(input_path),
            "--outdir",
            str(root / "output"),
            "--lang",
            "en",
        ]
        with patch(
            "scripts.run_pipeline.load_effective_config",
            return_value=(self._config(), True),
        ), patch(
            "scripts.run_pipeline.create_llm_adapter",
            return_value=adapter,
        ), patch("sys.argv", argv):
            return main()

    def test_transient_chunk_failure_is_retried_and_written(self) -> None:
        adapter = RetryingPipelineAdapter(failures=1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            result = self._run_pipeline(root, adapter)

            self.assertEqual(result, 0)
            self.assertEqual(adapter.calls, 2)
            self.assertTrue((root / "output/lecture.md").is_file())

    def test_exhausted_chunk_retries_do_not_write_partial_markdown(self) -> None:
        adapter = RetryingPipelineAdapter(failures=3)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            result = self._run_pipeline(root, adapter)

            self.assertEqual(result, 1)
            self.assertEqual(adapter.calls, 3)
            self.assertFalse((root / "output/lecture.md").exists())


if __name__ == "__main__":
    unittest.main()
