import tempfile
import unittest
from pathlib import Path

from intext.cache import MemoryCache, SqliteCache, TieredCache
from intext.translate import Translation, Translator


class FakeProvider:
    def __init__(self):
        self.calls = 0

    def translate(self, text: str) -> str:
        self.calls += 1
        return "译文:" + text


class CacheTest(unittest.TestCase):
    def test_memory_evicts_oldest(self):
        cache = MemoryCache(limit=2)
        cache.put("a", "1")
        cache.put("b", "2")
        cache.put("c", "3")
        self.assertIsNone(cache.get("a"))
        self.assertEqual(cache.get("c"), "3")

    def test_disk_roundtrip_and_provider_is_not_called_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            disk = SqliteCache(Path(tmp) / "cache.sqlite")
            cache = TieredCache(MemoryCache(), disk)
            provider = FakeProvider()
            translator = Translator(
                provider,
                cache,
                source="auto",
                target="zh",
                endpoint="https://example.test/v1/chat/completions",
                model="gpt 6.1 sol",
            )
            first = translator.translate("hello")
            second = translator.translate("hello")
            self.assertEqual(first, Translation(text="译文:hello", cached=False, model="gpt 6.1 sol"))
            self.assertTrue(second.cached)
            self.assertEqual(provider.calls, 1)
            disk.close()

    def test_explicit_retry_refetches_and_replaces_the_cached_result(self):
        cache = MemoryCache()
        provider = FakeProvider()
        translator = Translator(
            provider,
            cache,
            source="auto",
            target="zh",
            endpoint="https://example.test/v1/chat/completions",
            model="gpt 6.1 sol",
        )
        provider.translate = lambda text: "第一次"
        first = translator.translate("hello")
        cached = translator.translate("hello")
        provider.translate = lambda text: "第二次"
        refreshed = translator.translate("hello", use_cache=False)
        stored = translator.translate("hello")
        self.assertFalse(first.cached)
        self.assertTrue(cached.cached)
        self.assertEqual(cached.text, "第一次")
        self.assertFalse(refreshed.cached)
        self.assertEqual(refreshed.text, "第二次")
        self.assertTrue(stored.cached)
        self.assertEqual(stored.text, "第二次")

    def test_disk_drops_the_oldest_past_the_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            disk = SqliteCache(Path(tmp) / "cache.sqlite", limit=2)
            disk.put("a", "1")
            disk.put("b", "2")
            disk.put("c", "3")
            self.assertIsNone(disk.get("a"))
            self.assertEqual(disk.get("c"), "3")
            disk.close()



if __name__ == "__main__":
    unittest.main()
