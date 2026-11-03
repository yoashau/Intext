"""Build unified icons from the current tray SVG, without runtime dependencies.

All physical sizes share 1-epx strokes on a 16-epx grid. Rasterize each
size separately using the same theme palette on all application surfaces.
"""
from __future__ import annotations

import math
import re
import struct
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "design" / "tray-icon.svg"
ASSET_DIR = ROOT / "src" / "intext" / "assets"
SIZES = (16, 20, 24, 28, 32, 36, 40, 48, 56, 64, 72, 80, 96, 128, 256)
LIGHT_GLYPH = (32, 32, 32)
DARK_GLYPH = (255, 255, 255)
TRAY_SIZES = tuple(sorted(set(SIZES) | set(range(16, 65))))
TRAY_VARIANTS = (("tray.ico", (0, 0, 0), 228), ("tray-on-dark.ico", DARK_GLYPH, 255))


def segments(size: int, root=None):
    """Flatten the SVG's absolute M/L/Q/Z paths into round-capped segments."""
    if root is None:
        root = ET.parse(SOURCE).getroot()
    guides = tuple(tuple(float(v) for v in root.attrib.get(f"data-snap-{axis}", "").split())
                   for axis in ("x", "y"))
    def hint(value: float, axis: int) -> float:
        # Align straight strokes before flattening, so rounded corners remain
        # continuous. A 1.25px line retains a solid pixel plus edge coverage.
        levels = guides[axis]
        width = size / 16
        if value in levels:
            return (math.floor(value*width - width/2 + .5) + width/2) / width
        return value

    for path in root:
        tokens = iter(re.findall(r"[MLQZ]|-?\d+(?:\.\d+)?", path.attrib["d"]))
        point = start = (0.0, 0.0)
        for command in tokens:
            if command == "Z":
                yield point, start
                point = start
                continue
            end = (hint(float(next(tokens)), 0), hint(float(next(tokens)), 1))
            if command == "M":
                point = start = end
            elif command == "L":
                yield point, end
                point = end
            elif command == "Q":
                control = end
                end = (hint(float(next(tokens)), 0), hint(float(next(tokens)), 1))
                origin = point
                for step in range(1, 33):
                    t = step / 32
                    sample = tuple((1-t)**2*a + 2*(1-t)*t*b + t*t*c
                                   for a, b, c in zip(origin, control, end))
                    yield point, sample
                    point = sample
            else:
                raise ValueError(f"Unsupported SVG command {command}")


def render(size: int, color: tuple[int, int, int], source: Path | None = None, *, opacity: int = 255) -> bytes:
    # Union high-resolution strokes before filtering: intersections must not
    # darken, and transparent pixels must never contain premultiplied RGB.
    samples = 12 if size <= 48 else 4
    side = size * samples
    scale = side / 16
    mask = bytearray(side * side)
    root = ET.parse(source or SOURCE).getroot()
    for path in root:
        single = ET.Element("svg", root.attrib)
        single.append(path)
        lines = [(tuple(v*scale for v in a), tuple(v*scale for v in b))
                 for a, b in segments(size, single)]
        if path.attrib.get("fill", root.attrib.get("fill", "none")) != "none":
            # Our filled shapes are simple closed contours. Fill their union
            # at the same sample resolution as the strokes, without halos.
            for y in range(side):
                intersections = []
                for (ax, ay), (bx, by) in lines:
                    if min(ay, by) <= y+.5 < max(ay, by):
                        intersections.append(ax + (y+.5-ay)*(bx-ax)/(by-ay))
                intersections.sort()
                for left, right in zip(intersections[::2], intersections[1::2]):
                    for x in range(max(0, math.ceil(left-.5)), min(side, math.ceil(right-.5))):
                        mask[y*side+x] = 1
        if path.attrib.get("stroke", root.attrib.get("stroke", "none")) == "none":
            continue
        radius = float(path.attrib.get("stroke-width", root.attrib.get("stroke-width", "1"))) * scale / 2
        for (ax, ay), (bx, by) in lines:
            dx, dy = bx - ax, by - ay
            length = dx*dx + dy*dy
            for y in range(max(0, math.floor(min(ay, by)-radius)), min(side, math.ceil(max(ay, by)+radius))):
                for x in range(max(0, math.floor(min(ax, bx)-radius)), min(side, math.ceil(max(ax, bx)+radius))):
                    t = max(0, min(1, ((x+.5-ax)*dx + (y+.5-ay)*dy)/length)) if length else 0
                    if (x+.5-ax-t*dx)**2 + (y+.5-ay-t*dy)**2 <= radius*radius:
                        mask[y*side+x] = 1
    rgba = bytearray(size*size*4)
    for y in range(size):
        for x in range(size):
            cover = sum(sum(mask[sy*side+x*samples:sy*side+(x+1)*samples])
                        for sy in range(y*samples, (y+1)*samples))
            alpha = round(opacity*cover/(samples*samples))
            offset = (y*size+x)*4
            rgba[offset:offset+4] = bytes((*color, alpha))
    return bytes(rgba)


def write_png(path: Path, width: int, height: int, rgba: bytes) -> None:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)

    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        raw.extend(rgba[y * stride : (y + 1) * stride])
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


def bmp_entry(size: int, rgba: bytes) -> bytes:
    xor = bytearray()
    for y in range(size - 1, -1, -1):
        row = y * size * 4
        for x in range(size):
            red, green, blue, alpha = rgba[row + x * 4 : row + x * 4 + 4]
            xor.extend((blue, green, red, alpha))
    mask_stride = ((size + 31) // 32) * 4
    and_mask = bytes(mask_stride * size)
    header = struct.pack("<IIIHHIIIIII", 40, size, size * 2, 1, 32, 0, len(xor) + len(and_mask), 0, 0, 0, 0)
    return header + bytes(xor) + and_mask


def write_ico(path: Path, images: list[tuple[int, bytes]]) -> None:
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)
    entries = bytearray()
    payload = bytearray()
    offset = 6 + 16 * count
    for size, rgba in images:
        blob = bmp_entry(size, rgba)
        entries.extend(
            struct.pack(
                "<BBBBHHII",
                size if size < 256 else 0,
                size if size < 256 else 0,
                0,
                0,
                1,
                32,
                len(blob),
                offset,
            )
        )
        payload.extend(blob)
        offset += len(blob)
    path.write_bytes(header + bytes(entries) + bytes(payload))


def build() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    for name, color, opacity in TRAY_VARIANTS:
        images = [(size, render(size, color, opacity=opacity)) for size in TRAY_SIZES]
        write_ico(ASSET_DIR / name, images)
        print(f"wrote {name}: {TRAY_SIZES}")
        for size, rgba in images:
            if size in (16, 20, 24, 32, 48):
                preview = ROOT / "design" / "tray-audit"
                preview.mkdir(parents=True, exist_ok=True)
                write_png(preview / f"{name[:-4]}-{size}.png", size, size, rgba)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tray-only", action="store_true", help="leave application icons and page PNGs untouched")
    args = parser.parse_args()
    if args.tray_only:
        build()
    else:
        from make_app_icons import build as build_app_icons
        build_app_icons()
