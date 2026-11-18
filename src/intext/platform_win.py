"""Windows selection capture and global hotkey.

Selection prefers not to disturb the clipboard. If the clipboard holds files
or an image, the copy fallback is skipped. Text that is replaced is restored.
"""

from __future__ import annotations

import ctypes
import threading
import time
from concurrent.futures import Future, TimeoutError
from ctypes import wintypes
from dataclasses import dataclass

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def _bind() -> None:
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.EmptyClipboard.argtypes = []
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    user32.GetClipboardSequenceNumber.argtypes = []
    user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
    user32.GetClipboardOwner.argtypes = []
    user32.GetClipboardOwner.restype = wintypes.HWND
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HANDLE]
    kernel32.GlobalFree.restype = wintypes.HANDLE
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.MonitorFromPoint.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    user32.GetMonitorInfoW.restype = wintypes.BOOL



CF_UNICODETEXT = 13
CF_BITMAP = 2
CF_DIB = 8
CF_HDROP = 15
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
VK = {chr(code): code for code in range(ord("A"), ord("Z") + 1)}
VK.update({str(digit): 0x30 + digit for digit in range(10)})
VK.update({f"F{number}": 0x70 + number - 1 for number in range(1, 13)})
KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1
VK_CONTROL = 0x11
VK_C = 0x43


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    )


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    )


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    )


class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = (("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT))

    _anonymous_ = ("u",)
    _fields_ = (("type", wintypes.DWORD), ("u", _INPUT))


# Must be wintypes.POINT. shell_win used to rebind GetCursorPos to that type;
# a private Structure with the same fields still raises ArgumentError and the
# hotkey thread used to die before the popup was shown.
POINT = wintypes.POINT


class RECT(ctypes.Structure):
    _fields_ = (
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    )


def enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            return


_GetCursorPos = ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.POINTER(wintypes.POINT))(
    ("GetCursorPos", user32)
)
_AllowSetForegroundWindow = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)(
    ("AllowSetForegroundWindow", user32)
)
_SetForegroundWindow = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND)(
    ("SetForegroundWindow", user32)
)
_ShowWindow = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, ctypes.c_int)(
    ("ShowWindow", user32)
)
# Private prototype. Setting this on the shared user32 object makes pywebview's
# move() fail: it passes None for the unused size fields.
_SetWindowPos = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
)(("SetWindowPos", ctypes.WinDLL("user32", use_last_error=True)))


def cursor_pos() -> tuple[int, int]:
    """Physical cursor position. Never raises; pot-desktop falls back to (0, 0)."""
    point = wintypes.POINT()
    try:
        if not _GetCursorPos(ctypes.byref(point)):
            return 0, 0
    except Exception:
        return 0, 0
    return int(point.x), int(point.y)


def allow_foreground() -> None:
    """Let the UI thread take focus after WM_HOTKEY returns.

    The hotkey thread is the one Windows allows to set the foreground window.
    pywebview's later Show() runs on another thread and otherwise stays behind.
    """
    _AllowSetForegroundWindow(0xFFFFFFFF)


def foreground(hwnd: int) -> None:
    if not hwnd:
        return
    _ShowWindow(hwnd, 5)
    _SetForegroundWindow(hwnd)


_IsWindowVisible = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND)(("IsWindowVisible", user32))


def window_visible(hwnd: int) -> bool:
    return bool(hwnd and _IsWindowVisible(hwnd))


def hide_owned_window(hwnd: int) -> None:
    if hwnd:
        _ShowWindow(hwnd, 0)


def work_area_at(x: int, y: int) -> tuple[int, int, int, int]:
    class MONITORINFO(ctypes.Structure):
        _fields_ = (
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", wintypes.DWORD),
        )

    monitor = user32.MonitorFromPoint(POINT(x, y), 2)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        rect = info.rcWork
        return rect.left, rect.top, rect.right, rect.bottom
    return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def clamp_window(x: int, y: int, width: int, height: int) -> tuple[int, int]:
    left, top, right, bottom = work_area_at(x, y)
    x = min(max(x, left), max(left, right - width))
    y = min(max(y, top), max(top, bottom - height))
    return x, y


