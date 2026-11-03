import unittest

from intext.providers import UrllibClient, _http_message
from intext.translate import TranslationError


class _TimeoutResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        raise TimeoutError("The read operation timed out")


class ProviderTimeoutTest(unittest.TestCase):
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
