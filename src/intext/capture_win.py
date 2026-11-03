"""Select a screen region and read its text with Windows OCR.

The overlay is a normal Win32 window. It does not touch WebView2, so it can
run on a worker thread without freezing the popup.
"""

from __future__ import annotations

import base64
import re
import subprocess
import tempfile
from ctypes import wintypes
from pathlib import Path

import ctypes

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

WM_DESTROY = 0x0002
WM_PAINT = 0x000F
WM_ERASEBKGND = 0x0014
WM_KEYDOWN = 0x0100
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEMOVE = 0x0200
WM_RBUTTONUP = 0x0205
WM_SETCURSOR = 0x0020
VK_ESCAPE = 0x1B
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x00000002
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
IDC_CROSS = 32515

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

_OCR = r"""
param([string]$Path)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq "AsTask" -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]
function Await($WinRtTask, $ResultType) {
  $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
  $netTask = $asTask.Invoke($null, @($WinRtTask))
  if (-not $netTask.Wait(12000)) { exit 3 }
  $netTask.Result
}
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$zh = [Windows.Globalization.Language]::new("zh-Hans")
if ([Windows.Media.Ocr.OcrEngine]::IsLanguageSupported($zh)) {
  $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($zh)
} else {
  $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
}
if (-not $engine) { exit 2 }
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
Write-Output $result.Text
"""


class WNDCLASSW(ctypes.Structure):
    _fields_ = (
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    )


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = (
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", wintypes.RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", wintypes.BYTE * 32),
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


def _bind() -> None:
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = wintypes.BOOL
    user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
    user32.BeginPaint.restype = wintypes.HDC
    user32.GetDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.CreatePen.restype = wintypes.HPEN
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int


class _Drag:
    def __init__(self) -> None:
        self.origin = (0, 0)
        self.current = (0, 0)
        self.down = False
        self.rect: tuple[int, int, int, int] | None = None
        self.proc = None


def _point(lparam: int) -> tuple[int, int]:
    return ctypes.c_short(lparam & 0xFFFF).value, ctypes.c_short((lparam >> 16) & 0xFFFF).value


def _normalized(origin: tuple[int, int], current: tuple[int, int], base: tuple[int, int]) -> tuple[int, int, int, int] | None:
    left = min(origin[0], current[0]) + base[0]
    top = min(origin[1], current[1]) + base[1]
    right = max(origin[0], current[0]) + base[0]
    bottom = max(origin[1], current[1]) + base[1]
    if right - left < 8 or bottom - top < 8:
        return None
    return left, top, right - left, bottom - top


_capture_proc = None
_capture_drag = None
_SetWindowLongPtrW = ctypes.WINFUNCTYPE(ctypes.c_void_p, wintypes.HWND, ctypes.c_int, WNDPROC)(
    ("SetWindowLongPtrW", user32)
)
GWLP_WNDPROC = -4


def select_region() -> tuple[int, int, int, int] | None:
    """Block until the user drags a region. Return physical pixels, or None."""
    global _capture_proc, _capture_drag
    drag = _Drag()
    _capture_drag = drag
    base = (user32.GetSystemMetrics(SM_XVIRTUALSCREEN), user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
    size = (user32.GetSystemMetrics(SM_CXVIRTUALSCREEN), user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
    user32.LoadCursorW.restype = wintypes.HANDLE
    cursor = user32.LoadCursorW(None, IDC_CROSS)

    def wndproc(hwnd, message, wparam, lparam):
        if message == WM_LBUTTONDOWN:
            drag.down = True
            drag.origin = drag.current = _point(lparam)
            user32.SetCapture(hwnd)
            return 0
        if message == WM_MOUSEMOVE and drag.down:
            drag.current = _point(lparam)
            user32.InvalidateRect(hwnd, None, True)
            return 0
        if message == WM_LBUTTONUP and drag.down:
            drag.down = False
            drag.current = _point(lparam)
            user32.ReleaseCapture()
            rect = _normalized(drag.origin, drag.current, base)
            if rect is None:
                user32.InvalidateRect(hwnd, None, True)
                return 0
            drag.rect = rect
            user32.DestroyWindow(hwnd)
            return 0
        if message == WM_RBUTTONUP or (message == WM_KEYDOWN and wparam == VK_ESCAPE):
            drag.rect = None
            user32.DestroyWindow(hwnd)
            return 0
        if message == WM_SETCURSOR:
            user32.SetCursor(cursor or user32.LoadCursorW(None, IDC_CROSS))
            return 1
        if message == WM_ERASEBKGND:
            return 1
        if message == WM_PAINT:
            paint = PAINTSTRUCT()
            hdc = user32.BeginPaint(hwnd, ctypes.byref(paint))
            if drag.down:
                left = min(drag.origin[0], drag.current[0])
                top = min(drag.origin[1], drag.current[1])
                right = max(drag.origin[0], drag.current[0])
                bottom = max(drag.origin[1], drag.current[1])
                pen = gdi32.CreatePen(0, 2, 0x00FFFFFF)
                old = gdi32.SelectObject(hdc, pen)
                gdi32.SelectObject(hdc, gdi32.GetStockObject(5))
                gdi32.Rectangle(hdc, left, top, right, bottom)
                gdi32.SelectObject(hdc, old)
                gdi32.DeleteObject(pen)
            user32.EndPaint(hwnd, ctypes.byref(paint))
            return 0
        if message == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    proc = WNDPROC(wndproc)
    # The class name is registered only once. A later call must keep this
    # callback alive and install it on the new hwnd, or mouse input goes to
    # the first, already finished drag.
    _capture_proc = proc
    drag.proc = proc
    instance = kernel32.GetModuleHandleW(None)
    window_class = WNDCLASSW()
    window_class.lpfnWndProc = proc
    window_class.hInstance = instance
    window_class.hCursor = cursor
    window_class.hbrBackground = gdi32.GetStockObject(4)
    window_class.lpszClassName = "IntextCapture"
    user32.RegisterClassW(ctypes.byref(window_class))
    hwnd = user32.CreateWindowExW(
        WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_LAYERED,
        "IntextCapture",
        "Intext",
        WS_POPUP | WS_VISIBLE,
        base[0],
        base[1],
        size[0],
        size[1],
        None,
        None,
        instance,
        None,
    )
    if not hwnd:
        return None
    _SetWindowLongPtrW(hwnd, GWLP_WNDPROC, proc)
    user32.SetLayeredWindowAttributes(hwnd, 0, 88, LWA_ALPHA)
    user32.SetForegroundWindow(hwnd)
    message = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))
    return drag.rect


