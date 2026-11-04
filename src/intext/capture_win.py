"""Frozen desktop capture with buffered rectangle and Ctrl-freehand selection."""

from __future__ import annotations

import ctypes
import itertools
import os
from ctypes import wintypes
from functools import lru_cache
from pathlib import Path

from .screenshot import Screenshot, Selection, lasso_selection, mask_screenshot, rectangle_selection

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_classes = itertools.count()


class WNDCLASSW(ctypes.Structure):
    _fields_ = (("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR))


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = (("hdc", wintypes.HDC), ("fErase", wintypes.BOOL), ("rcPaint", wintypes.RECT),
                ("fRestore", wintypes.BOOL), ("fIncUpdate", wintypes.BOOL), ("reserved", ctypes.c_byte * 32))


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = (("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD))


def _bind() -> None:
    def bind(dll, name, result, *args):
        function = getattr(dll, name)
        function.restype, function.argtypes = result, list(args)
    H, I, U, P = wintypes.HANDLE, ctypes.c_int, wintypes.UINT, ctypes.c_void_p
    bind(kernel32, "GetModuleHandleW", H, wintypes.LPCWSTR)
    bind(user32, "RegisterClassW", wintypes.ATOM, ctypes.POINTER(WNDCLASSW))
    bind(user32, "UnregisterClassW", wintypes.BOOL, wintypes.LPCWSTR, H)
    bind(user32, "CreateWindowExW", H, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
         I, I, I, I, H, H, H, P)
    bind(user32, "DefWindowProcW", LRESULT, H, U, wintypes.WPARAM, wintypes.LPARAM)
    bind(user32, "GetMessageW", wintypes.BOOL, ctypes.POINTER(wintypes.MSG), H, U, U)
    bind(user32, "TranslateMessage", wintypes.BOOL, ctypes.POINTER(wintypes.MSG))
    bind(user32, "DispatchMessageW", LRESULT, ctypes.POINTER(wintypes.MSG))
    bind(user32, "LoadCursorW", H, H, P)
    bind(user32, "SetCursor", H, H)
    bind(user32, "SetCapture", H, H)
    bind(user32, "SetForegroundWindow", wintypes.BOOL, H)
    bind(user32, "DestroyWindow", wintypes.BOOL, H)
    bind(user32, "InvalidateRect", wintypes.BOOL, H, P, wintypes.BOOL)
    bind(user32, "BeginPaint", H, H, ctypes.POINTER(PAINTSTRUCT))
    bind(user32, "EndPaint", wintypes.BOOL, H, ctypes.POINTER(PAINTSTRUCT))
    bind(user32, "GetDC", H, H)
    bind(user32, "ReleaseDC", I, H, H)
    bind(gdi32, "CreateCompatibleDC", H, H)
    bind(gdi32, "SelectObject", H, H, H)
    bind(gdi32, "DeleteObject", wintypes.BOOL, H)
    bind(gdi32, "DeleteDC", wintypes.BOOL, H)
    bind(gdi32, "BitBlt", wintypes.BOOL, H, I, I, I, I, H, I, I, wintypes.DWORD)
    bind(gdi32, "CreatePolygonRgn", H, ctypes.POINTER(wintypes.POINT), I, I)
    bind(gdi32, "CreateDIBSection", H, H, P, U, ctypes.POINTER(P), H, wintypes.DWORD)
    bind(gdi32, "SelectClipRgn", I, H, H)
    bind(gdi32, "SaveDC", I, H)
    bind(gdi32, "RestoreDC", wintypes.BOOL, H, I)
    bind(gdi32, "IntersectClipRect", I, H, I, I, I, I)
    bind(gdi32, "GdiFlush", wintypes.BOOL)
    bind(user32, "ShowWindow", wintypes.BOOL, H, I)
    bind(user32, "UpdateWindow", wintypes.BOOL, H)


def virtual_screen() -> tuple[int, int, int, int]:
    return tuple(user32.GetSystemMetrics(index) for index in (76, 77, 78, 79))


def _bitmap_info(width: int, height: int) -> BITMAPINFOHEADER:
    info = BITMAPINFOHEADER()
    info.biSize = ctypes.sizeof(info)
    info.biWidth, info.biHeight = width, -height
    info.biPlanes, info.biBitCount = 1, 32
    info.biSizeImage = width * height * 4
    return info


def screen_image(rect: tuple[int, int, int, int]):
    surface = _screen_surface(rect)
    try:
        return surface.to_image()
    finally:
        surface.close()


def _screen_surface(rect):
    """Freeze directly into the DIB reused by the selection window."""
    x, y, width, height = rect
    screen = user32.GetDC(None)
    surface = None
    try:
        surface = _Surface((width, height))
        if not gdi32.BitBlt(surface.dc, 0, 0, width, height, screen, x, y, 0x00CC0020):
            raise ctypes.WinError(ctypes.get_last_error())
        return surface
    except Exception:
        if surface is not None:
            surface.close()
        raise
    finally:
        user32.ReleaseDC(None, screen)


def capture_bmp(rect: tuple[int, int, int, int], path: Path) -> None:
    screen_image(rect).save(path, format="BMP")


def _point(lparam: int) -> tuple[int, int]:
    return ctypes.c_short(lparam & 0xFFFF).value, ctypes.c_short((lparam >> 16) & 0xFFFF).value


class _Surface:
    """A persistent top-down DIB. Each frame is presented in one BitBlt."""

    def __init__(self, size: tuple[int, int], pixels: bytes | None = None):
        self.width, self.height = size
        self.dc = gdi32.CreateCompatibleDC(None)
        self.bitmap = self.old = None
        try:
            info = _bitmap_info(*size)
            bits = ctypes.c_void_p()
            self.bitmap = gdi32.CreateDIBSection(self.dc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
            self.bits = bits
            if not self.dc or not self.bitmap or not bits:
                raise ctypes.WinError(ctypes.get_last_error())
            self.old = gdi32.SelectObject(self.dc, self.bitmap)
            if pixels is not None:
                if len(pixels) != self.width * self.height * 4:
                    raise ValueError("Invalid capture surface dimensions")
                ctypes.memmove(bits, pixels, len(pixels))
        except Exception:
            self.close()
            raise

    def to_image(self):
        from PIL import Image

        # GDI batches writes; finish them before reading the DIB's memory.
        gdi32.GdiFlush()
        pixels = ctypes.string_at(self.bits, self.width * self.height * 4)
        return Image.frombytes("RGB", (self.width, self.height), pixels, "raw", "BGRX")

    def close(self):
        if self.old:
            gdi32.SelectObject(self.dc, self.old)
            self.old = None
        if self.bitmap:
            gdi32.DeleteObject(self.bitmap)
            self.bitmap = None
        if self.dc:
            gdi32.DeleteDC(self.dc)
            self.dc = None


@lru_cache(maxsize=4)
def _hint_image(scale: float, light: bool):
    """Supersampled grayscale text and rounded edges, without ClearType fringes."""
    from PIL import Image, ImageChops, ImageDraw, ImageFont

    factor = 4
    density = scale * factor
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    font = ImageFont.truetype(str(fonts / "msyh.ttc"), round(14 * density))
    text = "拖动框选 · Ctrl + 拖动自由圈选 · Esc / 右键取消"
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    box = measure.textbbox((0, 0), text, font=font)
    width = round((box[2] - box[0] + 32 * density) / factor)
    height = round((box[3] - box[1] + 18 * density) / factor)
    image = Image.new("RGBA", (width * factor, height * factor))
    draw = ImageDraw.Draw(image)
    fill, ink, edge = ((247, 244, 239), (38, 35, 31), (223, 218, 209)) if light else ((46, 43, 40), (243, 238, 231), (74, 70, 65))
    draw.rounded_rectangle((factor, factor, image.width-factor-1, image.height-factor-1),
                           radius=10*density, fill=fill, outline=edge, width=factor)
    draw.text((16*density-box[0], 9*density-box[1]), text, font=font, fill=ink)
    image = image.resize((width, height), Image.Resampling.LANCZOS)
    red, green, blue, alpha = image.split()
    # AlphaBlend expects premultiplied BGRA. Straight alpha produces black halos.
    premultiplied = Image.merge("RGBA", tuple(ImageChops.multiply(channel, alpha) for channel in (red, green, blue)) + (alpha,))
    return image, premultiplied.tobytes("raw", "BGRA")



def select_region(image=None, rect=None) -> Selection | None:
    """Drag a rectangle; hold Ctrl to switch the current drag to freehand."""
    from contextlib import ExitStack
    from .platform_win import apps_use_light_theme, cursor_pos, work_area_at

    rect = rect or virtual_screen()
    image = image or screen_image(rect)
    base, size = rect[:2], rect[2:]
    scale = max(1.0, user32.GetDpiForSystem() / 96.0)
    work = work_area_at(*cursor_pos())
    hint, hint_pixels = _hint_image(scale, apps_use_light_theme())
    hint_x = (work[0] + work[2] - hint.width) // 2 - base[0]
    hint_y = work[1] - base[1] + round(24 * scale)
    cursor = user32.LoadCursorW(None, ctypes.c_void_p(32515))
    alpha_blend = ctypes.WinDLL("msimg32", use_last_error=True).AlphaBlend
    alpha_blend.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                           wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    alpha_blend.restype = wintypes.BOOL
    points, errors = [], []
    selection = None
    down = freehand = dirty = False
    current = (0, 0)
    painted = None

    with ExitStack() as resources:
        def surface(image_size, pixels=None):
            value = _Surface(image_size, pixels)
            resources.callback(value.close)
            return value

        original = image if isinstance(image, _Surface) else surface(size, image.tobytes("raw", "BGRX"))
        dimmed = surface(size)
        gdi32.BitBlt(dimmed.dc, 0, 0, *size, None, 0, 0, 0x00000042)  # BLACKNESS
        if not alpha_blend(dimmed.dc, 0, 0, *size, original.dc, 0, 0, *size, 122 << 16):
            raise ctypes.WinError(ctypes.get_last_error())
        frame = surface(size)
        hint_surface = surface(hint.size, hint_pixels)
        freehand_fill = None

        def shape_points():
            if not points:
                return []
            if freehand:
                return points if current == points[-1] else points + [current]
            x0, y0 = points[0]
            x1, y1 = current
            return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

        def bounds(shape):
            if not shape or not down:
                return None
            xs, ys = zip(*shape)
            pad = 1
            return max(0, min(xs)-pad), max(0, min(ys)-pad), min(size[0], max(xs)+pad+1), min(size[1], max(ys)+pad+1)

        def invalidate(hwnd):
            nonlocal dirty
            dirty = True
            areas = [area for area in (painted, bounds(shape_points())) if area is not None]
            if areas:
                damage = wintypes.RECT(min(a[0] for a in areas), min(a[1] for a in areas),
                                       max(a[2] for a in areas), max(a[3] for a in areas))
                user32.InvalidateRect(hwnd, ctypes.byref(damage), False)

        def compose(damage):
            nonlocal painted
            x, y, right, bottom = damage
            saved_frame = gdi32.SaveDC(frame.dc)
            gdi32.IntersectClipRect(frame.dc, x, y, right, bottom)
            try:
                draw_frame(x, y, right-x, bottom-y)
            finally:
                gdi32.RestoreDC(frame.dc, saved_frame)
            painted = bounds(shape_points())

        def draw_frame(x, y, width, height):
            nonlocal freehand_fill
            gdi32.BitBlt(frame.dc, x, y, width, height, dimmed.dc, x, y, 0x00CC0020)
            shape = shape_points()
            if down and freehand and len(shape) >= 3:
                if freehand_fill is None:
                    from .selection_win import FreehandFill

                    gdi32.GdiFlush()
                    freehand_fill = FreehandFill(original)
                    resources.callback(freehand_fill.close)
                freehand_fill.draw(frame.dc, shape, (x, y, width, height))
            elif down and len(shape) >= 3:
                polygon = (wintypes.POINT * len(shape))(*(wintypes.POINT(*p) for p in shape))
                region = gdi32.CreatePolygonRgn(polygon, len(shape), 1)
                saved = gdi32.SaveDC(frame.dc)
                try:
                    gdi32.SelectClipRgn(frame.dc, region)
                    gdi32.BitBlt(frame.dc, x, y, width, height, original.dc, x, y, 0x00CC0020)
                finally:
                    gdi32.RestoreDC(frame.dc, saved)
                    gdi32.DeleteObject(region)
            if not alpha_blend(frame.dc, hint_x, hint_y, hint.width, hint.height,
                               hint_surface.dc, 0, 0, hint.width, hint.height, 0x01FF0000):
                raise ctypes.WinError(ctypes.get_last_error())

        def point(lparam):
            x, y = _point(lparam)
            return min(max(x, 0), size[0]-1), min(max(y, 0), size[1]-1)

        def handle(hwnd, message, wparam, lparam):
            nonlocal down, freehand, dirty, current, selection
            if message == 0x0201:
                current = point(lparam)
                points[:] = [current]
                freehand = bool(wparam & 0x0008)  # MK_CONTROL, captured with the mouse event.
                down = dirty = True
                user32.SetCapture(hwnd)
                invalidate(hwnd)
                return 0
            if message == 0x0200 and down:
                current = point(lparam)
                freehand = freehand or bool(wparam & 0x0008)
                if len(points) < 16000 and sum((a-b)**2 for a,b in zip(current, points[-1])) >= 4:
                    points.append(current)
                invalidate(hwnd)
                return 0
            if message == 0x0202 and down:
                current = point(lparam)
                freehand = freehand or bool(wparam & 0x0008)
                if freehand and current != points[-1]:
                    points.append(current)
                down = False
                user32.ReleaseCapture()
                selection = lasso_selection(points, base) if freehand else rectangle_selection(points[0], current, base)
                if selection is not None:
                    user32.DestroyWindow(hwnd)
                else:
                    points.clear()
                    invalidate(hwnd)
                return 0
            if message in (0x001F, 0x0215) and down:  # Cancel/capture lost.
                down = False
                points.clear()
                invalidate(hwnd)
                return 0
            if message == 0x0205 or (message == 0x0100 and wparam == 0x1B) or message == 0x0008:
                user32.DestroyWindow(hwnd)
                return 0
            if message == 0x0020:
                user32.SetCursor(cursor)
                return 1
            if message == 0x0014:
                return 1
            if message == 0x000F:
                paint = PAINTSTRUCT()
                hdc = user32.BeginPaint(hwnd, ctypes.byref(paint))
                try:
                    if dirty:
                        r = paint.rcPaint
                        compose((r.left, r.top, r.right, r.bottom))
                        dirty = False
                    # The screen never sees the intermediate dim/selection/text passes.
                    r = paint.rcPaint
                    gdi32.BitBlt(hdc, r.left, r.top, r.right-r.left, r.bottom-r.top,
                                 frame.dc, r.left, r.top, 0x00CC0020)
                finally:
                    user32.EndPaint(hwnd, ctypes.byref(paint))
                return 0
            if message == 0x0002:
                user32.ReleaseCapture()
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)

        def callback(*args):
            try:
                return handle(*args)
            except Exception as exc:
                errors.append(exc)
                user32.DestroyWindow(args[0])
                return 0

        proc = WNDPROC(callback)
        instance = kernel32.GetModuleHandleW(None)
        name = f"IntextCapture{next(_classes)}"
        cls = WNDCLASSW(lpfnWndProc=proc, hInstance=instance, hCursor=cursor, lpszClassName=name)
        if not user32.RegisterClassW(ctypes.byref(cls)):
            raise ctypes.WinError(ctypes.get_last_error())
        hwnd = None
        try:
            # Finish the first frame while hidden so creation cannot flash black.
            compose((0, 0, *size))
            hwnd = user32.CreateWindowExW(0x00000088, name, "Intext capture", 0x80000000,
                                          *rect, None, None, instance, None)
            if not hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            user32.ShowWindow(hwnd, 5)
            user32.UpdateWindow(hwnd)
            user32.SetForegroundWindow(hwnd)
            message = wintypes.MSG()
            while True:
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result <= 0:
                    if result < 0:
                        raise ctypes.WinError(ctypes.get_last_error())
                    break
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
            if errors:
                raise errors[0]
            return selection
        finally:
            if hwnd:
                user32.DestroyWindow(hwnd)
            user32.UnregisterClassW(name, instance)


def capture_shot() -> Screenshot | None:
    # Wait for the compositor to remove Intext windows hidden by the caller.
    ctypes.WinDLL("dwmapi").DwmFlush()
    rect = virtual_screen()
    frozen = _screen_surface(rect)
    try:
        selection = select_region(frozen, rect)
        if selection is None:
            return None
        x, y, width, height = selection.rect
        crop = _Surface((width, height))
        try:
            gdi32.BitBlt(crop.dc, 0, 0, width, height, frozen.dc, x-rect[0], y-rect[1], 0x00CC0020)
            return mask_screenshot(crop.to_image(), selection, (x, y))
        finally:
            crop.close()
    finally:
        frozen.close()


def _mask_freehand(image, points):
    """Use precisely the live path and coverage for the exported screenshot."""
    from contextlib import ExitStack
    from PIL import Image
    from .selection_win import FreehandFill

    with ExitStack() as resources:
        source = _Surface(image.size, image.tobytes("raw", "BGRX"))
        resources.callback(source.close)
        background = Image.new("RGB", image.size, "white")
        output = _Surface(image.size, background.tobytes("raw", "BGRX"))
        resources.callback(output.close)
        fill = FreehandFill(source)
        resources.callback(fill.close)
        fill.draw(output.dc, points, (0, 0, *image.size))
        return output.to_image()


def read_screen_text() -> str | None:
    from .ocr import recognize

    shot = capture_shot()
    return None if shot is None else recognize(shot).text


_bind()
