import threading
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from unittest.mock import patch

from intext.cache import MemoryCache
from intext.translate import TranslationError, Translator


class CacheConcurrencyTest(unittest.TestCase):
    def translator(self, provider, cache):
        return Translator(
            provider, cache, source="en", target="zh",
            endpoint="https://example.test/v1/chat/completions", model="fake",
        )

    def test_concurrent_translators_share_one_request_and_one_error(self):
        # Wait until every follower has joined before releasing the provider.
        # No sleeps or live service are needed to reproduce the race.
        for fails in (False, True):
            with self.subTest(fails=fails):
                cache = MemoryCache()
                entered, release, joined = threading.Event(), threading.Event(), threading.Event()
                lock = threading.Lock()
                followers = 0

                class Pending(Future):
                    def result(self, timeout=None):
                        nonlocal followers
                        with lock:
                            followers += 1
                            if followers == 5:
                                joined.set()
                        return super().result(timeout=5)

                class Provider:
                    calls = 0

                    def translate(self, text):
                        self.calls += 1
                        entered.set()
                        if not release.wait(5):
                            raise TimeoutError("test release")
                        if fails:
                            raise TranslationError("请求超时")
                        return "你好"

                provider = Provider()
                with patch("intext.cache.Future", Pending), ThreadPoolExecutor(max_workers=6) as pool:
                    work = [pool.submit(self.translator(provider, cache).translate, "hello") for _ in range(6)]
                    try:
                        self.assertTrue(entered.wait(5))
                        self.assertTrue(joined.wait(5))
                    finally:
                        release.set()
                    if fails:
                        for future in work:
                            with self.assertRaisesRegex(TranslationError, "请求超时"):
                                future.result(timeout=5)
                    else:
                        results = [future.result(timeout=5) for future in work]
                        self.assertEqual([result.text for result in results], ["你好"] * 6)
                        self.assertEqual(sum(not result.cached for result in results), 1)
                self.assertEqual(provider.calls, 1)
                self.assertEqual(cache._pending, {})
                provider.translate = lambda text: "重试成功"
                if fails:
                    self.assertEqual(self.translator(provider, cache).translate("hello").text, "重试成功")

    def test_refresh_supersedes_an_older_request_without_being_overwritten(self):
        cache = MemoryCache()
        entered, release = threading.Event(), threading.Event()

        class Provider:
            def translate(self, text):
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("test release")
                return "旧结果"

        old = self.translator(Provider(), cache)
        new = self.translator(type("Provider", (), {"translate": lambda self, text: "新结果"})(), cache)
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(old.translate, "hello")
            try:
                self.assertTrue(entered.wait(5))
                refreshed = new.translate("hello", use_cache=False)
                self.assertFalse(refreshed.cached)
            finally:
                release.set()
            self.assertEqual(first.result(timeout=5).text, "旧结果")
        self.assertEqual(old.translate("hello").text, "新结果")

    def test_refresh_hides_old_cache_and_normal_calls_join_the_refresh(self):
        cache = MemoryCache()
        cache.put("key", "旧结果")
        entered, release, joined = threading.Event(), threading.Event(), threading.Event()

        class Pending(Future):
            def result(self, timeout=None):
                joined.set()
                return super().result(timeout=5)

        def load():
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test release")
            return "新结果"

        with patch("intext.cache.Future", Pending), ThreadPoolExecutor(max_workers=2) as pool:
            refresh = pool.submit(cache.get_or_load, "key", load, refresh=True)
            try:
                self.assertTrue(entered.wait(5))
                self.assertIsNone(cache.peek("key"))
                follower = pool.submit(cache.get_or_load, "key", lambda: self.fail("duplicate request"))
                self.assertTrue(joined.wait(5))
            finally:
                release.set()
            self.assertEqual(refresh.result(timeout=5), ("新结果", False))
            self.assertEqual(follower.result(timeout=5), ("新结果", True))
        self.assertEqual(cache.peek("key"), "新结果")

    def test_different_keys_do_not_block_one_another(self):
        cache = MemoryCache()
        barrier = threading.Barrier(2)

        def load(text):
            barrier.wait(timeout=5)
            return text

        with ThreadPoolExecutor(max_workers=2) as pool:
            work = [pool.submit(cache.get_or_load, key, lambda key=key: load(key)) for key in ("a", "b")]
            self.assertEqual([future.result(timeout=5)[0] for future in work], ["a", "b"])

    def test_line_endings_match_but_paragraphs_and_meaning_stay_distinct(self):
        cache = MemoryCache()
        seen = []
        provider = type("Provider", (), {"translate": lambda self, text: seen.append(text) or "译文"})()
        translator = self.translator(provider, cache)
        translator.translate("First.\r\n\r\nSecond.")
        self.assertTrue(translator.translate("First.\n\nSecond.").cached)
        self.assertTrue(translator.translate("First.\r\rSecond.").cached)
        self.assertFalse(translator.translate("First.\nSecond.").cached)
        self.assertFalse(translator.translate("First. Second.").cached)
        translator.translate("It is safe.")
        self.assertFalse(translator.translate("It is not safe.").cached)
        self.assertEqual(seen[0], "First.\n\nSecond.")

    def test_empty_results_are_not_cached(self):
        cache = MemoryCache()
        provider = type("Provider", (), {"translate": lambda self, text: " "})()
        translator = self.translator(provider, cache)
        with self.assertRaises(TranslationError):
            translator.translate("hello")
        provider.translate = lambda text: "你好"
        self.assertFalse(translator.translate("hello").cached)


if __name__ == "__main__":
    unittest.main()
