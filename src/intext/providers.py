"""OpenAI-compatible chat provider.

The HTTP body is built by translate.build_chat_body. This module only sends
that body; it does not invent sampling or reasoning fields.
"""

from __future__ import annotations

import urllib.parse
from typing import Protocol

from .http_client import CancellationToken, _http_message, default_http_client
from .translate import TranslationError, build_chat_body, extract_chat_text, messages_for


class HttpClient(Protocol):
    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        body: dict,
        timeout: float,
        *, cancellation: CancellationToken | None = None,
    ) -> dict: ...


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
        cancellation: CancellationToken | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.source = source
        self.target = target
        self.optional_fields = optional_fields or {}
        self.http = http or default_http_client()
        self.timeout = timeout
        self.cancellation = cancellation

    def translate(self, text: str) -> str:
        return self.complete(messages_for(text, self.source, self.target))

    def complete(self, messages: list[dict]) -> str:
        if self.cancellation is not None:
            self.cancellation.check()
        if not self.endpoint.strip():
            raise TranslationError("未配置接口地址，请在设置中填写完整地址。")
        try:
            address = urllib.parse.urlsplit(self.endpoint)
            valid = (address.scheme in {"http", "https"} and bool(address.hostname)
                     and not any(char.isspace() for char in self.endpoint))
            address.port  # Validate malformed and out-of-range ports as well.
        except ValueError:
            valid = False
        if not valid:
            raise TranslationError("接口地址无效，请填写以 http:// 或 https:// 开头的完整地址。")
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
        if self.cancellation is None:
            payload = self.http.post_json(self.endpoint, headers, body, self.timeout)
        else:
            payload = self.http.post_json(self.endpoint, headers, body, self.timeout, cancellation=self.cancellation)
        return extract_chat_text(payload)