def _open_clipboard(owner: int | None = None) -> bool:
    for _ in range(8):
        if user32.OpenClipboard(owner):
            return True
        time.sleep(0.01)
    return False


def _read_clipboard_text() -> str | None:
    if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
        return None
    handle = user32.GetClipboardData(CF_UNICODETEXT)
    if not handle:
        return None
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        return None
    try:
        return ctypes.wstring_at(pointer)
    finally:
        kernel32.GlobalUnlock(handle)


def clipboard_text() -> str | None:
    if not _open_clipboard():
        return None
    try:
        return _read_clipboard_text()
    finally:
        user32.CloseClipboard()


def _clipboard_version() -> tuple[int, int]:
    return user32.GetClipboardSequenceNumber(), int(user32.GetClipboardOwner() or 0)


@dataclass(frozen=True)
class _ClipboardSnapshot:
    text: str | None
    version: tuple[int, int]


def _clipboard_snapshot(*, text_only: bool = False) -> _ClipboardSnapshot | None:
    if not _open_clipboard():
        return None
    try:
        if text_only and _has_non_text_clipboard_data():
            return None
        text = _read_clipboard_text()
        if text_only and text is None and user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        return _ClipboardSnapshot(text, _clipboard_version())
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text: str, *, expected: _ClipboardSnapshot | None = None) -> bool:
    """Replace clipboard text. The allocation happens before the clipboard is emptied."""
    encoded = (text + "\0").encode("utf-16-le")
    handle = kernel32.GlobalAlloc(0x0002, len(encoded))
    if not handle:
        return False
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        kernel32.GlobalFree(handle)
        return False
    try:
        ctypes.memmove(pointer, encoded, len(encoded))
    finally:
        kernel32.GlobalUnlock(handle)
    # EmptyClipboard followed by SetClipboardData requires a real HWND.
    # The bridge runs on worker threads, where GetActiveWindow returns NULL.
    create = ctypes.WINFUNCTYPE(
        wintypes.HWND, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
        wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    )(("CreateWindowExW", user32))
    destroy = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND)(("DestroyWindow", user32))
    owner = create(0, "STATIC", "IntextClipboard", 0, 0, 0, 0, 0, -3, None, None, None)
    if not owner:
        kernel32.GlobalFree(handle)
        return False
    if not _open_clipboard(owner):
        destroy(owner)
        kernel32.GlobalFree(handle)
        return False
    committed = False
    try:
        if expected is not None:
            if _has_non_text_clipboard_data() or _clipboard_version() != expected.version:
                return False
            # Reading Unicode text renders any deferred clipboard data before
            # the final revision check. The clipboard is still open here.
            if _read_clipboard_text() != expected.text or _clipboard_version() != expected.version:
                return False
        if not user32.EmptyClipboard():
            return False
        for _ in range(4):
            if user32.SetClipboardData(CF_UNICODETEXT, handle):
                committed = True
                return True
            time.sleep(0.005)
        return False
    finally:
        user32.CloseClipboard()
        destroy(owner)
        if not committed:
            kernel32.GlobalFree(handle)


def _has_non_text_clipboard_data() -> bool:
    return any(user32.IsClipboardFormatAvailable(fmt) for fmt in (CF_HDROP, CF_DIB, CF_BITMAP))


def _key(vk: int, flags: int = 0) -> INPUT:
    event = INPUT()
    event.type = INPUT_KEYBOARD
    event.ki = KEYBDINPUT(vk, 0, flags, 0, None)
    return event


def _send_inputs(events: list[INPUT]) -> bool:
    if not events:
        return True
    array = (INPUT * len(events))(*events)
    sent = user32.SendInput(len(events), array, ctypes.sizeof(INPUT))
    return sent == len(events)


def send_ctrl_c() -> bool:
    events = [_key(VK_CONTROL), _key(VK_C), _key(VK_C, KEYEVENTF_KEYUP), _key(VK_CONTROL, KEYEVENTF_KEYUP)]
    return _send_inputs(events)


_MODIFIER_VKS = (0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5)
_CTRL_VKS = (VK_CONTROL, 0xA2, 0xA3)


def _modifier_down() -> bool:
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in _MODIFIER_VKS)


def _held_modifiers() -> tuple[int, ...]:
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    return tuple(vk for vk in _MODIFIER_VKS if user32.GetAsyncKeyState(vk) & 0x8000)


