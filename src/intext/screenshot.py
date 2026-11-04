"""Screenshot data and geometry, independent of the desktop capture window."""

from __future__ import annotations

import base64
import io
import math
import sys
from dataclasses import dataclass

Point = tuple[int, int]


@dataclass(frozen=True)
class Selection:
    rect: tuple[int, int, int, int]
    points: tuple[Point, ...]  # Relative to the bounding rectangle, in physical pixels.
    freehand: bool = False


@dataclass(frozen=True)
class Screenshot:
    png: bytes
    selection: Selection

    @property
    def data_url(self) -> str:
        return "data:image/png;base64," + base64.b64encode(self.png).decode("ascii")

    def image(self):
        from PIL import Image

        with Image.open(io.BytesIO(self.png)) as image:
            return image.convert("RGB")


@dataclass(frozen=True)
class TextRegion:
    id: int
    text: str
    box: tuple[tuple[float, float], ...]
    confidence: float = 1.0

    @property
    def rect(self) -> tuple[float, float, float, float]:
        xs, ys = zip(*self.box)
        return min(xs), min(ys), max(xs), max(ys)


@dataclass(frozen=True)
class OcrPage:
    regions: tuple[TextRegion, ...]
    engine: str = "PP-OCRv5"

    @property
    def text(self) -> str:
        # Keep individual lines and the detector's reading order. Joining the
        # whole page with spaces loses lists, code indentation and paragraphs.
        return "\n".join(region.text for region in self.regions)


def lasso_selection(points: list[Point], base: Point = (0, 0)) -> Selection | None:
    points = [point for i, point in enumerate(points) if i == 0 or point != points[i-1]]
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    if len(points) < 3:
        return None
    xs, ys = zip(*points)
    left, top, right, bottom = min(xs), min(ys), max(xs), max(ys)
    twice_area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1])))
    if right - left < 8 or bottom - top < 8 or twice_area < 128:
        return None
    return Selection(
        (left + base[0], top + base[1], right - left + 1, bottom - top + 1),
        tuple((x - left, y - top) for x, y in points),
        freehand=True,
    )


def freehand_path(points):
    """A closed cubic path with bounded rounding of the recorded mouse trace.

    Curves stay inside the raw points' bounds. Short mouse segments blend at
    their midpoints. At sharp turns, limit the curve's midpoint displacement
    from the recorded corner to 1.5 physical pixels.
    GDI+ path types: Start=0, Line=1, Bezier=3, CloseSubpath=0x80.
    """
    points = [p for i, p in enumerate(points) if i == 0 or p != points[i-1]]
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    if len(points) < 3:
        return (), b""
    corners = []
    for i, (x, y) in enumerate(points):
        previous, following = points[i-1], points[(i+1) % len(points)]
        before = math.hypot(previous[0]-x, previous[1]-y)
        after = math.hypot(following[0]-x, following[1]-y)
        turn = math.hypot((previous[0]-x)/before + (following[0]-x)/after,
                          (previous[1]-y)/before + (following[1]-y)/after)
        cut = min(before / 2, after / 2, 6 / max(turn, 1e-9))
        start = (x + (previous[0]-x)*cut/before, y + (previous[1]-y)*cut/before)
        end = (x + (following[0]-x)*cut/after, y + (following[1]-y)*cut/after)
        # Convert a quadratic corner to an equivalent cubic Bezier.
        c1 = (start[0] + (x-start[0])*2/3, start[1] + (y-start[1])*2/3)
        c2 = (end[0] + (x-end[0])*2/3, end[1] + (y-end[1])*2/3)
        corners.append((start, c1, c2, end))
    path, kinds = [corners[0][0]], bytearray([0])
    for i, (_, c1, c2, end) in enumerate(corners):
        path.extend((c1, c2, end, corners[(i+1) % len(corners)][0]))
        kinds.extend((3, 3, 3, 1))
    kinds[-1] |= 0x80
    return tuple(path), bytes(kinds)


def _freehand_mask(size, points):
    """Portable supersampled fallback; Windows uses the live native renderer."""
    from PIL import Image, ImageDraw

    path, _ = freehand_path(points)
    if not path:
        return Image.new("L", size)
    polygon = [path[0]]
    for i in range(1, len(path), 4):
        p0, p1, p2, p3 = polygon[-1], path[i], path[i+1], path[i+2]
        for step in range(1, 13):
            t = step / 12
            polygon.append(tuple((1-t)**3*p0[d] + 3*(1-t)**2*t*p1[d] + 3*(1-t)*t*t*p2[d] + t**3*p3[d] for d in (0, 1)))
        polygon.append(path[i+3])
    factor = 4
    mask = Image.new("L", (size[0]*factor, size[1]*factor))
    ImageDraw.Draw(mask).polygon([(round(x*factor), round(y*factor)) for x, y in polygon], fill=255)
    return mask.resize(size, Image.Resampling.LANCZOS)


def rectangle_selection(start: Point, end: Point, base: Point = (0, 0)) -> Selection | None:
    left, right = sorted((start[0], end[0]))
    top, bottom = sorted((start[1], end[1]))
    if right - left < 8 or bottom - top < 8:
        return None
    width, height = right - left, bottom - top
    return Selection((left + base[0], top + base[1], width + 1, height + 1),
                     ((0, 0), (width, 0), (width, height), (0, height)))


def mask_screenshot(image, selection: Selection, base: Point = (0, 0)) -> Screenshot:
    from PIL import Image, ImageDraw

    x, y, width, height = selection.rect
    crop = image.crop((x - base[0], y - base[1], x - base[0] + width, y - base[1] + height)).convert("RGB")
    if selection.freehand and sys.platform == "win32":
        from .capture_win import _mask_freehand

        crop = _mask_freehand(crop, selection.points)
    else:
        if selection.freehand:
            mask = _freehand_mask(crop.size, selection.points)
        else:
            mask = Image.new("L", crop.size)
            ImageDraw.Draw(mask).polygon(selection.points, fill=255)
        # Remove outside RGB values, rather than merely hiding them with alpha.
        crop = Image.composite(crop, Image.new("RGB", crop.size, "white"), mask)
    output = io.BytesIO()
    crop.save(output, format="PNG")
    return Screenshot(output.getvalue(), selection)