def _struct_bytes(value) -> bytes:
    return ctypes.string_at(ctypes.addressof(value), ctypes.sizeof(value))


def _write_bmp(path: Path, width: int, height: int, pixels: bytes, row_stride: int) -> None:
    info = BITMAPINFOHEADER()
    info.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.biWidth = width
    info.biHeight = height
    info.biPlanes = 1
    info.biBitCount = 24
    info.biSizeImage = row_stride * height
    offset = 14 + ctypes.sizeof(info)
    file_size = offset + len(pixels)
    header = b"BM" + int(file_size).to_bytes(4, "little") + bytes(4) + int(offset).to_bytes(4, "little")
    path.write_bytes(header + _struct_bytes(info) + pixels)


def capture_bmp(rect: tuple[int, int, int, int], path: Path) -> None:
    x, y, width, height = rect
    screen = user32.GetDC(None)
    memory = gdi32.CreateCompatibleDC(screen)
    bitmap = gdi32.CreateCompatibleBitmap(screen, width, height)
    old = gdi32.SelectObject(memory, bitmap)
    gdi32.BitBlt(memory, 0, 0, width, height, screen, x, y, SRCCOPY)
    row = ((width * 3 + 3) // 4) * 4
    info = BITMAPINFOHEADER()
    info.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.biWidth = width
    info.biHeight = height
    info.biPlanes = 1
    info.biBitCount = 24
    info.biSizeImage = row * height
    pixels = ctypes.create_string_buffer(info.biSizeImage)
    gdi32.GetDIBits(memory, bitmap, 0, height, pixels, ctypes.byref(info), DIB_RGB_COLORS)
    _write_bmp(path, width, height, pixels.raw, row)
    gdi32.SelectObject(memory, old)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory)
    user32.ReleaseDC(None, screen)


def _tidy(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    return " ".join(text.split()) if "\n" not in text else text.strip()


def recognize_file(path: Path) -> str:
    safe = str(path).replace("'", "''")
    script = _OCR.replace("param([string]$Path)", f"$Path = '{safe}'")
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-WindowStyle", "Hidden", "-EncodedCommand", encoded],
            capture_output=True,
            timeout=20,
            creationflags=0x08000000,
            check=False,
        )
    except subprocess.TimeoutExpired:
        from .config import log_error

        log_error("ocr timeout")
        return ""
    if completed.returncode != 0:
        from .config import log_error

        log_error(completed.stderr.decode("utf-8", "replace")[:500] or "ocr failed")
        return ""
    return _tidy(completed.stdout.decode("utf-8-sig", "replace"))


def read_screen_text() -> str | None:
    """None means the user cancelled. An empty string means nothing was read."""
    import time

    rect = select_region()
    if rect is None:
        return None
    time.sleep(0.08)
    with tempfile.TemporaryDirectory(prefix="intext-shot-") as folder:
        path = Path(folder) / "shot.bmp"
        capture_bmp(rect, path)
        return recognize_file(path)


_bind()
