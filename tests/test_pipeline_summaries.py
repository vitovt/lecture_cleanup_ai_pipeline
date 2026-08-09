from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from scripts.run_pipeline import (
    LONG_SUMMARY_END,
    LONG_SUMMARY_START,
    SHORT_SUMMARY_END,
    SHORT_SUMMARY_START,
    _append_summaries,
    _parse_combined_summaries,
    _resolve_summary_settings,
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


class SummarySettingsTests(unittest.TestCase):
    def test_new_defaults_keep_summary_generation_disabled(self) -> None:
        self.assertEqual(
            _resolve_summary_settings({}, "uk"),
            ("disabled", "append", "uk"),
        )

    def test_legacy_true_preserves_short_appended_summary(self) -> None:
        cfg = {
            "summary_mode": "disabled",
            "summary_output": "append",
            "append_summary": True,
        }
        self.assertEqual(
            _resolve_summary_settings(cfg, "de"),
            ("short", "append", "de"),
        )

    def test_legacy_false_disables_even_cli_both_mode(self) -> None:
        cfg = {"append_summary": False}
        self.assertEqual(
            _resolve_summary_settings(
                cfg,
                "en",
                cli_mode="both",
                cli_output="separate",
                cli_long_lang="uk",
            ),
            ("disabled", "separate", "uk"),
        )

    def test_cli_can_disable_a_legacy_true_configuration(self) -> None:
        cfg = {"append_summary": True}
        self.assertEqual(
            _resolve_summary_settings(cfg, "en", cli_mode="disabled"),
            ("disabled", "append", "en"),
        )

    def test_explicit_long_summary_language_overrides_lecture_language(self) -> None:
        cfg = {
            "summary_mode": "long",
            "summary_output": "separate",
            "long_summary_lang": "uk",
        }
        self.assertEqual(
            _resolve_summary_settings(cfg, "de"),
            ("long", "separate", "uk"),
        )

    def test_invalid_config_value_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "summary_mode"):
            _resolve_summary_settings({"summary_mode": "medium"}, "en")


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
    def test_both_summaries_are_appended_long_then_short(self) -> None:
        output = _append_summaries(
            "Lecture",
            {"short": "Short body", "long": "Long body"},
            "## Short",
            "## Long",
        )

        self.assertEqual(
            output,
            "Lecture\n\n## Long\n\nLong body\n\n## Short\n\nShort body\n",
        )

    def test_separate_summaries_use_expected_sibling_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            outdir = Path(directory)
            paths = _write_separate_summaries(
                outdir,
                "lecture",
                {"short": "Short body", "long": "Long body"},
                "## Short",
                "## Long",
            )

            self.assertEqual(
                paths,
                [outdir / "lecture-longsummary.md", outdir / "lecture-summary.md"],
            )
            self.assertEqual(
                (outdir / "lecture-longsummary.md").read_text(encoding="utf-8"),
                "## Long\n\nLong body\n",
            )
            self.assertEqual(
                (outdir / "lecture-summary.md").read_text(encoding="utf-8"),
                "## Short\n\nShort body\n",
            )

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
        cfg["summary_mode"] = "both"
        cfg["summary_output"] = "separate"
        cfg["long_summary_lang"] = "default"
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


if __name__ == "__main__":
    unittest.main()
