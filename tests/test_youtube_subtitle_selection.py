"""Offline metadata tests for language and source selection."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "selection", Path(__file__).resolve().parents[1] / "subtitle-utils/select_youtube_subtitles.py")
selection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selection)


def entry(lang, auto=True, translation=None, name="Original", ext="vtt"):
    url = f"https://example.com/api/timedtext?lang={lang}&fmt={ext}"
    if auto:
        url += "&kind=asr"
    if translation:
        url += f"&tlang={translation}"
    return {"url": url, "name": name, "ext": ext}


def metadata(auto=(), manual=(), audio=None):
    return {"automatic_captions": {c: [entry(c.removesuffix('-orig'))] for c in auto},
            "subtitles": {c: [entry(c, auto=False)] for c in manual},
            "formats": ([{"language": audio, "language_preference": 10, "acodec": "opus"}]
                        if audio else [])}


class SelectionTests(unittest.TestCase):
    def test_original_audio_wins_over_alphabet_and_default_dub(self):
        info = metadata(auto=("ar-orig", "en-orig", "uk-orig"), audio="en-US")
        info["language"] = "ar"
        info["formats"] += [{"language": "ar", "language_preference": 5, "acodec": "opus"}]
        info["formats"] += info["formats"][:1]
        self.assertEqual(selection.select(info)[:2], ("en-orig", "auto"))

    def test_ambiguous_audio_requires_explicit_language(self):
        info = metadata(auto=("ar-orig", "en-orig"))
        info["language"] = "ar"  # Unmarked top-level language is unreliable.
        with self.assertRaisesRegex(ValueError, "--lang CODE"):
            selection.select(info)
        self.assertEqual(selection.select(info, "en")[0], "en-orig")

    def test_multiple_original_audio_languages_are_ambiguous(self):
        info = metadata(auto=("en-orig", "de-orig"), audio="en")
        info["formats"].append({"language": "de", "language_preference": 10, "acodec": "opus"})
        with self.assertRaisesRegex(ValueError, "Multiple original audio"):
            selection.select(info)

    def test_source_policies_and_no_translation_fallback(self):
        info = metadata(auto=("en-orig",), manual=("en",), audio="en-US")
        self.assertEqual(selection.select(info, source="auto")[:2], ("en-orig", "auto"))
        for source in ("manual", "prefer-manual"):
            self.assertEqual(selection.select(info, source=source)[:2], ("en", "manual"))
        info["subtitles"] = {}
        self.assertEqual(selection.select(info, source="prefer-manual")[1], "auto")
        with self.assertRaisesRegex(ValueError, "No manual"):
            selection.select(info, source="manual")
        info["automatic_captions"] = {"en": [entry("ar", translation="en")]}
        with self.assertRaisesRegex(ValueError, "Available native subtitles: none"):
            selection.select(info)

    def test_mixed_plain_key_is_filtered_and_orig_alias_preferred(self):
        info = metadata(auto=("en-orig",), audio="en")
        info["automatic_captions"]["en"] = [entry("ar", translation="en"), entry("en")]
        self.assertEqual(selection.select(info)[0], "en-orig")
        del info["automatic_captions"]["en-orig"]
        self.assertEqual(selection.select(info)[2], [entry("en")])

    def test_exact_region_precedes_source_preference(self):
        info = metadata(auto=("de-CH-orig",), manual=("de-DE",), audio="de-CH")
        self.assertEqual(selection.select(info, source="prefer-manual")[:2], ("de-CH-orig", "auto"))
        with self.assertRaisesRegex(ValueError, "No manual"):
            selection.select(info, source="manual")

    def test_generic_then_unique_variant_and_ambiguity(self):
        info = metadata(auto=("de-DE-orig", "de-CH-orig"))
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            selection.select(info, "de")
        self.assertEqual(selection.select(info, "de-CH")[0], "de-CH-orig")
        del info["automatic_captions"]["de-CH-orig"]
        self.assertEqual(selection.select(info, "de")[0], "de-DE-orig")
        info["subtitles"] = {"de": [entry("de", False)]}
        self.assertEqual(selection.select(info, "de-AT", "prefer-manual")[0], "de")

    def test_chinese_scripts_are_not_interchangeable(self):
        info = metadata(auto=("zh-Hans-orig", "zh-Hant-orig"))
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            selection.select(info, "zh")
        self.assertEqual(selection.select(info, "zh-Hans-CN")[0], "zh-Hans-orig")
        del info["automatic_captions"]["zh-Hans-orig"]
        with self.assertRaisesRegex(ValueError, "unavailable"):
            selection.select(info, "zh-Hans")

    def test_formats_are_not_tracks_but_named_variants_are(self):
        info = metadata(auto=("en-orig",))
        info["automatic_captions"]["en-orig"].append(entry("en", ext="json3"))
        self.assertEqual(selection.select(info)[0], "en-orig")
        info["automatic_captions"]["en-orig"].append(entry("en", name="SDH"))
        with self.assertRaisesRegex(ValueError, "Multiple named.*SDH"):
            selection.select(info)