def modifiers_clear(timeout: float = 0.35) -> bool:
    """Wait until the hotkey chord is actually up. A synthetic key-up is not enough."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _modifier_down():
            return True
        time.sleep(0.01)
    return False


def send_ctrl_c_after_release(held: tuple[int, ...]) -> bool:
    """Release the chord and copy in one batch.

    A separate check after key-up loses to keyboard repeat while the shortcut
    is still physically held, and a lone Alt key-up can open the menu bar.
    """
    others = [_key(vk, KEYEVENTF_KEYUP) for vk in held if vk not in _CTRL_VKS]
    controls = [_key(vk, KEYEVENTF_KEYUP) for vk in held if vk in _CTRL_VKS]
    events = others + controls + [
        _key(VK_CONTROL),
        _key(VK_C),
        _key(VK_C, KEYEVENTF_KEYUP),
        _key(VK_CONTROL, KEYEVENTF_KEYUP),
    ]
    return _send_inputs(events)


def _inject_copy(timeout: float, *, expected_focus: int,
                 expected_clipboard: tuple[int, int]) -> bool:
    """Insert Ctrl+C only as a clean chord. A zero SendInput count is not a copy."""
    clear = modifiers_clear(timeout)
    if focused_hwnd() != expected_focus or _clipboard_version() != expected_clipboard:
        return False
    if clear:
        return send_ctrl_c()
    held = _held_modifiers()
    if not held:
        return send_ctrl_c()
    return send_ctrl_c_after_release(held)


class GUITHREADINFO(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", RECT),
    )


_GetGUIThreadInfo = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD, ctypes.POINTER(GUITHREADINFO))(
    ("GetGUIThreadInfo", user32)
)
_GetWindowThreadProcessId = ctypes.WINFUNCTYPE(
    wintypes.DWORD, wintypes.HWND, ctypes.POINTER(wintypes.DWORD),
)(("GetWindowThreadProcessId", user32))
_SendMessageTimeoutW = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_size_t),
)(("SendMessageTimeoutW", user32))
WM_COPY = 0x0301
SMTO_ABORTIFHUNG = 0x0002


def focused_hwnd() -> int:
    """Focused control of the foreground thread. GetFocus only sees our thread."""
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    if not _GetGUIThreadInfo(0, ctypes.byref(info)):
        return 0
    return int(info.hwndFocus or info.hwndActive or 0)


def _window_process(hwnd: int) -> int:
    pid = wintypes.DWORD()
    if hwnd:
        _GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _await_clipboard(wait_s: float, *, original: tuple[int, int],
                     focus: int, process: int) -> _ClipboardSnapshot | None:
    deadline = time.monotonic() + wait_s
    while True:
        if focused_hwnd() != focus:
            return None
        current = _clipboard_snapshot()
        if current is not None and current.version != original:
            if focused_hwnd() == focus and _window_process(current.version[1]) == process:
                return current
            return None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(0.012, remaining))


class _AutomationReader:
    """Limit a provider call without accumulating hung background threads."""

    def __init__(self, timeout: float = 1.5) -> None:
        self.timeout = timeout
        self._lock = threading.Lock()
        self._pending: Future | None = None

    def read(self) -> tuple[str | None, bool]:
        with self._lock:
            if self._pending is not None and not self._pending.done():
                return None, True
            result = Future()
            self._pending = result

            def run() -> None:
                try:
                    from .uia_win import read_selection

                    result.set_result(read_selection())
                except Exception as exc:
                    result.set_exception(exc)

            threading.Thread(target=run, name="Intext UI Automation", daemon=True).start()
        try:
            return result.result(timeout=self.timeout)
        except TimeoutError:
            from .config import log_error

            log_error("selection: UI Automation timed out")
            # A late provider result must never cause a clipboard or key action.
            return None, True
        except Exception as exc:
            from .config import log_error

            log_error(f"selection: UI Automation failed ({type(exc).__name__})")
            return None, True


_automation_reader = _AutomationReader()


def _automation_selection() -> tuple[str | None, bool]:
    """Read accessible selections with a bounded, non-UI MTA worker."""
    return _automation_reader.read()


def read_selected_text(wait_s: float = 0.6) -> str | None:
    """Read the focused selection without destroying a non-text clipboard."""
    initial_focus = focused_hwnd()
    text, handled = _automation_selection()
    if initial_focus and focused_hwnd() != initial_focus:
        return None
    if handled:
        return text
    original = _clipboard_snapshot(text_only=True)
    process = _window_process(initial_focus)
    if (original is None or not process or focused_hwnd() != initial_focus
            or _clipboard_version() != original.version):
        return None
    result = ctypes.c_size_t()
    returned = _SendMessageTimeoutW(initial_focus, WM_COPY, 0, 0, SMTO_ABORTIFHUNG, 200, ctypes.byref(result))
    captured = _await_clipboard(0 if returned else 0.2, original=original.version,
                                focus=initial_focus, process=process)
    # A timed-out WM_COPY can still write later. Avoid sending a second copy.
    if captured is None and returned:
        for release_timeout, copy_wait in ((0.35, wait_s), (0.2, 0.35)):
            if _inject_copy(release_timeout, expected_focus=initial_focus, expected_clipboard=original.version):
                captured = _await_clipboard(copy_wait + 0.12, original=original.version,
                                            focus=initial_focus, process=process)
                break
    if captured is None:
        return None
    # Restore only the revision produced by the copy. A later user copy
    # between this read and EmptyClipboard must remain on the clipboard.
    if original.text is not None and original.text != captured.text:
        set_clipboard_text(original.text, expected=captured)
    if focused_hwnd() != initial_focus:
        return None
    return (captured.text or "").strip() or None


def parse_hotkey(spec: str) -> tuple[int, int]:
    parts = [part.strip().lower() for part in spec.split("+") if part.strip()]
    if not parts:
        raise ValueError("empty hotkey")
    modifiers = MOD_NOREPEAT
    key = parts[-1]
    for part in parts[:-1]:
        if part == "ctrl":
            modifiers |= MOD_CONTROL
        elif part == "alt":
            modifiers |= MOD_ALT
        elif part == "shift":
            modifiers |= MOD_SHIFT
        elif part == "win":
            modifiers |= MOD_WIN
        else:
            raise ValueError(f"unknown modifier: {part}")
    vk = VK.get(key.upper())
    if vk is None:
        raise ValueError(f"unsupported hotkey key: {key}")
    return modifiers, vk


_bind()


def set_app_id() -> None:
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Intext.App")
    except Exception:
        return


def _theme_flag(name: str, default: bool = True) -> bool:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, name)
        return bool(value)
    except OSError:
        return default


def system_uses_light_theme() -> bool:
    return _theme_flag("SystemUsesLightTheme")


def apps_use_light_theme() -> bool:
    return _theme_flag("AppsUseLightTheme")


def small_icon_size() -> int:
    SM_CXSMICON = 49
    try:
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowW.restype = wintypes.HWND
        user32.GetDpiForWindow.argtypes = [wintypes.HWND]
        user32.GetDpiForWindow.restype = wintypes.UINT
        user32.GetDpiForSystem.restype = wintypes.UINT
        user32.GetSystemMetricsForDpi.argtypes = [ctypes.c_int, wintypes.UINT]
        user32.GetSystemMetricsForDpi.restype = ctypes.c_int
        taskbar = user32.FindWindowW("Shell_TrayWnd", None)
        dpi = user32.GetDpiForWindow(taskbar) if taskbar else 0
        size = user32.GetSystemMetricsForDpi(SM_CXSMICON, dpi or user32.GetDpiForSystem())
        if size:
            return int(size)
    except Exception:
        pass
    size = user32.GetSystemMetrics(SM_CXSMICON)
    return int(size or 16)


def load_icon(path: str, size: int):
    LR_LOADFROMFILE = 0x0010
    IMAGE_ICON = 1
    user32.LoadImageW.argtypes = [
        wintypes.HINSTANCE,
        wintypes.LPCWSTR,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.LoadImageW.restype = wintypes.HANDLE
    return user32.LoadImageW(None, path, IMAGE_ICON, size, size, LR_LOADFROMFILE)


def destroy_icon(handle) -> None:
    if handle:
        user32.DestroyIcon.argtypes = [wintypes.HICON]
        user32.DestroyIcon.restype = wintypes.BOOL
        user32.DestroyIcon(handle)


class _FrameMargins(ctypes.Structure):
    _fields_ = (
        ("left", ctypes.c_int),
        ("right", ctypes.c_int),
        ("top", ctypes.c_int),
        ("bottom", ctypes.c_int),
    )


def enable_window_transparency(hwnd: int) -> None:
    """Composite a transparent tool window with the desktop, not a Form fill.

    The caller supplies a black GDI backing and a transparent WebView2 base.
    https://learn.microsoft.com/windows/win32/api/dwmapi/nf-dwmapi-dwmextendframeintoclientarea
    """
    # Keep this signature independent of pywebview's cached ctypes binding.
    extend = ctypes.WinDLL("dwmapi").DwmExtendFrameIntoClientArea
    extend.argtypes = [wintypes.HWND, ctypes.POINTER(_FrameMargins)]
    extend.restype = wintypes.LONG
    margins = _FrameMargins(-1, -1, -1, -1)
    result = extend(hwnd, ctypes.byref(margins))
    if result != 0:
        raise OSError(result, "窗口透明合成初始化失败")


def smooth_window_corners(hwnd: int, light: bool) -> None:
    """Attach a smooth composited corner. See smooth_frame for why."""
    from .smooth_frame import attach_smooth_frame

    attach_smooth_frame(int(hwnd), bool(light))


def set_taskbar_button(hwnd: int, visible: bool) -> None:
    """Show a taskbar button only while the settings window is open.

    ShowInTaskbar recreates the form and drops the WebView, so this only
    changes the extended style of the existing window.
    """
    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_APPWINDOW = 0x00040000
    flags = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long
    style = int(user32.GetWindowLongW(hwnd, GWL_EXSTYLE))
    if visible:
        cleaned = (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
    else:
        cleaned = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
    if cleaned == style:
        return
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, cleaned)
    _SetWindowPos(hwnd, 0, 0, 0, 0, 0, flags)


def move_window(hwnd: int, x: int, y: int) -> None:
    """Move without touching pywebview's SetWindowPos binding."""
    if not hwnd:
        return
    _SetWindowPos(hwnd, 0, int(x), int(y), 0, 0, 0x0001 | 0x0004 | 0x0040)


