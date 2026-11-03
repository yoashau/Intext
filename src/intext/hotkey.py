"""Hotkey text shared by settings and the Windows registrar.

Sizes and shortcuts stay in device-independent form. Windows DPI scaling
changes physical size; this module does not.
"""

from __future__ import annotations

import re

_MODIFIERS = ("ctrl", "alt", "shift", "win")
_KEY = re.compile(r"[a-z0-9]|f(?:[1-9]|1[0-2])")
_LABELS = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}


def canonical_hotkey(spec: str) -> str:
    parts = [part.strip().lower() for part in str(spec).split("+") if part.strip()]
    if len(parts) < 2:
        raise ValueError("hotkey needs a modifier")
    key = parts[-1]
    modifiers = parts[:-1]
    if key in _MODIFIERS or not _KEY.fullmatch(key):
        raise ValueError("unsupported hotkey key")
    if any(part not in _MODIFIERS for part in modifiers):
        raise ValueError("unsupported modifier")
    if len(modifiers) != len(set(modifiers)):
        raise ValueError("duplicate modifier")
    ordered = [part for part in _MODIFIERS if part in modifiers]
    if not ordered:
        raise ValueError("hotkey needs a modifier")
    return "+".join(ordered + [key])


def resolve_hotkey_change(
    current_select: str,
    current_shot: str,
    requested_select: str,
    requested_shot: str,
) -> tuple[str, str, str, str]:
    """Return the shortcuts to keep and any reason they were rejected.

    Invalid or duplicate requests stay on the previous shortcut. The caller
    shows the rejection on the box the user just edited.
    """
    select_error = ""
    shot_error = ""
    try:
        select = canonical_hotkey(requested_select)
    except ValueError:
        select = current_select
        select_error = "无效"
    try:
        shot = canonical_hotkey(requested_shot)
    except ValueError:
        shot = current_shot
        shot_error = "无效"
    if select == shot:
        if select != current_select and not select_error:
            select_error = "重复"
        if shot != current_shot and not shot_error:
            shot_error = "重复"
        if not select_error and not shot_error:
            select_error = "重复"
            shot_error = "重复"
        return current_select, current_shot, select_error, shot_error
    if select_error or shot_error:
        return select, shot, select_error, shot_error
    return select, shot, "", ""


def registration_failure(code: int) -> str:
    """Short reason for a failed RegisterHotKey call.

    1409 is ERROR_HOTKEY_ALREADY_REGISTERED. Other codes stay generic so the
    settings box does not claim the shortcut is taken when Windows said otherwise.
    """
    if int(code) == 1409:
        return "已被占用"
    return "注册失败"


def display_hotkey(spec: str) -> str:
    try:
        spec = canonical_hotkey(spec)
    except ValueError:
        spec = str(spec or "")
    return " + ".join(_LABELS.get(part, part.upper()) for part in spec.split("+") if part)
