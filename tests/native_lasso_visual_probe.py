"""Review real Windows lasso captures and lossless 8x edge details.

All visible content is synthetic. Only the owned selection window is captured.
Run with Windows Python; an optional --before points to a historical module.
"""
from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import math
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--before', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'src'))
    from PIL import Image, ImageDraw
    from intext.platform_win import enable_dpi_awareness
    enable_dpi_awareness()
    from intext import capture_win
    modules = [('after', capture_win)]
    if args.before:
        spec = importlib.util.spec_from_file_location('intext._hard_edge_reference', args.before)
        previous_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(previous_module)
        modules.insert(0, ('before', previous_module))
    output = root / 'design/lasso-edge-review'
    output.mkdir(parents=True, exist_ok=True)
    user = capture_win.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.GetForegroundWindow.restype = wintypes.HWND
    user.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    user.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
    user.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    previous = user.GetForegroundWindow()
    cursor = wintypes.POINT()
    user.GetCursorPos(ctypes.byref(cursor))

    def find():
        found = []
        def visit(hwnd, _):
            pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            name = ctypes.create_unicode_buffer(128)
            user.GetClassNameW(hwnd, name, len(name))
            if pid.value == os.getpid() and name.value.startswith('IntextCapture'):
                found.append(hwnd)
            return True
        user.EnumWindows(callback_type(visit), 0)
        return found[0] if found else None

    circle = [(round(420+250*math.cos(a)), round(350+200*math.sin(a)))
              for a in (2*math.pi*i/240 for i in range(241))]
    corners = [(170, 180), (650, 240), (480, 285), (650, 530), (330, 490), (190, 550), (170, 180)]
    paths = {'curve': circle, 'corners': corners}
    report = {'passed': False, 'cases': []}
    screenshots = {}
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            for version, module in modules:
                for theme, background in [('light', (250, 230, 210)), ('dark', (80, 85, 95))]:
                    for name, points in paths.items():
                        rect = module.virtual_screen()
                        synthetic = Image.new('RGB', rect[2:], background)
                        times = []
                        end_paint = module.user32.EndPaint
                        def end(*values):
                            result = end_paint(*values)
                            times.append(time.perf_counter())
                            return result
                        module.user32.EndPaint = end
                        future = pool.submit(module.select_region, synthetic, rect)
                        hwnd = None
                        deadline = time.monotonic()+5
                        while not hwnd and time.monotonic()<deadline:
                            hwnd = find()
                            time.sleep(.002)
                        assert hwnd, 'Capture window did not open'
                        try:
                            user.SetCursorPos(rect[0]+points[0][0], rect[1]+points[0][1])
                            time.sleep(.02)
                            user.keybd_event(0x11, 0, 0, 0)
                            user.mouse_event(0x0002, 0, 0, 0, 0)
                            for i, (x, y) in enumerate(points):
                                user.SetCursorPos(rect[0]+x, rect[1]+y)
                                time.sleep(.005)
                            time.sleep(.06)
                            assert find() == hwnd and user.GetForegroundWindow() == hwnd, 'Capture lost focus'
                            # Give the compositor the complete last frame before reading.
                            ctypes.WinDLL('dwmapi').DwmFlush()
                            image = module.screen_image((rect[0]+100, rect[1]+120, 650, 500))
                            intervals = sorted((b-a)*1000 for a, b in zip(times[2:], times[3:]))
                            colors = image.getcolors(image.width*image.height)
                            count = len(colors) if colors is not None else 0
                            if name == 'curve':
                                # Validate the full interior and exterior, not just
                                # the presence of blended pixels along an edge.
                                dimmed = image.getpixel((0, 0))
                                for y in range(150, 570, 20):
                                    for x in range(150, 690, 20):
                                        radius = ((x-420)/250)**2 + ((y-350)/200)**2
                                        pixel = image.getpixel((x-100, y-120))
                                        if radius < .8:
                                            assert pixel == background, ('interior hole', version, x, y, pixel)
                                        elif radius > 1.2:
                                            assert pixel == dimmed, ('exterior leak', version, x, y, pixel)
                            if version == 'after':
                                assert count > 10, 'Freehand edge still has binary coverage'
                            image.save(output / f'{version}-{theme}-{name}.png')
                            screenshots[(version, theme, name)] = image
                            report['cases'].append({'version': version, 'theme': theme, 'path': name,
                                'colors': count, 'paintMedianMs': round(statistics.median(intervals), 2) if intervals else None,
                                'paintP95Ms': round(intervals[int((len(intervals)-1)*.95)], 2) if intervals else None})
                        finally:
                            user.mouse_event(0x0004, 0, 0, 0, 0)
                            user.keybd_event(0x11, 0, 0x0002, 0)
                            future.result(timeout=5)
                            module.user32.EndPaint = end_paint
        if args.before:
            # Nearest-neighbor enlargement exposes each actual pixel; no smoothing
            # is applied to these diagnostic images.
            rows = [('slope', 'light', 'curve', (390, 35, 454, 67)),
                    ('curve', 'light', 'curve', (552, 178, 616, 210)),
                    ('corner', 'light', 'corners', (52, 44, 116, 76)),
                    ('closure', 'dark', 'curve', (552, 214, 616, 246))]
            montage = Image.new('RGB', (1048, len(rows)*280), '#eeeeee')
            draw = ImageDraw.Draw(montage)
            for row, (label, theme, name, box) in enumerate(rows):
                for column, version in enumerate(('before', 'after')):
                    detail = screenshots[(version, theme, name)].crop(box).resize((512, 256), Image.Resampling.NEAREST)
                    x, y = column*524, row*280
                    draw.text((x+8, y+4), f'{label} / {version} / 8x actual pixels', fill='black')
                    montage.paste(detail, (x+6, y+24))
            montage.save(output / 'details-8x.png')
        report['passed'] = True
    finally:
        if previous:
            user.SetForegroundWindow(previous)
        user.SetCursorPos(cursor.x, cursor.y)
        (root / 'build/lasso-visual-validation.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
