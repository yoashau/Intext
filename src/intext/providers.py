"""OpenAI-compatible chat provider.

The HTTP body is built by translate.build_chat_body. This module only sends
that body; it does not invent sampling or reasoning fields.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Protocol

from .translate import TranslationError, build_chat_body, extract_chat_text, messages_for


class HttpClient(Protocol):
    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        body: dict,
        timeout: float,
    ) -> dict: ...


class UrllibClient:
    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        body: dict,
        timeout: float,
    ) -> dict:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise TranslationError(_http_message(exc.code, detail)) from exc
        except TimeoutError as exc:
            raise TranslationError("请求超时") from exc
        except urllib.error.URLError as exc:
            raise TranslationError("无法连接模型服务") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TranslationError("模型返回的不是 JSON") from exc
        if not isinstance(payload, dict):
            raise TranslationError("模型返回的内容无法读取")
        return payload


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        model: str,
        source: str,
        target: str,
        optional_fields: dict | None = None,
        http: HttpClient | None = None,
        timeout: float = 90.0,
    ) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.source = source
        self.target = target
        self.optional_fields = optional_fields or {}
        self.http = http or UrllibClient()
        self.timeout = timeout

    def translate(self, text: str) -> str:
        return self.complete(messages_for(text, self.source, self.target))

    def complete(self, messages: list[dict]) -> str:
        body = build_chat_body(
            self.model,
            messages,
            self.optional_fields,
        )
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = self.http.post_json(self.endpoint, headers, body, self.timeout)
        return extract_chat_text(payload)


def _redact_secret(detail: str) -> str:
    detail = re.sub(r"(?i)bearer\s+\S+", "Bearer [redacted]", detail)
    return re.sub(r"\bsk-[A-Za-z0-9_\-]{8,}", "[redacted]", detail)


def _http_message(status: int, detail: str) -> str:
    compact = " ".join(_redact_secret(detail).split())
    if len(compact) > 180:
        compact = compact[:180] + "…"
    if compact:
        return f"模型请求失败（{status}）：{compact}"
    return f"模型请求失败（{status}）"