_instance_mutex = None


def claim_instance() -> bool:
    global _instance_mutex
    ERROR_ALREADY_EXISTS = 183
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.GetLastError.restype = wintypes.DWORD
    _instance_mutex = kernel32.CreateMutexW(None, False, "Local\\Intext.Instance")
    return kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def signal_running_instance() -> bool:
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    for _ in range(50):
        hwnd = user32.FindWindowW("IntextShell", "Intext")
        if hwnd:
            user32.PostMessageW(hwnd, 0x8002, 0, 0)
            return True
        time.sleep(0.05)
    return False


_RESIZE_EDGES = {"n", "s", "e", "w", "ne", "nw", "se", "sw"}


def logical_work_size() -> tuple[int, int]:
    """Primary work area in logical pixels. Falls back to a normal laptop size."""
    try:
        user32.MonitorFromPoint.restype = wintypes.HANDLE
        monitor = user32.MonitorFromPoint(POINT(0, 0), 1)
        class MONITORINFO(ctypes.Structure):
            _fields_ = (
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", wintypes.DWORD),
            )

        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return (1280, 800)
        work_w = int(info.rcWork.right - info.rcWork.left)
        work_h = int(info.rcWork.bottom - info.rcWork.top)
        dpi = 96
        try:
            shcore = ctypes.windll.shcore
            shcore.GetDpiForMonitor.argtypes = [
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.POINTER(wintypes.UINT),
                ctypes.POINTER(wintypes.UINT),
            ]
            shcore.GetDpiForMonitor.restype = ctypes.c_long
            dx = wintypes.UINT()
            dy = wintypes.UINT()
            if shcore.GetDpiForMonitor(monitor, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0 and dx.value:
                dpi = int(dx.value)
        except Exception:
            dpi = 96
        scale = max(1.0, dpi / 96.0)
        return max(1, int(work_w / scale)), max(1, int(work_h / scale))
    except Exception:
        return (1280, 800)


def _button_down() -> bool:
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    return bool(user32.GetAsyncKeyState(0x01) & 0x8000)


def begin_form_resize(form, edge: str, on_finished=None, *, minimum=None) -> None:
    """Resize a frameless form from an edge. The page only starts the drag.

    A UI timer reads the cursor, so the webview does not have to forward every
    move across the script bridge. Releasing the mouse ends it even if the
    pointer has left the window.
    """
    edge = str(edge or "")
    if edge not in _RESIZE_EDGES:
        return
    previous = getattr(form, "_intext_resize", None)
    end_form_resize(form)
    if previous and previous.get("timer") is not None:
        try:
            previous["timer"].Dispose()
        except Exception:
            pass
    from System.Drawing import Rectangle
    from System.Windows.Forms import Cursors, Cursor, Timer
    from .geometry import MINIMUM_SETTINGS
    minimum = minimum or MINIMUM_SETTINGS

    scale = 1.0
    try:
        scale = float(form._scale) or 1.0
    except Exception:
        scale = 1.0
    bounds = form.Bounds
    state = {
        "done": False,
        "edge": edge,
        "changed": False,
        "scale": scale,
        "sx": int(Cursor.Position.X),
        "sy": int(Cursor.Position.Y),
        "left": int(bounds.Left),
        "top": int(bounds.Top),
        "right": int(bounds.Right),
        "bottom": int(bounds.Bottom),
        "on_finished": on_finished,
        "timer": None,
    }
    cursors = {
        "n": Cursors.SizeNS,
        "s": Cursors.SizeNS,
        "e": Cursors.SizeWE,
        "w": Cursors.SizeWE,
        "ne": Cursors.SizeNESW,
        "sw": Cursors.SizeNESW,
        "nw": Cursors.SizeNWSE,
        "se": Cursors.SizeNWSE,
    }
    try:
        form.Cursor = cursors[edge]
    except Exception:
        pass

    def apply() -> None:
        if state["done"]:
            return
        try:
            if form.IsDisposed:
                finish()
                return
        except Exception:
            finish()
            return
        pos = Cursor.Position
        dx = int(pos.X) - state["sx"]
        dy = int(pos.Y) - state["sy"]
        left, top = state["left"], state["top"]
        right, bottom = state["right"], state["bottom"]
        current = state["edge"]
        if "w" in current:
            left += dx
        if "e" in current:
            right += dx
        if "n" in current:
            top += dy
        if "s" in current:
            bottom += dy
        min_w = max(int(form.MinimumSize.Width), int(minimum[0] * scale))
        min_h = max(int(form.MinimumSize.Height), int(minimum[1] * scale))
        if right - left < min_w:
            if "w" in current:
                left = right - min_w
            else:
                right = left + min_w
        if bottom - top < min_h:
            if "n" in current:
                top = bottom - min_h
            else:
                bottom = top + min_h
        cx = (left + right) // 2
        cy = (top + bottom) // 2
        wl, wt, wr, wb = work_area_at(cx, cy)
        max_w = max(min_w, wr - wl - 8)
        max_h = max(min_h, wb - wt - 8)
        if right - left > max_w:
            if "w" in current:
                left = right - max_w
            else:
                right = left + max_w
        if bottom - top > max_h:
            if "n" in current:
                top = bottom - max_h
            else:
                bottom = top + max_h
        width = max(1, right - left)
        height = max(1, bottom - top)
        if int(form.Bounds.Width) == width and int(form.Bounds.Height) == height and int(form.Bounds.Left) == left and int(form.Bounds.Top) == top:
            return
        form.Bounds = Rectangle(left, top, width, height)
        state["changed"] = True

    def tick(_sender, _args) -> None:
        try:
            if not _button_down():
                end_form_resize(form)
                return
            apply()
        except Exception:
            end_form_resize(form)

    timer = Timer()
    timer.Interval = 16
    timer.Tick += tick
    state["timer"] = timer
    state["tick"] = tick
    form._intext_resize = state
    timer.Start()


def end_form_resize(form) -> None:
    state = getattr(form, "_intext_resize", None)
    if not state or state.get("done"):
        return
    state["done"] = True
    timer = state.get("timer")
    tick = state.get("tick")
    if timer is not None:
        try:
            timer.Stop()
        except Exception:
            pass
        if tick is not None:
            try:
                timer.Tick -= tick
            except Exception:
                pass
        try:
            timer.Dispose()
        except Exception:
            pass
        state["timer"] = None
    try:
        from System.Windows.Forms import Cursors

        form.Cursor = Cursors.Default
    except Exception:
        pass
    callback = state.get("on_finished")
    if state.get("changed") and callback is not None:
        scale = state.get("scale") or 1.0
        try:
            callback(max(1, int(round(form.Width / scale))), max(1, int(round(form.Height / scale))))
        except Exception:
            return


def begin_form_drag(form) -> None:
    """Let Windows move the frameless window.

    A timer that assigns Bounds every 16ms fights the WebView and, on the
    settings page, the rounded rim. ReleaseCapture plus a caption drag is the
    same path a normal title bar uses, so the move stays on the system loop.
    """
    end_form_resize(form)
    hwnd = int(form.Handle.ToInt64())
    release = ctypes.WINFUNCTYPE(wintypes.BOOL)(("ReleaseCapture", user32))
    send = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )(("SendMessageW", user32))
    form._intext_dragging = True
    try:
        release()
        send(hwnd, 0x00A1, 2, 0)  # WM_NCLBUTTONDOWN, HTCAPTION
    finally:
        form._intext_dragging = False


