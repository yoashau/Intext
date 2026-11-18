"""Optional request fields.

Common fields stay available, but a field is sent only when it is enabled
and its value is valid. The settings preview is the raw request body.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FieldSpec:
    key: str
    kind: str
    default: str


SPECS: tuple[FieldSpec, ...] = (
    FieldSpec("temperature", "number", "1"),
    FieldSpec("top_p", "number", "1"),
    FieldSpec("max_tokens", "number", "1024"),
    FieldSpec("reasoning_effort", "text", "medium"),
    FieldSpec("frequency_penalty", "number", "0"),
    FieldSpec("presence_penalty", "number", "0"),
)

def default_field_state() -> dict[str, dict]:
    return {
        spec.key: {"enabled": False, "value": spec.default}
        for spec in SPECS
    }


def normalize_field_state(raw: object) -> dict[str, dict]:
    state = default_field_state()
    if not isinstance(raw, dict):
        return state
    for key, item in raw.items():
        if key not in state or not isinstance(item, dict):
            continue
        value = item.get("value", state[key]["value"])
        state[key] = {
            "enabled": item.get("enabled") is True,
            "value": "" if value is None else str(value),
        }
    return state


# Keep this identical to the number test in assets/settings.js.
# The preview and the request must accept the same spellings.
NUMBER_TEXT = r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?$"
_NUMBER = re.compile(NUMBER_TEXT)


def coerce_value(spec: FieldSpec, raw: str) -> object | None:
    text = raw.strip()
    if not text:
        return None
    if spec.kind == "number":
        if _NUMBER.fullmatch(text) is None:
            return None
        number = float(text)
        if not math.isfinite(number):
            return None
        if spec.key == "max_tokens" and (number <= 0 or not number.is_integer()):
            return None
        if number.is_integer():
            return int(number)
        return number
    return text


def enabled_payload(fields: dict[str, dict]) -> dict:
    payload: dict = {}
    state = normalize_field_state(fields)
    for spec in SPECS:
        item = state[spec.key]
        if not item["enabled"]:
            continue
        value = coerce_value(spec, item["value"])
        if value is None:
            continue
        payload[spec.key] = value
    return payload


def request_preview(model: str, source: str, target: str, fields: dict[str, dict], *,
                    kind: str = "text", shot_input: str = "ocr", shot_display: str = "popup") -> dict:
    """The JSON body that will be sent. Disabled or invalid fields are absent."""
    from .translate import PLACEHOLDER_TEXT, build_chat_body, messages_for

    messages = messages_for(PLACEHOLDER_TEXT, source, target)
    if kind == "shot" and (shot_input == "image" or shot_display == "overlay"):
        from .shot_translate import shot_messages
        from .screenshot import OcrPage, TextRegion

        page = OcrPage((TextRegion(0, "<截图文字区域>", ((0, 0), (1, 0), (1, 1), (0, 1))),)) if shot_display == "overlay" else None
        messages = shot_messages(source, target, image="data:image/png;base64,<截图PNG>" if shot_input == "image" else None, page=page)
    elif kind == "shot":
        messages = messages_for("<截图识别文字>", source, target)
    return build_chat_body(
        model.strip(),
        messages,
        enabled_payload(fields),
    )
