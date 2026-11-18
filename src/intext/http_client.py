"""Shared, bounded HTTP connections with cancellation across worker threads."""

from __future__ import annotations

import asyncio
import atexit
import json
import re
import ssl
import threading
from concurrent.futures import CancelledError, Future
from contextlib import aclosing
from typing import Callable

from .translate import TranslationError


class CancellationToken:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancelled = False
        self._callbacks: set[Callable[[], object]] = set()

    def check(self) -> None:
        with self._lock:
            if self._cancelled:
                raise CancelledError()

    def subscribe(self, callback: Callable[[], object]) -> Callable[[], None]:
        with self._lock:
            cancelled = self._cancelled
            if not cancelled:
                self._callbacks.add(callback)
        if cancelled:
            callback()

        def remove() -> None:
            with self._lock:
                self._callbacks.discard(callback)

        return remove

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            callbacks = tuple(self._callbacks)
            self._callbacks.clear()
        for callback in callbacks:
            callback()


class PooledHttpClient:
    """One lazy I/O loop and pool per app; no thread per socket or polling.

    Translation workers retain their synchronous API. Cancelling their token
    cancels the actual asynchronous request, including a queued pool wait.
    """

    def __init__(self, max_concurrency: int = 2, *, transport=None, trust_env: bool = True) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self._limit = max_concurrency
        self._transport = transport
        self._trust_env = trust_env
        self._lock = threading.Lock()
        self._closed = False
        self._loop = None
        self._thread = None
        self._pending: set[Future] = set()
        self._client = None
        self._semaphore = None

    def _run(self, loop) -> None:
        asyncio.set_event_loop(loop)
        try:
            loop.run_forever()
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            loop.close()

    def _discard(self, future: Future) -> None:
        with self._lock:
            self._pending.discard(future)

    def post_json(self, url: str, headers: dict[str, str], body: dict, timeout: float,
                  *, cancellation: CancellationToken | None = None) -> dict:
        if cancellation is not None:
            cancellation.check()
        with self._lock:
            if self._closed:
                raise CancelledError()
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(target=self._run, args=(self._loop,),
                                                name="Intext HTTP", daemon=True)
                self._thread.start()
            future = asyncio.run_coroutine_threadsafe(self._post(url, headers, body, timeout), self._loop)
            self._pending.add(future)
        future.add_done_callback(self._discard)
        unsubscribe = cancellation.subscribe(future.cancel) if cancellation is not None else None
        try:
            result = future.result()
            if cancellation is not None:
                cancellation.check()
            return result
        finally:
            if unsubscribe is not None:
                unsubscribe()

    async def _post(self, url, headers, body, timeout):
        import httpx

        status = None
        secret = headers.get("Authorization", "").removeprefix("Bearer ")
        try:
            # The deadline includes queueing and the complete response, rather
            # than restarting a socket timeout for every chunk of a slow body.
            async with asyncio.timeout(timeout):
                if self._client is None:
                    self._semaphore = asyncio.Semaphore(self._limit)
                    self._client = httpx.AsyncClient(
                        verify=ssl.create_default_context(), trust_env=self._trust_env,
                        limits=httpx.Limits(max_connections=self._limit, max_keepalive_connections=self._limit,
                                            keepalive_expiry=30),
                        transport=self._transport,
                    )
                async with self._semaphore:
                    request = self._client.build_request("POST", url, headers=headers, json=body, timeout=timeout)
                    origin = (request.url.scheme, request.url.raw_host, request.url.port)
                    for _ in range(self._client.max_redirects + 1):
                        async with aclosing(await self._client.send(request, stream=True, follow_redirects=False)) as response:
                            request = response.next_request
                            if request is None:
                                status = response.status_code
                                raw = (await response.aread()).decode("utf-8", errors="replace")
                                break
                            if (request.url.scheme, request.url.raw_host, request.url.port) != origin:
                                raise TranslationError("接口重定向到其他地址，请在设置中填写最终接口地址。")
                    else:
                        raise TranslationError("接口重定向次数过多，请检查接口地址。")
        except (httpx.TimeoutException, TimeoutError) as exc:
            if status is not None and not 200 <= status < 300:
                raise TranslationError(_http_message(status, "")) from exc
            raise TranslationError("请求超时") from exc
        except httpx.HTTPError as exc:
            if status is not None and not 200 <= status < 300:
                raise TranslationError(_http_message(status, "")) from exc
            raise TranslationError("无法连接模型服务") from exc
        if not 200 <= status < 300:
            raise TranslationError(_http_message(status, raw, secret=secret))
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TranslationError("模型返回的不是 JSON") from exc
        if not isinstance(payload, dict):
            raise TranslationError("模型返回的内容无法读取")
        return payload

    async def _shutdown(self) -> None:
        current = asyncio.current_task()
        tasks = [task for task in asyncio.all_tasks() if task is not current]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._client is not None:
            await self._client.aclose()

    def close(self, *, wait: bool = True) -> None:
        with self._lock:
            if self._closed:
                thread = self._thread
                shutdown = None
            else:
                self._closed = True
                thread = self._thread
                pending = tuple(self._pending)
                shutdown = self._loop
        if shutdown is not None:
            for future in pending:
                future.cancel()
            done = asyncio.run_coroutine_threadsafe(self._shutdown(), shutdown)
            done.add_done_callback(lambda _: shutdown.call_soon_threadsafe(shutdown.stop))
        if wait and thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)


_default_client = PooledHttpClient()
atexit.register(lambda: _default_client.close(wait=False))


def default_http_client() -> PooledHttpClient:
    return _default_client


def _redact_secret(detail: str) -> str:
    detail = re.sub(r"(?i)bearer\s+\S+", "Bearer [redacted]", detail)
    return re.sub(r"\bsk-[A-Za-z0-9_\-]{8,}", "[redacted]", detail)


def _http_message(status: int, detail: str, *, secret: str = "") -> str:
    if secret:
        detail = detail.replace(secret, "[redacted]")
    compact = " ".join(_redact_secret(detail).split())
    if len(compact) > 180:
        compact = compact[:180] + "…"
    return f"模型请求失败（{status}）：{compact}" if compact else f"模型请求失败（{status}）"
