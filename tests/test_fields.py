import json
import unittest
from pathlib import Path

from intext.fields import enabled_payload, request_preview, status_presentation
from intext.translate import TranslationError, build_chat_body, cache_key, extract_chat_text, messages_for, swapped_languages


class FieldPayloadTest(unittest.TestCase):
    def test_disabled_fields_are_omitted(self):
        fields = {
            "temperature": {"enabled": False, "value": "0.2"},
            "reasoning_effort": {"enabled": True, "value": "high"},
            "max_tokens": {"enabled": True, "value": "not-a-number"},
        }
        self.assertEqual(enabled_payload(fields), {"reasoning_effort": "high"})
        self.assertNotIn("temperature", enabled_payload(fields))

    def test_custom_reasoning_is_preserved_in_preview_and_request(self):
        fields = {"reasoning_effort": {"enabled": True, "value": "  xhigh  "}}
        self.assertEqual(enabled_payload(fields), {"reasoning_effort": "xhigh"})
        self.assertEqual(request_preview("custom", "auto", "zh", fields)["reasoning_effort"], "xhigh")
        fields["reasoning_effort"]["enabled"] = False
        self.assertNotIn("reasoning_effort", enabled_payload(fields))
        fields["reasoning_effort"].update(enabled=True, value="   ")
        self.assertNotIn("reasoning_effort", enabled_payload(fields))

    def test_preview_is_the_raw_request_body(self):
        fields = {
            "temperature": {"enabled": True, "value": "0.2"},
            "reasoning_effort": {"enabled": False, "value": "high"},
        }
        body = request_preview("gpt 6.1 sol", "auto", "zh", fields)
        self.assertEqual(
            set(body),
            {"model", "messages", "temperature"},
        )
        self.assertEqual(body["model"], "gpt 6.1 sol")
        self.assertEqual(body["temperature"], 0.2)
        self.assertEqual(body["messages"][1]["content"], "<选中文字>")
        self.assertNotIn("reasoning_effort", body)
        rendered = json.dumps(body, ensure_ascii=False, indent=2)
        self.assertIn('"temperature": 0.2', rendered)
        self.assertNotIn("reasoning_effort", rendered)
        self.assertNotIn("api_key", rendered)

    def test_disabled_temperature_disappears_from_the_body(self):
        enabled = request_preview(
            "gpt 6.1 sol",
            "auto",
            "zh",
            {"temperature": {"enabled": True, "value": "0.2"}},
        )
        disabled = request_preview(
            "gpt 6.1 sol",
            "auto",
            "zh",
            {"temperature": {"enabled": False, "value": "0.2"}},
        )
        self.assertIn("temperature", enabled)
        self.assertNotIn("temperature", disabled)

    def test_body_contains_only_enabled_fields(self):
        body = build_chat_body(
            "gpt 6.1 sol",
            messages_for("hello", "auto", "zh"),
            enabled_payload({"temperature": {"enabled": False, "value": "1"}}),
        )
        self.assertEqual(set(body), {"model", "messages"})

    def test_cache_key_includes_enabled_fields(self):
        shared = dict(
            text="hello",
            source="auto",
            target="zh",
            endpoint="https://example.test/v1/chat/completions",
            model="gpt 6.1 sol",
            prompt="same",
        )
        plain = cache_key(**shared, options={})
        warm = cache_key(**shared, options={"temperature": 0.2})
        self.assertNotEqual(plain, warm)

    def test_preview_and_request_reject_the_same_unstable_numbers(self):
        fields = {
            "temperature": {"enabled": True, "value": "inf"},
            "top_p": {"enabled": True, "value": "1_000"},
            "max_tokens": {"enabled": True, "value": "0x10"},
            "frequency_penalty": {"enabled": True, "value": "nan"},
            "presence_penalty": {"enabled": True, "value": "0.5"},
        }
        self.assertEqual(enabled_payload(fields), {"presence_penalty": 0.5})
        html = Path(__file__).resolve().parents[1].joinpath("src/intext/assets/settings.html").read_text(encoding="utf-8")
        self.assertIn("const NUMBER_TEXT = ", html)
        self.assertIn("fields.NUMBER_TEXT", html)

    def test_long_status_stays_out_of_the_label(self):
        label, detail = status_presentation("模型请求失败（400）：temperature is not supported")
        self.assertEqual(label, "请求失败")
        self.assertIn("temperature", detail)

    def test_reasoning_parts_are_not_returned_as_the_translation(self):
        payload = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "reasoning", "text": "think first"},
                            {"type": "text", "text": "你好"},
                        ]
                    }
                }
            ]
        }
        self.assertEqual(extract_chat_text(payload), "你好")
        reasoning_only = {
            "choices": [{"message": {"content": [{"type": "reasoning", "text": "think"}]}}]
        }
        with self.assertRaises(TranslationError):
            extract_chat_text(reasoning_only)



    def test_swap_does_not_make_both_sides_the_same(self):
        self.assertEqual(swapped_languages("auto", "en"), ("en", "zh"))
        self.assertEqual(swapped_languages("zh", "auto"), ("en", "zh"))
        self.assertEqual(swapped_languages("en", "zh"), ("zh", "en"))


    def test_string_false_does_not_enable_a_field(self):
        fields = {"temperature": {"enabled": "false", "value": "0.2"}}
        self.assertEqual(enabled_payload(fields), {})


if __name__ == "__main__":
    unittest.main()
