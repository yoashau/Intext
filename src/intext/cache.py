"""Small two-level translation cache.

Memory serves repeated selections in the same session. SQLite keeps them
across restarts. Lookups stay on the hot path and do not touch the network.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from typing import Callable


class LoadingCache:
    """Share pending work; an explicit refresh supersedes older cache writes."""

    def __init__(self) -> None:
        self._pending: dict[str, Future[str]] = {}
        self._pending_lock = threading.Lock()

    def peek(self, key: str) -> str | None:
        with self._pending_lock:
            if key in self._pending:
                return None
            return self.get(key)

    def get_or_load(
        self, key: str, load: Callable[[], str], *, refresh: bool = False
    ) -> tuple[str, bool]:
        with self._pending_lock:
            pending = None if refresh else self._pending.get(key)
            if pending is None:
                if not refresh:
                    hit = self.get(key)
                    if hit is not None and hit.strip():
                        return hit, True
                pending = Future()
                self._pending[key] = pending
                owner = True
            else:
                owner = False
        if not owner:
            return pending.result(), True
        try:
            result = load()
            with self._pending_lock:
                if self._pending.get(key) is pending:
                    self.put(key, result)
                    del self._pending[key]
            pending.set_result(result)
            return result, False
        except BaseException as exc:
            with self._pending_lock:
                if self._pending.get(key) is pending:
                    del self._pending[key]
            pending.set_exception(exc)
            raise


class MemoryCache(LoadingCache):
    def __init__(self, limit: int = 256) -> None:
        super().__init__()
        self._limit = limit
        self._items: dict[str, str] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            value = self._items.get(key)
            if value is None:
                return None
            self._items.pop(key)
            self._items[key] = value
            return value

    def put(self, key: str, value: str) -> None:
        with self._lock:
            self._items.pop(key, None)
            self._items[key] = value
            while len(self._items) > self._limit:
                self._items.pop(next(iter(self._items)))


class SqliteCache(LoadingCache):
    def __init__(self, path: Path, limit: int = 2000) -> None:
        super().__init__()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._limit = max(1, int(limit))
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS translations (
                key TEXT PRIMARY KEY,
                result TEXT NOT NULL,
                created REAL NOT NULL
            )
            """
        )
        self._db.commit()

    def get(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT result FROM translations WHERE key = ?",
                (key,),
            ).fetchone()
        return None if row is None else row[0]

    def put(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute(
                """
                INSERT INTO translations(key, result, created)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    result = excluded.result,
                    created = excluded.created
                """,
                (key, value, time.time()),
            )
            self._db.execute(
                """
                DELETE FROM translations
                WHERE key != ?
                AND key NOT IN (
                    SELECT key FROM translations
                    WHERE key != ?
                    ORDER BY created DESC
                    LIMIT ?
                )
                """,
                (key, key, max(0, self._limit - 1)),
            )
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()


class TieredCache(LoadingCache):
    def __init__(self, memory: MemoryCache, disk: SqliteCache) -> None:
        super().__init__()
        self.memory = memory
        self.disk = disk

    def get(self, key: str) -> str | None:
        hit = self.memory.get(key)
        if hit is not None:
            return hit
        hit = self.disk.get(key)
        if hit is not None:
            self.memory.put(key, hit)
        return hit

    def put(self, key: str, value: str) -> None:
        self.memory.put(key, value)
        self.disk.put(key, value)
