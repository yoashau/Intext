import ctypes
import os
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor


@unittest.skipUnless(sys.platform == "win32", "requires the native Windows capture window")
class NativeCaptureTests(unittest.TestCase):
    def test_edge_only_rendering_matches_full_antialias_fill_without_seams(self):
        from array import array
        from itertools import chain
        from PIL import Image
        from intext.capture_win import _Surface
        from intext.selection_win import FreehandFill
        from intext.screenshot import freehand_path

        size = (240, 240)
        source = _Surface(size, Image.new("RGB", size, (250, 230, 210)).tobytes("raw", "BGRX"))
        fill = FreehandFill(source)
        try:
            for points in ([(15, 20), (200, 65), (160, 190), (25, 160)],
                           [(20, 20), (210, 40), (80, 90), (210, 210), (40, 180)],
                           [(15, 15), (220, 220), (220, 15), (15, 220)]):
                pixels = Image.new("RGB", size, (120, 110, 100)).tobytes("raw", "BGRX")
                fast, reference = _Surface(size, pixels), _Surface(size, pixels)
                path, graphics = ctypes.c_void_p(), ctypes.c_void_p()
                try:
                    fill.draw(fast.dc, points, (0, 0, *size))
                    vertices, kinds = freehand_path(points)
                    coordinates = array("f", chain.from_iterable(vertices))
                    values = (ctypes.c_float * len(coordinates)).from_buffer(coordinates)
                    types = (ctypes.c_ubyte * len(kinds)).from_buffer_copy(kinds)
                    api = fill.api
                    fill.check(api.GdipCreatePath2(values, types, len(kinds), 0, ctypes.byref(path)))
                    fill.check(api.GdipCreateFromHDC(reference.dc, ctypes.byref(graphics)))
                    fill.check(api.GdipSetSmoothingMode(graphics, 5))
                    fill.check(api.GdipSetPixelOffsetMode(graphics, 4))
                    fill.check(api.GdipSetInterpolationMode(graphics, 5))
                    fill.check(api.GdipFillPath(graphics, fill.brush, path))
                    api.GdipDeleteGraphics(graphics)
                    graphics.value = None
                    self.assertEqual(fast.to_image().tobytes(), reference.to_image().tobytes())
                finally:
                    if graphics:
                        fill.api.GdipDeleteGraphics(graphics)
                    if path:
                        fill.api.GdipDeletePath(path)
                    reference.close()
                    fast.close()
        finally:
            fill.close()
            source.close()

    def test_smooth_preview_and_export_use_matching_coverage_and_preserve_image_detail(self):
        from PIL import Image
        from intext.capture_win import _Surface
        from intext.selection_win import FreehandFill
        from intext.screenshot import lasso_selection, mask_screenshot

        size = (220, 220)
        points = [(15, 20), (200, 65), (160, 190), (25, 160)]
        source = _Surface(size, Image.new("RGB", size, "white").tobytes("raw", "BGRX"))
        frame = _Surface(size, Image.new("RGB", size, "black").tobytes("raw", "BGRX"))
        fill = FreehandFill(source)
        try:
            fill.draw(frame.dc, points, (0, 0, *size))
            selection = lasso_selection(points)
            x, y, w, h = selection.rect
            preview = frame.to_image().crop((x, y, x+w, y+h))
            output = mask_screenshot(Image.new("RGB", size, "black"), selection).image()
            error = max(abs(a[0]+b[0]-255) for a, b in zip(preview.getdata(), output.getdata()))
            self.assertLessEqual(error, 4, "preview and export must cover the same subpixels")
        finally:
            fill.close()
            frame.close()
            source.close()
        image = Image.new("RGB", size)
        for y in range(size[1]):
            for x in range(size[0]):
                image.putpixel((x, y), (x, y, 255 if (x+y) % 2 else 0))
        selection = lasso_selection([(10, 10), (210, 10), (210, 210), (10, 210)])
        output = mask_screenshot(image, selection).image()
        self.assertEqual(output.crop((10, 10, 190, 190)).tobytes(), image.crop((20, 20, 200, 200)).tobytes())

    def test_native_frozen_surface_is_cropped_in_physical_screen_coordinates(self):
        from unittest.mock import patch
        from PIL import Image
        from intext import capture_win
        from intext.screenshot import rectangle_selection

        rect = (-120, -40, 80, 60)
        image = Image.new("RGB", rect[2:], (30, 40, 50))
        for y in range(20, 41):
            for x in range(10, 41):
                image.putpixel((x, y), (x, y, 200))
        frozen = capture_win._Surface(image.size, image.tobytes("raw", "BGRX"))
        selection = rectangle_selection((10, 20), (40, 40), rect[:2])
        with patch.object(capture_win, "virtual_screen", return_value=rect), \
             patch.object(capture_win, "_screen_surface", return_value=frozen), \
             patch.object(capture_win, "select_region", return_value=selection):
            shot = capture_win.capture_shot()
        self.assertEqual(shot.selection.rect, (-110, -20, 31, 21))
        self.assertEqual(shot.image().getpixel((0, 0)), (10, 20, 200))
        self.assertEqual(shot.image().getpixel((30, 20)), (40, 40, 200))
        self.assertIsNone(frozen.dc)

    def test_hint_edges_composite_without_dark_halos_at_common_dpi_scales(self):
        from ctypes import wintypes
        from PIL import Image
        from intext.capture_win import _hint_image, _Surface

        blend = ctypes.WinDLL("msimg32", use_last_error=True).AlphaBlend
        blend.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                          wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
        blend.restype = wintypes.BOOL
        gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        gdi.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        gdi.GetPixel.restype = wintypes.COLORREF
        for scale, light in ((1.0, True), (1.25, False), (1.5, True), (2.0, False)):
            with self.subTest(scale=scale, light=light):
                hint, premultiplied = _hint_image(scale, light)
                alpha = hint.getchannel("A")
                self.assertTrue(any(0 < value < 255 for value in alpha.getdata()), "hint edges must be antialiased")
                background = Image.new("RGB", hint.size, (171, 195, 219))
                expected = Image.alpha_composite(background.convert("RGBA"), hint).convert("RGB")
                destination = _Surface(hint.size, background.tobytes("raw", "BGRX"))
                source = _Surface(hint.size, premultiplied)
                try:
                    self.assertTrue(blend(destination.dc, 0, 0, *hint.size, source.dc, 0, 0, *hint.size, 0x01FF0000))
                    for y in range(0, hint.height, 3):
                        for x in range(0, hint.width, 3):
                            color = gdi.GetPixel(destination.dc, x, y)
                            actual = (color & 255, color >> 8 & 255, color >> 16 & 255)
                            self.assertTrue(all(abs(a - b) <= 2 for a, b in zip(actual, expected.getpixel((x, y)))),
                                            f"incorrect alpha blend at {x}, {y}: {actual}")
                finally:
                    source.close()
                    destination.close()

    def test_rectangles_freehand_and_cancel_reuse_the_worker_without_leaking_windows(self):
        from ctypes import wintypes
        from PIL import Image
        from intext.capture_win import select_region

        user = ctypes.WinDLL("user32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

        def find():
            found = []
            def visit(hwnd, _):
                pid = wintypes.DWORD()
                user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                name = ctypes.create_unicode_buffer(128)
                user.GetClassNameW(hwnd, name, len(name))
                if pid.value == os.getpid() and name.value.startswith("IntextCapture"):
                    found.append(hwnd)
                return True
            user.EnumWindows(callback_type(visit), 0)
            return found[0] if found else None

        cases = (
            ([(40, 40), (240, 140)], None, (90, 90, 201, 101)),
            ([(240, 140), (40, 40)], None, (90, 90, 201, 101)),
            ([(40, 40), (240, 40), (220, 140), (40, 140)], 0, (90, 90, 201, 101)),
            ([(40, 40), (240, 40), (220, 140), (40, 140)], 2, (90, 90, 201, 101)),
            (None, None, None),
            ([(40, 40), (240, 140)], None, (90, 90, 201, 101)),
        )
        with ThreadPoolExecutor(max_workers=1) as worker:
            for points, control_at, expected in cases:
                future = worker.submit(select_region, Image.new("RGB", (500, 300), "white"), (50, 50, 500, 300))
                deadline = time.monotonic() + 5
                hwnd = None
                while not hwnd and time.monotonic() < deadline:
                    hwnd = find()
                    time.sleep(0.01)
                self.assertIsNotNone(hwnd)
                try:
                    if points is None:
                        user.PostMessageW(hwnd, 0x0100, 0x1B, 0)
                        self.assertIsNone(future.result(timeout=5))
                    else:
                        for index, (x, y) in enumerate(points):
                            control = control_at is not None and index >= control_at
                            user.PostMessageW(hwnd, 0x0201 if index == 0 else 0x0200, 1 | (8 if control else 0), x | y << 16)
                        x, y = points[-1]
                        # Releasing Ctrl before the mouse does not change a freehand stroke into a rectangle.
                        user.PostMessageW(hwnd, 0x0202, 0, x | y << 16)
                        selection = future.result(timeout=5)
                        self.assertEqual(selection.rect, expected)
                        self.assertEqual(len(selection.points), 4)
                        if control_at is not None:
                            self.assertEqual(selection.points[2], (180, 100))
                finally:
                    if find():
                        user.PostMessageW(hwnd, 0x0100, 0x1B, 0)
                self.assertIsNone(find())

    def test_drag_frames_do_not_expose_the_dimmed_intermediate_pass(self):
        from ctypes import wintypes
        from PIL import Image
        from intext.capture_win import select_region

        user = ctypes.WinDLL("user32", use_last_error=True)
        gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user.GetDC.argtypes = [wintypes.HWND]
        user.GetDC.restype = wintypes.HDC
        user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        gdi.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        gdi.GetPixel.restype = wintypes.COLORREF

        def find():
            found = []
            def visit(hwnd, _):
                pid = wintypes.DWORD()
                user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                name = ctypes.create_unicode_buffer(128)
                user.GetClassNameW(hwnd, name, len(name))
                if pid.value == os.getpid() and name.value.startswith("IntextCapture"):
                    found.append(hwnd)
                return True
            user.EnumWindows(callback_type(visit), 0)
            return found[0] if found else None

        with ThreadPoolExecutor(max_workers=1) as worker:
            future = worker.submit(select_region, Image.new("RGB", (500, 300), (250, 230, 210)), (50, 50, 500, 300))
            deadline, hwnd = time.monotonic() + 5, None
            while not hwnd and time.monotonic() < deadline:
                hwnd = find()
                time.sleep(0.01)
            self.assertTrue(hwnd)
            try:
                user.PostMessageW(hwnd, 0x0201, 1, 20 | 20 << 16)
                user.PostMessageW(hwnd, 0x0200, 1, 130 | 130 << 16)
                dc = user.GetDC(hwnd)
                self.assertTrue(dc)
                try:
                    expected = 250 | 230 << 8 | 210 << 16
                    deadline = time.monotonic() + 2
                    while gdi.GetPixel(dc, 60, 60) != expected and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertEqual(gdi.GetPixel(dc, 60, 60), expected)
                    # The selection boundary uses only original/dimmed pixels.
                    dimmed = gdi.GetPixel(dc, 10, 10)
                    self.assertNotEqual(dimmed, expected)
                    for x, y in ((80, 20), (80, 129), (20, 80), (129, 80)):
                        self.assertEqual(gdi.GetPixel(dc, x, y), expected)
                    for x, y in ((80, 19), (80, 130), (19, 80), (130, 80)):
                        self.assertEqual(gdi.GetPixel(dc, x, y), dimmed)
                    samples = []
                    for index in range(80):
                        x = 140 + index % 120
                        user.PostMessageW(hwnd, 0x0200, 1, x | 160 << 16)
                        samples.append(gdi.GetPixel(dc, 60, 60))
                        time.sleep(0.002)
                    self.assertTrue(all(color == expected for color in samples), "an intermediate dimmed frame was visible")
                    # Shrinking must restore the old highlighted area.
                    user.PostMessageW(hwnd, 0x0200, 1, 100 | 100 << 16)
                    deadline = time.monotonic() + 2
                    while gdi.GetPixel(dc, 120, 120) == expected and time.monotonic() < deadline:
                        time.sleep(0.005)
                    self.assertNotEqual(gdi.GetPixel(dc, 120, 120), expected)
                    self.assertEqual(gdi.GetPixel(dc, 60, 60), expected)
                    self.assertEqual(gdi.GetPixel(dc, 80, 130), dimmed)
                finally:
                    user.ReleaseDC(hwnd, dc)
            finally:
                user.PostMessageW(hwnd, 0x0100, 0x1B, 0)
                future.result(timeout=5)
