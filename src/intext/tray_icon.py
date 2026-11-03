"""Load tray artwork with the taskbar's foreground, including contrast themes.

Application/window icons do not use this module. The opaque white tray asset
is the coverage mask for custom contrast colors, so normal-mode opacity never
dims an accessibility foreground.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

from .platform_win import destroy_icon, load_icon

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)


class HIGHCONTRASTW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwFlags", wintypes.DWORD), ("scheme", wintypes.LPWSTR)]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
               ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP), ("hbmColor", wintypes.HBITMAP)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
               ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
               ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
               ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.LPVOID, wintypes.UINT]
user32.SystemParametersInfoW.restype = wintypes.BOOL
user32.GetSysColor.argtypes = [ctypes.c_int]
user32.GetSysColor.restype = wintypes.DWORD
user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(ICONINFO)]
user32.GetIconInfo.restype = wintypes.BOOL
user32.CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]
user32.CreateIconIndirect.restype = wintypes.HICON
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                          wintypes.LPVOID, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT,
                                 ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL


def _contrast_color() -> tuple[int, int, int] | None:
    contrast = HIGHCONTRASTW()
    contrast.cbSize = ctypes.sizeof(contrast)
    if not user32.SystemParametersInfoW(0x0042, contrast.cbSize, ctypes.byref(contrast), 0):
        return None
    if not contrast.dwFlags & 1:  # HCF_HIGHCONTRASTON
        return None
    color = user32.GetSysColor(8)  # COLOR_WINDOWTEXT
    return color & 255, (color >> 8) & 255, (color >> 16) & 255


def _tint_icon(source, size: int, color: tuple[int, int, int]):
    info = ICONINFO()
    if not user32.GetIconInfo(source, ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    dc = None
    bitmap = None
    try:
        dc = user32.GetDC(None)
        if not dc:
            raise ctypes.WinError(ctypes.get_last_error())
        header = BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(header)
        header.biWidth, header.biHeight = size, -size
        header.biPlanes, header.biBitCount = 1, 32
        rgba = (ctypes.c_ubyte * (size * size * 4))()
        if gdi32.GetDIBits(dc, info.hbmColor, 0, size, rgba, ctypes.byref(header), 0) != size:
            raise ctypes.WinError(ctypes.get_last_error())
        red, green, blue = color
        for offset in range(0, len(rgba), 4):
            alpha = rgba[offset + 3]
            rgba[offset] = (blue * alpha + 127) // 255
            rgba[offset + 1] = (green * alpha + 127) // 255
            rgba[offset + 2] = (red * alpha + 127) // 255
        pixels = ctypes.c_void_p()
        bitmap = gdi32.CreateDIBSection(dc, ctypes.byref(header), 0, ctypes.byref(pixels), None, 0)
        if not bitmap:
            raise ctypes.WinError(ctypes.get_last_error())
        ctypes.memmove(pixels, rgba, len(rgba))
        tinted = ICONINFO(True, 0, 0, info.hbmMask, bitmap)
        result = user32.CreateIconIndirect(ctypes.byref(tinted))
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())
        return result
    finally:
        if bitmap:
            gdi32.DeleteObject(bitmap)
        gdi32.DeleteObject(info.hbmColor)
        gdi32.DeleteObject(info.hbmMask)
        if dc:
            user32.ReleaseDC(None, dc)


def load_tray_icon(path: str, size: int):
    color = _contrast_color()
    if color is None:
        return load_icon(path, size)
    mask = load_icon(str(Path(path).with_name("tray-on-dark.ico")), size)
    if not mask:
        return None
    try:
        return _tint_icon(mask, size, color)
    finally:
        destroy_icon(mask)
