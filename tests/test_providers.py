import unittest
from unittest.mock import Mock, patch

from intext.providers import OpenAICompatibleProvider, UrllibClient, _http_message
from intext.translate import TranslationError, Translator
from intext.cache import MemoryCache


class ProviderCompletionTest(unittest.TestCase):
    def test_invalid_endpoint_is_actionable_and_never_sent(self):
        for endpoint in ("api.example.test/v1/chat/completions", "file:///tmp/model", "https://", "http://[broken", "http://localhost:99999", "https://bad host.test"):
            with self.subTest(endpoint=endpoint):
                http = Mock()
                provider = OpenAICompatibleProvider(endpoint=endpoint, api_key="", model="m", source="en", target="zh", http=http)
                with self.assertRaisesRegex(TranslationError, "接口地址无效"):
                    provider.translate("hello")
                http.post_json.assert_not_called()

    def test_local_http_endpoint_is_supported(self):
        http = Mock()
        http.post_json.return_value = {"choices": [{"message": {"content": "你好"}}]}
        provider = OpenAICompatibleProvider(endpoint="http://localhost:8080/v1/chat/completions", api_key="", model="m", source="en", target="zh", http=http)
        self.assertEqual(provider.translate("hello"), "你好")

    def test_missing_endpoint_is_reported_without_sending_a_request(self):
        http = Mock()
        provider = OpenAICompatibleProvider(endpoint="", api_key="test-token", model="m", source="en", target="zh", http=http)
        with self.assertRaisesRegex(TranslationError, "接口地址"):
            provider.translate("hello")
        http.post_json.assert_not_called()

    def test_truncated_translation_is_reported_and_not_cached(self):
        http = Mock()
        http.post_json.side_effect = [
            {"choices": [{"finish_reason": "length", "message": {"content": "只有半句的译"}}]},
            {"choices": [{"finish_reason": "stop", "message": {"content": "完整译文"}}]},
        ]
        provider = OpenAICompatibleProvider(endpoint="https://example.test/v1/chat/completions", api_key="",
            model="test", source="en", target="zh", http=http)
        translator = Translator(provider, MemoryCache(), source="en", target="zh", endpoint=provider.endpoint, model=provider.model)
        with self.assertRaisesRegex(TranslationError, "输出长度限制"):
            translator.translate("hello")
        self.assertEqual(translator.translate("hello").text, "完整译文")
        self.assertTrue(translator.translate("hello").cached)
        self.assertEqual(http.post_json.call_count, 2)


class _TimeoutResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        raise TimeoutError("The read operation timed out")


class ProviderTimeoutTest(unittest.TestCase):
    def test_error_echo_of_current_nonstandard_key_is_redacted(self):
        import io
        import urllib.error

        secret = "review-custom-key-123456"
        body = io.BytesIO(('{"error":"Invalid API key: ' + secret + '"}').encode())
        error = urllib.error.HTTPError("https://example.test", 401, "denied", {}, body)
        with patch("intext.providers.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(TranslationError) as caught:
                UrllibClient().post_json("https://example.test", {"Authorization": "Bearer " + secret}, {}, .1)
        self.assertNotIn(secret, str(caught.exception))
        self.assertIn("[redacted]", str(caught.exception))
        self.assertIn("401", str(caught.exception))

    def test_unreadable_error_body_keeps_the_http_status(self):
        import http.client
        import urllib.error

        for failure in (TimeoutError("stalled"), http.client.IncompleteRead(b"partial")):
            with self.subTest(failure=type(failure).__name__):
                body = Mock()
                body.read.side_effect = failure
                error = urllib.error.HTTPError("https://example.test", 429, "limited", {}, body)
                with patch("intext.providers.urllib.request.urlopen", side_effect=error):
                    with self.assertRaisesRegex(TranslationError, "模型请求失败（429）"):
                        UrllibClient().post_json("https://example.test", {}, {}, .1)

    def test_body_timeout_stays_a_short_error(self):
        import intext.providers as providers

        original = providers.urllib.request.urlopen
        providers.urllib.request.urlopen = lambda *_args, **_kwargs: _TimeoutResponse()
        try:
            with self.assertRaises(TranslationError) as caught:
                UrllibClient().post_json("https://example.test", {}, {"model": "m"}, 0.1)
        finally:
            providers.urllib.request.urlopen = original
        self.assertEqual(str(caught.exception), "请求超时")
        self.assertNotIn("timed out", str(caught.exception))


    def test_error_text_does_not_keep_a_bearer_token(self):
        message = _http_message(401, "invalid Authorization: Bearer sk-secretsecret")
        self.assertNotIn("sk-secretsecret", message)
        self.assertIn("请求失败", message)


if __name__ == "__main__":
    unittest.main()