WH_MOUSE_LL = 14
_CLICK_DOWN = (0x0201, 0x0204, 0x0207, 0x00A1, 0x00A4, 0x00A7)
_OUTSIDE_HOOK = None
_OUTSIDE_PROC = None
_OUTSIDE_CALLBACK = None


class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = (
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    )


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """Read a window rectangle without sharing GetWindowRect's global argtypes.

    smooth_frame binds that function to its own RECT type. Reusing it from the
    click hook raises ArgumentError, and the exception was swallowed, so an
    outside click never closed the popup.
    """
    if not hwnd:
        return None
    rect = RECT()
    getter = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, ctypes.POINTER(RECT))(
        ("GetWindowRect", user32)
    )
    if not getter(hwnd, ctypes.byref(rect)):
        return None
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


def install_outside_click_hook(callback) -> bool:
    """Report mouse clicks. The shell thread already runs a message loop."""
    global _OUTSIDE_HOOK, _OUTSIDE_PROC, _OUTSIDE_CALLBACK
    _OUTSIDE_CALLBACK = callback
    if _OUTSIDE_HOOK:
        return True
    hook_proc = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    call_next = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t, wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
    )(("CallNextHookEx", user32))
    set_hook = ctypes.WINFUNCTYPE(
        wintypes.HHOOK, ctypes.c_int, hook_proc, wintypes.HINSTANCE, wintypes.DWORD
    )(("SetWindowsHookExW", user32))

    def proc(code, wparam, lparam):
        if code >= 0 and int(wparam) in _CLICK_DOWN and _OUTSIDE_CALLBACK is not None:
            try:
                info = ctypes.cast(lparam, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
                _OUTSIDE_CALLBACK(int(info.pt.x), int(info.pt.y))
            except Exception:
                pass
        return call_next(_OUTSIDE_HOOK, code, wparam, lparam)

    _OUTSIDE_PROC = hook_proc(proc)
    _OUTSIDE_HOOK = set_hook(WH_MOUSE_LL, _OUTSIDE_PROC, None, 0)
    if not _OUTSIDE_HOOK:
        try:
            from .config import log_error
            log_error(f"outside-click hook failed {ctypes.get_last_error()}")
        except Exception:
            pass
    return bool(_OUTSIDE_HOOK)


def uninstall_outside_click_hook() -> bool:
    """Called on the installing message-loop thread when no popup needs it."""
    global _OUTSIDE_HOOK, _OUTSIDE_PROC, _OUTSIDE_CALLBACK
    if _OUTSIDE_HOOK:
        unhook = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HHOOK)(("UnhookWindowsHookEx", user32))
        if not unhook(_OUTSIDE_HOOK):
            from .config import log_error
            log_error(f"outside-click unhook failed {ctypes.get_last_error()}")
            _OUTSIDE_CALLBACK = None
            return False
    _OUTSIDE_HOOK = _OUTSIDE_PROC = _OUTSIDE_CALLBACK = None
    return True
