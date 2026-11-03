"""Settings window size in logical pixels.

The preferred size is a design constant, not a measurement of one monitor.
A short work area caps the height so the window stays a panel. A size the
user has already chosen is kept, and only clamped to the current work area.
"""

from __future__ import annotations

PREFERRED_SETTINGS = (480, 600)
MINIMUM_SETTINGS = (360, 380)
SETTINGS_MARGIN = 28
SETTINGS_WIDTH_FRACTION = 0.94
SETTINGS_HEIGHT_FRACTION = 0.52


def settings_size(work: tuple[int, int], saved: tuple[int, int] | None = None) -> tuple[int, int]:
    if saved and saved[0] > 0 and saved[1] > 0:
        return clamp_size(saved, work)
    return clamp_size(
        PREFERRED_SETTINGS,
        work,
        width_fraction=SETTINGS_WIDTH_FRACTION,
        height_fraction=SETTINGS_HEIGHT_FRACTION,
    )


def clamp_size(
    size: tuple[int, int],
    work: tuple[int, int],
    *,
    width_fraction: float = 1.0,
    height_fraction: float = 1.0,
    minimum: tuple[int, int] = MINIMUM_SETTINGS,
    margin: int = SETTINGS_MARGIN,
) -> tuple[int, int]:
    work_w = max(1, int(work[0]))
    work_h = max(1, int(work[1]))
    avail_w = max(1, work_w - margin)
    avail_h = max(1, work_h - margin)
    cap_w = min(avail_w, max(1, int(work_w * width_fraction)))
    cap_h = min(avail_h, max(1, int(work_h * height_fraction)))
    width = min(max(1, int(size[0])), cap_w)
    height = min(max(1, int(size[1])), cap_h)
    if minimum[0] <= avail_w:
        width = max(width, min(minimum[0], cap_w))
    if minimum[1] <= avail_h:
        height = max(height, min(minimum[1], cap_h))
    return width, height


def should_dismiss_popup(point: tuple[int, int], rect: tuple[int, int, int, int] | None, *, pinned: bool, visible: bool) -> bool:
    """Outside clicks close an unpinned, visible translation window."""
    if pinned or not visible or rect is None:
        return False
    left, top, right, bottom = rect
    if right <= left or bottom <= top:
        return False
    x, y = point
    return x < left or y < top or x >= right or y >= bottom


def tray_menu_position(point: tuple[int, int], size: tuple[int, int], work: tuple[int, int, int, int]) -> tuple[int, int]:
    x, y = point
    width, height = size
    left, top, right, bottom = work
    gap = 6
    preferred = x + gap
    if preferred + width > right:
        preferred = x - width - gap
    return min(max(preferred, left), max(left, right - width)), min(max(y - height, top), max(top, bottom - height))
