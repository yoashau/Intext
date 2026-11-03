"""Smooth settings-window corners.

A 1-bit SetWindowRgn stair-steps, and Windows 11's DWM round corner is a small
clip whose edge is blended against black. Neither can look like a Mac window.
The page stays in the WinForms WebView. A click-through layered window, owned
by that form, paints the antialiased rim in true alpha. The form's region is
inset just inside that rim so its stair cannot show, and the rim's center is
punched out so the page remains visible.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

CORNER_DIP = 22
RIM = 4
REGION_INSET = 2
PAD = 8

_LIGHT = (247, 244, 239)
_DARK = (28, 27, 25)

WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
GWL_STYLE = -16
GWL_WNDPROC = -4
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
SWP_HIDEWINDOW = 0x0080
WM_NCACTIVATE = 0x0086
ULW_ALPHA = 0x00000002
AC_SRC_ALPHA = 1
WM_DESTROY = 0x0002
WM_SHOWWINDOW = 0x0018
WM_WINDOWPOSCHANGED = 0x0047
WM_DPICHANGED = 0x02E0
DWMWA_NCRENDERING_POLICY = 2
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMNCRP_DISABLED = 1
DWMWCP_DONOTROUND = 1
DWMWA_COLOR_NONE = 0xFFFFFFFE
ERROR_CLASS_ALREADY_EXISTS = 1410

_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)
_CLASS_PROC = None
_CLASS = None
_HOOKS: list[tuple] = []
_FRAMES: dict[int, dict] = {}
_READY = False
_BUSY = False


class RECT(ctypes.Structure):
    _fields_ = (
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    )


class POINT(ctypes.Structure):
    _fields_ = (("x", wintypes.LONG), ("y", wintypes.LONG))


class SIZE(ctypes.Structure):
    _fields_ = (("cx", wintypes.LONG), ("cy", wintypes.LONG))


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = (
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    )


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = (
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    )


class BITMAPINFO(ctypes.Structure):
    _fields_ = (("bmiHeader", BITMAPINFOHEADER),)


class WNDCLASSW(ctypes.Structure):
    _fields_ = (
        ("style", wintypes.UINT),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    )


class WINDOWPOS(ctypes.Structure):
    _fields_ = (
        ("hwnd", wintypes.HWND),
        ("hwndInsertAfter", wintypes.HWND),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("cx", ctypes.c_int),
        ("cy", ctypes.c_int),
        ("flags", wintypes.UINT),
    )


def attach_smooth_frame(hwnd: int, light: bool) -> None:
    """Create or refresh the antialiased rim for a frameless settings window."""
    key = _key(hwnd)
    if not key:
        return
    try:
        _bind()
        _prepare_owner(key)
        _ensure_class()
        frame = _FRAMES.get(key)
        if frame is None:
            overlay = _create_overlay(key)
            if not overlay:
                _log(f"smooth-frame overlay failed {ctypes.get_last_error()}")
                return
            frame = {"overlay": overlay, "light": light, "size": (0, 0), "color": None, "dpi": 0}
            try:
                _install_hook(key)
            except Exception:
                if user32.IsWindow(overlay):
                    user32.DestroyWindow(overlay)
                raise
            _FRAMES[key] = frame
        frame["light"] = light
        # Size, DPI and color changes already invalidate the frame. Calling
        # this from every resize event must not paint the same bitmap twice.
        _sync(key, force=False)
    except Exception:
        _log_exc()


def _bind() -> None:
    global _READY
    if _READY:
        return
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    user32.GetDpiForWindow.restype = wintypes.UINT
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_void_p
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.CallWindowProcW.argtypes = [
        ctypes.c_void_p,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.CallWindowProcW.restype = ctypes.c_ssize_t
    user32.DefWindowProcW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
    user32.SetWindowRgn.restype = ctypes.c_int
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.UpdateLayeredWindow.argtypes = [
        wintypes.HWND,
        wintypes.HDC,
        ctypes.POINTER(POINT),
        ctypes.POINTER(SIZE),
        wintypes.HDC,
        ctypes.POINTER(POINT),
        wintypes.DWORD,
        ctypes.POINTER(BLENDFUNCTION),
        wintypes.DWORD,
    ]
    user32.UpdateLayeredWindow.restype = wintypes.BOOL
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    gdi32.CreateRoundRectRgn.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    gdi32.CreateRoundRectRgn.restype = wintypes.HANDLE
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    gdi32.SelectObject.restype = wintypes.HANDLE
    gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.CreateDIBSection.argtypes = [
        wintypes.HDC,
        ctypes.POINTER(BITMAPINFO),
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.HANDLE,
        wintypes.DWORD,
    ]
    gdi32.CreateDIBSection.restype = wintypes.HANDLE
    kernel32.GetLastError.restype = wintypes.DWORD
    _READY = True


def _prepare_owner(hwnd: int) -> None:
    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    cleaned = int(style) & ~WS_CAPTION & ~WS_THICKFRAME
    if cleaned != int(style):
        user32.SetWindowLongW(hwnd, GWL_STYLE, cleaned)
        user32.SetWindowPos(
            hwnd,
            None,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
    dwmapi = ctypes.windll.dwmapi
    dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    value = ctypes.c_int(DWMWCP_DONOTROUND)
    dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(value), 4)
    value = ctypes.c_int(DWMWA_COLOR_NONE)
    dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_BORDER_COLOR, ctypes.byref(value), 4)
    value = ctypes.c_int(DWMNCRP_DISABLED)
    dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_NCRENDERING_POLICY, ctypes.byref(value), 4)


def _ensure_class() -> None:
    global _CLASS_PROC, _CLASS
    if _CLASS_PROC is not None:
        return

    def proc(window, msg, wparam, lparam):
        if msg == 0x0084:  # WM_NCHITTEST: the rim must not steal clicks
            return -1
        return user32.DefWindowProcW(window, msg, wparam, lparam)

    _CLASS_PROC = _WNDPROC(proc)
    _CLASS = WNDCLASSW()
    _CLASS.lpfnWndProc = _CLASS_PROC
    _CLASS.lpszClassName = "IntextSmoothFrame"
    atom = user32.RegisterClassW(ctypes.byref(_CLASS))
    error = kernel32.GetLastError()
    if not atom and error not in (0, ERROR_CLASS_ALREADY_EXISTS):
        _log(f"smooth-frame class failed {error}")


def _create_overlay(owner: int) -> int:
    hwnd = user32.CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
        "IntextSmoothFrame",
        "",
        WS_POPUP,
        0,
        0,
        10,
        10,
        owner,
        None,
        None,
        None,
    )
    return _key(hwnd)


def _install_hook(hwnd: int) -> None:
    if any(item[0] == hwnd for item in _HOOKS):
        return
    previous = user32.GetWindowLongPtrW(hwnd, GWL_WNDPROC)

    def proc(window, msg, wparam, lparam):
        key = _key(window)
        try:
            if msg == WM_WINDOWPOSCHANGED:
                pos = ctypes.cast(lparam, ctypes.POINTER(WINDOWPOS)).contents
                if int(pos.flags) & SWP_HIDEWINDOW:
                    _hide_overlay(key)
                else:
                    _sync(key, force=False)
            elif msg == WM_DPICHANGED:
                _sync(key, force=True)
            elif msg == WM_SHOWWINDOW:
                if not wparam:
                    _hide_overlay(key)
                else:
                    _sync(key, force=True)
            elif msg == WM_NCACTIVATE:
                # DefWindowProc paints a rectangular inactive border on a
                # borderless form. -1 tells it not to redraw that frame.
                if not wparam:
                    lparam = -1
                _prepare_owner(key)
            elif msg == WM_DESTROY:
                _drop(key)
        except Exception:
            _log_exc()
        if not previous:
            return user32.DefWindowProcW(window, msg, wparam, lparam)
        return user32.CallWindowProcW(previous, window, msg, wparam, lparam)

    callback = _WNDPROC(proc)
    user32.SetWindowLongPtrW(hwnd, GWL_WNDPROC, callback)
    _HOOKS.append((hwnd, callback, proc, previous))


def hide_smooth_frame(hwnd: int) -> None:
    """Hide the rim immediately, even if a paint is in progress."""
    _hide_overlay(_key(hwnd))


def _hide_overlay(hwnd: int) -> None:
    frame = _FRAMES.get(hwnd)
    if not frame:
        return
    overlay = frame.get("overlay") or 0
    if overlay and user32.IsWindow(overlay):
        user32.ShowWindow(overlay, 0)


def _sync(hwnd: int, force: bool) -> None:
    global _BUSY
    frame = _FRAMES.get(hwnd)
    if frame is None or not user32.IsWindow(hwnd):
        return
    if _BUSY:
        frame["resync"] = True
        if not user32.IsWindowVisible(hwnd):
            _hide_overlay(hwnd)
        return
    overlay = frame["overlay"]
    if not overlay or not user32.IsWindow(overlay):
        return
    rect = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width < 8 or height < 8 or width > 8000 or height > 8000:
        return
    visible = bool(user32.IsWindowVisible(hwnd))
    if not visible:
        _hide_overlay(hwnd)
        return
    dpi = int(user32.GetDpiForWindow(hwnd) or 96)
    radius = max(12, int(round(CORNER_DIP * dpi / 96)))
    radius = min(radius, width // 2 - 2, height // 2 - 2)
    color = _LIGHT if frame["light"] else _DARK
    size_changed = frame["size"] != (width, height) or frame["dpi"] != dpi or frame["color"] != color
    _BUSY = True
    try:
        # Rebuilding the region on every move makes dragging stutter. Only
        # redo it when the size, scale, or theme actually changes.
        if force or size_changed:
            _clip_owner(hwnd, width, height, radius)
            _paint(
                overlay,
                int(rect.left),
                int(rect.top),
                width,
                height,
                radius,
                color,
                show=bool(user32.IsWindowVisible(hwnd)),
            )
            frame["size"] = (width, height)
            frame["dpi"] = dpi
            frame["color"] = color
            if force and frame.get("logged") is None:
                frame["logged"] = True
                _log(f"smooth-frame hwnd={hwnd} overlay={overlay} {width}x{height} dpi={dpi} radius={radius}")
        else:
            user32.SetWindowPos(
                overlay,
                hwnd,
                int(rect.left) - PAD,
                int(rect.top) - PAD,
                0,
                0,
                SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )
    finally:
        _BUSY = False
        if not user32.IsWindowVisible(hwnd):
            _hide_overlay(hwnd)
        elif frame.pop("resync", False):
            _sync(hwnd, force=False)


def _clip_owner(hwnd: int, width: int, height: int, radius: int) -> None:
    inset = REGION_INSET
    corner = max(1, radius - inset)
    region = gdi32.CreateRoundRectRgn(
        inset,
        inset,
        width - inset + 1,
        height - inset + 1,
        corner * 2,
        corner * 2,
    )
    if not region:
        return
    if not user32.SetWindowRgn(hwnd, region, True):
        gdi32.DeleteObject(region)


def _paint(overlay: int, x: int, y: int, width: int, height: int, radius: int, color: tuple[int, int, int], *, show: bool = True) -> None:
    from System.Drawing import Bitmap, Color, Graphics, RectangleF, SolidBrush
    from System.Drawing.Drawing2D import CompositingMode, CompositingQuality, PixelOffsetMode, SmoothingMode
    from System.Drawing.Imaging import ImageLockMode, PixelFormat

    bitmap_w = width + PAD * 2
    bitmap_h = height + PAD * 2
    bitmap = Bitmap(bitmap_w, bitmap_h, PixelFormat.Format32bppPArgb)
    graphics = Graphics.FromImage(bitmap)
    try:
        graphics.SmoothingMode = SmoothingMode.AntiAlias
        graphics.PixelOffsetMode = PixelOffsetMode.HighQuality
        graphics.CompositingQuality = CompositingQuality.HighQuality
        graphics.Clear(Color.FromArgb(0, 0, 0, 0))
        rect = RectangleF(float(PAD), float(PAD), float(width - 1), float(height - 1))
        brush = SolidBrush(Color.FromArgb(255, color[0], color[1], color[2]))
        path = _rounded(rect, radius)
        try:
            graphics.FillPath(brush, path)
        finally:
            path.Dispose()
            brush.Dispose()
        graphics.SmoothingMode = getattr(SmoothingMode, "None")
        graphics.CompositingMode = CompositingMode.SourceCopy
        hole = RectangleF(rect.X + RIM, rect.Y + RIM, rect.Width - RIM * 2, rect.Height - RIM * 2)
        clear = SolidBrush(Color.FromArgb(0, 0, 0, 0))
        hole_path = _rounded(hole, max(1, radius - RIM))
        try:
            graphics.FillPath(clear, hole_path)
        finally:
            hole_path.Dispose()
            clear.Dispose()
        graphics.Flush()
        _blit(overlay, x - PAD, y - PAD, bitmap)
    finally:
        graphics.Dispose()
        bitmap.Dispose()
    user32.ShowWindow(overlay, 8 if show else 0)


def _rounded(rect, radius: int):
    from System.Drawing.Drawing2D import GraphicsPath

    path = GraphicsPath()
    diameter = float(min(radius * 2, rect.Width, rect.Height))
    path.AddArc(rect.X, rect.Y, diameter, diameter, 180.0, 90.0)
    path.AddArc(rect.Right - diameter, rect.Y, diameter, diameter, 270.0, 90.0)
    path.AddArc(rect.Right - diameter, rect.Bottom - diameter, diameter, diameter, 0.0, 90.0)
    path.AddArc(rect.X, rect.Bottom - diameter, diameter, diameter, 90.0, 90.0)
    path.CloseFigure()
    return path


def _blit(hwnd: int, x: int, y: int, bitmap) -> None:
    from System.Drawing import Rectangle
    from System.Drawing.Imaging import ImageLockMode, PixelFormat

    width = int(bitmap.Width)
    height = int(bitmap.Height)
    data = bitmap.LockBits(
        Rectangle(0, 0, width, height),
        ImageLockMode.ReadOnly,
        PixelFormat.Format32bppPArgb,
    )
    screen = user32.GetDC(None)
    memory = gdi32.CreateCompatibleDC(screen)
    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    bits = ctypes.c_void_p()
    dib = gdi32.CreateDIBSection(screen, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
    try:
        if not dib or not bits.value:
            bitmap.UnlockBits(data)
            data = None
            _log(f"smooth-frame dib failed {kernel32.GetLastError()}")
            return
        ctypes.memmove(bits, int(data.Scan0.ToInt64()), width * height * 4)
        bitmap.UnlockBits(data)
        data = None
        old = gdi32.SelectObject(memory, dib)
        dst = POINT(x, y)
        size = SIZE(width, height)
        src = POINT(0, 0)
        blend = BLENDFUNCTION(0, 0, 255, AC_SRC_ALPHA)
        ok = user32.UpdateLayeredWindow(
            hwnd,
            None,
            ctypes.byref(dst),
            ctypes.byref(size),
            memory,
            ctypes.byref(src),
            0,
            ctypes.byref(blend),
            ULW_ALPHA,
        )
        if not ok:
            _log(f"smooth-frame blit failed {kernel32.GetLastError()}")
        gdi32.SelectObject(memory, old)
    finally:
        if data is not None:
            bitmap.UnlockBits(data)
        if dib:
            gdi32.DeleteObject(dib)
        if memory:
            gdi32.DeleteDC(memory)
        if screen:
            user32.ReleaseDC(None, screen)


def _drop(hwnd: int) -> None:
    frame = _FRAMES.pop(hwnd, None)
    if not frame:
        return
    overlay = frame.get("overlay")
    if overlay and user32.IsWindow(overlay):
        user32.DestroyWindow(overlay)


def _key(value) -> int:
    if not value:
        return 0
    raw = getattr(value, "value", value)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _log(message: str) -> None:
    try:
        from .config import log_error

        log_error(message)
    except Exception:
        return


def _log_exc() -> None:
    import traceback

    _log(traceback.format_exc())
