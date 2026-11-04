import json
import tempfile
import threading
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from intext.cache import MemoryCache, SqliteCache, TieredCache
from intext.fields import request_preview
from intext.providers import OpenAICompatibleProvider
from intext.screenshot import OcrPage, Screenshot, Selection, TextRegion
from intext.shot_translate import BLOCK_INSTRUCTION, IMAGE_INSTRUCTION, parse_regions, translate_shot
from intext.translate import STRUCTURE_INSTRUCTION, TranslationError, Translator


class ShotTranslationTests(unittest.TestCase):
    def setUp(self):
        self.shot = Screenshot(b"test-png", Selection((0, 0, 100, 60), ()))
        self.page = OcrPage((TextRegion(0, "Heading", ((0, 0), (90, 0), (90, 20), (0, 20))),
                             TextRegion(1, "A = 42", ((0, 30), (90, 30), (90, 50), (0, 50)))))
        self.http = Mock()
        self.provider = OpenAICompatibleProvider(endpoint="https://example.test/completions", api_key="secret",
            model="vision", source="en", target="zh", http=self.http)
        self.cache = MemoryCache()

    def translator(self, cache=None):
        return Translator(self.provider, self.cache if cache is None else cache,
            source=self.provider.source, target=self.provider.target, endpoint=self.provider.endpoint,
            model=self.provider.model, optional_fields=self.provider.optional_fields)

    def ocr_popup(self, *, cache=None, page=None, shot=None, use_cache=True):
        return translate_shot(self.shot if shot is None else shot, provider=self.provider,
            cache=self.cache if cache is None else cache, input_mode="ocr", display="popup",
            page=self.page if page is None else page, use_cache=use_cache)

    def test_text_and_ocr_popup_reuse_each_other_and_refresh_both_directions(self):
        for screenshot_first in (False, True):
            with self.subTest(screenshot_first=screenshot_first):
                self.cache = MemoryCache()
                self.http.reset_mock()
                self.http.post_json.return_value = {"choices": [{"message": {"content": "原译文"}}]}
                text = lambda **kw: self.translator().translate(self.page.text, **kw)
                first, second = (self.ocr_popup, text) if screenshot_first else (text, self.ocr_popup)
                self.assertFalse(first().cached)
                self.assertTrue(second().cached)
                self.assertEqual(second().text, "原译文")
                self.assertEqual(self.http.post_json.call_count, 1)
                self.http.post_json.return_value = {"choices": [{"message": {"content": "新译文"}}]}
                self.assertFalse(second(use_cache=False).cached)
                self.assertTrue(first().cached)
                self.assertEqual(first().text, "新译文")
                self.assertEqual(self.http.post_json.call_count, 2)

    def test_same_ocr_text_reuses_cache_across_different_images_and_region_boxes(self):
        self.http.post_json.return_value = {"choices": [{"message": {"content": "译文"}}]}
        self.ocr_popup()
        other = Screenshot(b"different-pixels", Selection((200, 300, 400, 500), ()))
        moved = OcrPage(tuple(replace(r, box=tuple((x + 100, y + 20) for x, y in r.box)) for r in self.page.regions))
        self.assertTrue(self.ocr_popup(shot=other, page=moved).cached)
        self.assertEqual(self.http.post_json.call_count, 1)

    def test_ocr_normalization_matches_text_without_collapsing_structure(self):
        self.http.post_json.return_value = {"choices": [{"message": {"content": "译文"}}]}
        region = self.page.regions[0]
        original = "Café\n\n    code\nTail"
        page = OcrPage((replace(region, text="  Cafe\u0301\r\n\r\n    code\r\nTail  "),))
        self.ocr_popup(page=page)
        self.assertEqual(self.http.post_json.call_args.args[2]["messages"][1]["content"], original)
        self.assertTrue(self.translator().translate(original).cached)
        for changed in (original.replace("\n\n", "\n"), original.replace("    code", "code")):
            self.assertFalse(self.translator().translate(changed).cached)
        self.assertEqual(self.http.post_json.call_count, 3)

    def test_ocr_cache_remains_available_to_text_after_reopening_database(self):
        self.http.post_json.return_value = {"choices": [{"message": {"content": "持久译文"}}]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cache.sqlite"
            disk = SqliteCache(path)
            try:
                self.ocr_popup(cache=TieredCache(MemoryCache(), disk))
            finally:
                disk.close()
            disk = SqliteCache(path)
            try:
                result = self.translator(TieredCache(MemoryCache(), disk)).translate(self.page.text)
                self.assertTrue(result.cached)
                self.assertEqual(result.text, "持久译文")
                self.assertEqual(self.http.post_json.call_count, 1)
            finally:
                disk.close()

    def test_language_model_endpoint_parameters_and_prompt_still_separate_requests(self):
        self.http.post_json.return_value = {"choices": [{"message": {"content": "译文"}}]}
        self.translator().translate(self.page.text)
        for field, value in (("source", "auto"), ("target", "ja"), ("model", "other"),
                             ("endpoint", "https://other.test/completions"), ("optional_fields", {"temperature": 0.2})):
            with self.subTest(field=field), patch.object(self.provider, field, value):
                self.assertFalse(self.ocr_popup().cached)
        from intext.translate import system_prompt
        with patch("intext.translate.system_prompt", return_value=system_prompt("en", "zh") + " New policy."):
            self.assertFalse(self.ocr_popup().cached)
        self.assertTrue(self.ocr_popup().cached)
        self.assertEqual(self.http.post_json.call_count, 7)

    def test_plain_text_cache_cannot_replace_image_or_region_translations(self):
        self.http.post_json.return_value = {"choices": [{"message": {"content": "普通译文"}}]}
        self.translator().translate(self.page.text)
        for input_mode, display in (("image", "popup"), ("ocr", "overlay"), ("image", "overlay")):
            with self.subTest(input_mode=input_mode, display=display):
                value = '图片译文' if display == "popup" else '{"regions":[{"id":0,"text":"标题"},{"id":1,"text":"A = 42"}]}'
                self.http.post_json.return_value = {"choices": [{"message": {"content": value}}]}
                args = dict(provider=self.provider, cache=self.cache, input_mode=input_mode, display=display, page=self.page)
                self.assertFalse(translate_shot(self.shot, **args).cached)
                self.assertTrue(translate_shot(self.shot, **args).cached)
        self.assertEqual(self.http.post_json.call_count, 4)

    def test_simultaneous_text_and_ocr_share_one_pending_request(self):
        entered, release, joined = threading.Event(), threading.Event(), threading.Event()

        class Pending(Future):
            def result(self, timeout=None):
                joined.set()
                return super().result(timeout=5)

        def complete(*args):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test release")
            return {"choices": [{"message": {"content": "共用译文"}}]}

        self.http.post_json.side_effect = complete
        with patch("intext.cache.Future", Pending), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.translator().translate, self.page.text)
            try:
                self.assertTrue(entered.wait(5))
                second = pool.submit(self.ocr_popup)
                self.assertTrue(joined.wait(5))
            finally:
                release.set()
            self.assertFalse(first.result(timeout=5).cached)
            self.assertTrue(second.result(timeout=5).cached)
            self.assertEqual(second.result().text, "共用译文")
        self.assertEqual(self.http.post_json.call_count, 1)

    def test_four_modes_send_only_the_intended_text_image_and_enabled_fields(self):
        for input_mode in ("ocr", "image"):
            for display in ("popup", "overlay"):
                with self.subTest(input_mode=input_mode, display=display):
                    text = '{"regions":[{"id":1,"text":"A = 42"},{"id":0,"text":"标题"}]}' if display == "overlay" else "# 标题\nA = 42"
                    self.http.post_json.return_value = {"choices": [{"message": {"content": text}}]}
                    result = translate_shot(self.shot, provider=self.provider, cache=self.cache,
                        input_mode=input_mode, display=display, page=self.page)
                    body = self.http.post_json.call_args.args[2]
                    content = body["messages"][1]["content"]
                    self.assertEqual(isinstance(content, list), input_mode == "image")
                    if input_mode == "image":
                        self.assertEqual(content[1]["image_url"]["url"], self.shot.data_url)
                    self.assertNotIn("temperature", body)
                    self.assertNotIn("reasoning_effort", body)
                    self.assertNotIn("secret", json.dumps(body))
                    if display == "overlay":
                        self.assertEqual(result.text, "标题\nA = 42")
                    else:
                        self.assertEqual(result.text, text)

    def test_bad_region_ids_and_missing_translations_are_rejected(self):
        for value in ('{"regions":[]}', '{"regions":[{"id":0,"text":"a"},{"id":0,"text":"b"}]}',
                      '{"regions":[{"id":true,"text":"a"},{"id":0,"text":"b"}]}',
                      '{"regions":[{"id":0,"text":"a"},{"id":1,"text":""}]}', 'not JSON'):
            with self.subTest(value=value), self.assertRaises(TranslationError):
                parse_regions(value, self.page)

    def test_image_identity_is_part_of_cache_and_retry_refreshes(self):
        self.http.post_json.return_value = {"choices": [{"message": {"content": "译文"}}]}
        args = dict(provider=self.provider, cache=self.cache, input_mode="image", display="popup")
        self.assertFalse(translate_shot(self.shot, **args).cached)
        self.assertTrue(translate_shot(self.shot, **args).cached)
        other = Screenshot(b"other-png", self.shot.selection)
        self.assertFalse(translate_shot(other, **args).cached)
        self.assertFalse(translate_shot(self.shot, use_cache=False, **args).cached)
        self.assertEqual(self.http.post_json.call_count, 3)

    def test_incomplete_overlay_response_is_not_cached(self):
        self.http.post_json.return_value = {"choices": [{"message": {"content": '{"regions":[]}'}}]}
        for _ in range(2):
            with self.assertRaises(TranslationError):
                translate_shot(self.shot, provider=self.provider, cache=self.cache,
                               input_mode="ocr", display="overlay", page=self.page)
        self.assertEqual(self.http.post_json.call_count, 2)

    def test_preview_omits_secrets_and_shared_policy_matches_runtime(self):
        path = Path(__file__).resolve().parents[1] / "src/intext/assets/request-policy.js"
        policy = json.loads(path.read_text(encoding="utf-8").split("window.intextPolicy = ", 1)[1].removesuffix(";\n"))
        self.assertEqual(policy, {"structure": STRUCTURE_INSTRUCTION, "image": IMAGE_INSTRUCTION, "blocks": BLOCK_INSTRUCTION})
        body = request_preview("vision", "en", "zh", {}, kind="shot", shot_input="image", shot_display="overlay")
        self.assertEqual(body["messages"][1]["content"][1]["type"], "image_url")
        self.assertNotIn("temperature", body)
