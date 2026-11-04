"""User settings. Optional request fields stay disabled until enabled."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .fields import default_field_state, normalize_field_state


@dataclass
class Settings:
    endpoint: str = "https://api.openai.com/v1/chat/completions"
    api_key: str = ""
    model: str = ""
    source: str = "auto"
    target: str = "zh"
    fields: dict = field(default_factory=default_field_state)
    hotkey: str = "ctrl+alt+q"
    shot_hotkey: str = "ctrl+alt+e"
    shot_input: str = "ocr"
    shot_display: str = "popup"
    window_width: int = 0
    window_height: int = 0
    pinned: bool = False

    def to_dict(self) -> dict:
        data = {
            "endpoint": self.endpoint,
            "api_key": self.api_key,
            "model": self.model,
            "source": self.source,
            "target": self.target,
            "fields": self.fields,
            "hotkey": self.hotkey,
            "shot_hotkey": self.shot_hotkey,
            "shot_input": self.shot_input,
            "shot_display": self.shot_display,
            "pinned": bool(self.pinned),
        }
        if self.window_width > 0 and self.window_height > 0:
            data["window_width"] = self.window_width
            data["window_height"] = self.window_height
        return data


def config_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Intext"
    return Path.home() / ".config" / "intext"


def config_path() -> Path:
    return config_dir() / "config.json"



def _saved_hotkey(value: object, default: str) -> str:
    text = str(value or "").strip().lower()
    return text or default


def _positive(value: object) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def load_settings(path: Path | None = None) -> Settings:
    path = path or config_path()
    if not path.exists():
        settings = Settings()
        save_settings(settings, path)
        return settings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log_error(f"config unreadable: {exc}")
        backup = path.with_name("config.json.bak")
        try:
            if path.exists():
                path.replace(backup)
        except OSError:
            pass
        return Settings()
    if not isinstance(raw, dict):
        return Settings()
    settings = Settings(
        endpoint=str(raw.get("endpoint") or Settings.endpoint),
        api_key=str(raw.get("api_key") or ""),
        model=str(raw.get("model") or ""),
        source=str(raw.get("source") or "auto"),
        target=str(raw.get("target") or "zh"),
        fields=normalize_field_state(raw.get("fields")),
        hotkey=_saved_hotkey(raw.get("hotkey"), Settings.hotkey),
        shot_hotkey=_saved_hotkey(raw.get("shot_hotkey"), Settings.shot_hotkey),
        shot_input="image" if raw.get("shot_input") == "image" else "ocr",
        shot_display="overlay" if raw.get("shot_display") == "overlay" else "popup",
        window_width=_positive(raw.get("window_width")),
        window_height=_positive(raw.get("window_height")),
        pinned=bool(raw.get("pinned")),
    )
    if str(raw.get("hotkey") or "").strip().lower() != settings.hotkey or str(raw.get("shot_hotkey") or "").strip().lower() != settings.shot_hotkey:
        save_settings(settings, path)
    return settings


def save_settings(settings: Settings, path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def log_error(message: str) -> None:
    try:
        path = config_dir() / "intext.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")
    except OSError:
        return
