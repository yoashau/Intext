"""Tray assets and the actual Windows HICON path; no desktop theme changes."""
import ctypes
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ASSETS = Path(__file__).resolve().parents[1] / "src" / "intext" / "assets"


class TrayAssetsTests(unittest.TestCase):
    def test_application_icons_match_current_tray(self):
        for app, tray in (("intext.ico", "tray.ico"), ("intext-on-dark.ico", "tray-on-dark.ico")):
            with self.subTest(theme=tray):
                self.assertEqual((ASSETS / app).read_bytes(), (ASSETS / tray).read_bytes())

    def test_native_sizes_and_light_foreground(self):
        for name, opacity in (("tray.ico", 228), ("tray-on-dark.ico", 255)):
            data = (ASSETS / name).read_bytes()
            reserved, kind, count = struct.unpack_from("<HHH", data)
            self.assertEqual((reserved, kind), (0, 1))
            sizes = set()
            for i in range(count):
                width, height, _, _, planes, depth, length, offset = struct.unpack_from("<BBBBHHII", data, 6 + i * 16)
                size = width or 256
                sizes.add(size)
                self.assertEqual(height or 256, size)
                self.assertEqual((planes, depth), (1, 32))
                self.assertLessEqual(offset + length, len(data))
                pixels = data[offset + 40:offset + 40 + size * size * 4]
                self.assertEqual(max(pixels[3::4]), opacity)
                self.assertEqual(min(pixels[3::4]), 0)
                if name == "tray.ico":
                    self.assertTrue(all(value == 0 for c in range(3) for value in pixels[c::4]))
            self.assertTrue(set(range(16, 65)) <= sizes)


@unittest.skipUnless(sys.platform == "win32", "requires Windows HICON and GDI")
class NativeTrayTests(unittest.TestCase):
    @staticmethod
    def pixels(icon, size):
        from intext import tray_icon as tray
        info = tray.ICONINFO()
        if not tray.user32.GetIconInfo(icon, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        dc = tray.user32.GetDC(None)
        try:
            header = tray.BITMAPINFOHEADER()
            header.biSize = ctypes.sizeof(header)
            header.biWidth, header.biHeight = size, -size
            header.biPlanes, header.biBitCount = 1, 32
            pixels = (ctypes.c_ubyte * (size * size * 4))()
            if tray.gdi32.GetDIBits(dc, info.hbmColor, 0, size, pixels, ctypes.byref(header), 0) != size:
                raise ctypes.WinError(ctypes.get_last_error())
            return bytes(pixels)
        finally:
            tray.user32.ReleaseDC(None, dc)
            tray.gdi32.DeleteObject(info.hbmColor)
            tray.gdi32.DeleteObject(info.hbmMask)

    def test_native_alpha_contrast_color_and_coverage(self):
        from intext import tray_icon as tray
        from intext.platform_win import destroy_icon, load_icon
        for size in (16, 18, 20, 24, 28, 32, 36, 40, 48, 56, 64):
            mask = load_icon(str(ASSETS / "tray-on-dark.ico"), size)
            self.assertTrue(mask)
            try:
                coverage = self.pixels(mask, size)[3::4]
            finally:
                destroy_icon(mask)
            for contrast in (None, (255, 255, 255), (0, 0, 0), (255, 255, 0), (24, 200, 130)):
                with self.subTest(size=size, contrast=contrast), patch.object(tray, "_contrast_color", return_value=contrast):
                    icon = tray.load_tray_icon(str(ASSETS / "tray.ico"), size)
                    self.assertTrue(icon)
                    try:
                        pixels = self.pixels(icon, size)
                        alpha = pixels[3::4]
                        self.assertEqual(min(alpha), 0)
                        self.assertEqual(max(alpha), 228 if contrast is None else 255)
                        if contrast is not None:
                            self.assertEqual(alpha, coverage)
                        else:
                            self.assertTrue(all(abs(a - round(c * 228 / 255)) <= 1 for a, c in zip(alpha, coverage)))
                        color = contrast or (0, 0, 0)
                        for i, a in enumerate(alpha):
                            expected = bytes((channel * a + 127) // 255 for channel in reversed(color))
                            self.assertEqual(pixels[i * 4:i * 4 + 3], expected)
                    finally:
                        destroy_icon(icon)

    def test_refresh_releases_gdi_and_user_objects(self):
        from ctypes import wintypes
        from intext import tray_icon as tray
        from intext.platform_win import destroy_icon
        process = ctypes.windll.kernel32.GetCurrentProcess
        process.restype = wintypes.HANDLE
        resources = tray.user32.GetGuiResources
        resources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        resources.restype = wintypes.DWORD
        with patch.object(tray, "_contrast_color", return_value=(255, 255, 0)):
            destroy_icon(tray.load_tray_icon(str(ASSETS / "tray.ico"), 24))
            before = tuple(resources(process(), kind) for kind in (0, 1))
            for _ in range(64):
                destroy_icon(tray.load_tray_icon(str(ASSETS / "tray.ico"), 24))
            self.assertEqual(before, tuple(resources(process(), kind) for kind in (0, 1)))


if __name__ == "__main__":
    unittest.main()
