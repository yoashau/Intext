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
    label: str
    kind: str
    hint: str
    default: str
    options: tuple[str, ...] = ()


SPECS: tuple[FieldSpec, ...] = (
    FieldSpec("temperature", "温度", "number", "部分模型不接受。", "1"),
    FieldSpec("top_p", "top_p", "number", "通常与温度只开一个。", "1"),
    FieldSpec("max_tokens", "最大长度", "number", "不启用则由模型决定。", "1024"),
    FieldSpec(
        "reasoning_effort",
        "思考强度",
        "combo",
        "可选择预设或输入模型支持的值；不接受就保持关闭。",
        "medium",
        ("low", "medium", "high"),
    ),
    FieldSpec("frequency_penalty", "频率惩罚", "number", "降低重复用词。", "0"),
    FieldSpec("presence_penalty", "存在惩罚", "number", "鼓励新内容。", "0"),
)

_BY_KEY = {spec.key: spec for spec in SPECS}


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
        if key not in _BY_KEY or not isinstance(item, dict):
            continue
        value = item.get("value", state[key]["value"])
        state[key] = {
            "enabled": item.get("enabled") is True,
            "value": "" if value is None else str(value),
        }
    return state


# Keep this identical to the number test in assets/settings.html.
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


def request_preview(model: str, source: str, target: str, fields: dict[str, dict]) -> dict:
    """The JSON body that will be sent. Disabled or invalid fields are absent."""
    from .translate import PLACEHOLDER_TEXT, build_chat_body, messages_for

    return build_chat_body(
        model.strip(),
        messages_for(PLACEHOLDER_TEXT, source, target),
        enabled_payload(fields),
    )


def status_presentation(message: str) -> tuple[str, str | None]:
    """Keep the popup quiet. Long failures stay behind the help button."""
    text = " ".join(message.split())
    if len(text) <= 12:
        return text, None
    return "请求失败", text
