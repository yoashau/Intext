"""Tray icon and global hotkey for the running app.

One hidden window owns both, so a second launch can ask this instance to
open settings instead of starting another hotkey listener.
"""

from __future__ import annotations

import ctypes
import threading
import time
import traceback
from collections.abc import Callable
from ctypes import wintypes

from .platform_win import destroy_icon, parse_hotkey, small_icon_size
from .tray_icon import load_tray_icon

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_NULL = 0x0000
WM_COMMAND = 0x0111
WM_SETTINGCHANGE = 0x001A
WM_THEMECHANGED = 0x031A
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B
WM_HOTKEY = 0x0312
WM_TIMER = 0x0113
ID_HOTKEY_RETRY = 9
ID_ICON_CHECK = 10
WM_OPEN = 0x8002
WM_TRAY = 0x8001
NIF_MESSAGE = 0x0001
NIF_ICON = 0x0002
NIF_TIP = 0x0004
NIF_SHOWTIP = 0x0080
NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIM_SETVERSION = 4
WM_REBIND = 0x8003


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


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON),
    )


def _bind() -> None:
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
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
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
    user32.SetTimer.restype = ctypes.c_size_t
    user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
    user32.KillTimer.restype = wintypes.BOOL
    # Do not rebind GetCursorPos here. A second POINT type makes the popup
    # path raise ArgumentError after this module is imported.
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    shell32.Shell_NotifyIconW.restype = wintypes.BOOL
    kernel32.GetLastError.restype = wintypes.DWORD
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class Shell:
    def __init__(
        self,
        *,
        hotkey: str,
        tip: str,
        icon_path: Callable[[], str],
        on_hotkey: Callable[[], None],
        on_open: Callable[[], None],
        on_quit: Callable[[], None],
        on_shot: Callable[[], None] | None = None,
        on_menu: Callable[[int, int], None] | None = None,
        shot_hotkey: str = "ctrl+alt+e",
        on_theme: Callable[[], None] | None = None,
        on_hotkeys: Callable[[dict], None] | None = None,
        on_outside_click: Callable[[int, int], None] | None = None,
    ) -> None:
        self.hotkey = hotkey
        self.shot_hotkey = shot_hotkey
        self.tip = tip
        self.icon_path = icon_path
        self.on_hotkey = on_hotkey
        self.on_shot = on_shot or (lambda: None)
        self.on_menu = on_menu
        self.on_open = on_open
        self.on_quit = on_quit
        self.on_theme = on_theme
        self.on_hotkeys = on_hotkeys
        self.on_outside_click = on_outside_click
        self._lock = threading.Lock()
        self._rebind = None
        self._shot_ready = False
        self.hwnd = None
        self._proc = WNDPROC(self._wndproc)
        self._class = "IntextShell"
        self._icon = None
        self._icon_size = 0
        self._nid = NOTIFYICONDATAW()
        self._hotkey_ready = False
        self._registered_hotkey = None
        self._registered_shot = None
        self._hotkey_error = ""
        self._shot_error = ""
        self._hotkey_code = 0
        self._shot_code = 0
        self._retry_armed = False
        self._published = None
        self._logged_state = None
        self._thread_id = None
        self._stopped = threading.Event()

    def run(self) -> None:
        self._thread_id = threading.get_ident()
        instance = kernel32.GetModuleHandleW(None)
        window_class = WNDCLASSW()
        window_class.lpfnWndProc = self._proc
        window_class.hInstance = instance
        window_class.lpszClassName = self._class
        user32.RegisterClassW(ctypes.byref(window_class))
        self.hwnd = user32.CreateWindowExW(
            0,
            self._class,
            "Intext",
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            instance,
            None,
        )
        if not self.hwnd:
            raise OSError("无法创建托盘窗口")
        self._add_icon()
        user32.SetTimer(self.hwnd, ID_ICON_CHECK, 3000, None)
        self._register()
        if self.on_outside_click is not None:
            from .platform_win import install_outside_click_hook

            install_outside_click_hook(self.on_outside_click)
        message = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) != 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            user32.UnregisterHotKey(self.hwnd, 1)
            user32.UnregisterHotKey(self.hwnd, 2)
            self._remove_icon()
            if self.hwnd:
                user32.DestroyWindow(self.hwnd)
            self._stopped.set()


    def update_hotkeys(self, hotkey: str, shot_hotkey: str) -> dict[str, str]:
        done = threading.Event()
        box: dict[str, str] = {}
        with self._lock:
            self._rebind = (hotkey, shot_hotkey, done, box)
        if not self.hwnd:
            self.hotkey = hotkey
            self.shot_hotkey = shot_hotkey
            self._hotkey_error = "注册失败"
            self._shot_error = "注册失败"
            return self.errors()
        user32.PostMessageW(self.hwnd, WM_REBIND, 0, 0)
        if not done.wait(2):
            return {"hotkeyError": "注册失败", "shotHotkeyError": "注册失败"}
        return {
            "hotkeyError": box.get("hotkeyError", ""),
            "shotHotkeyError": box.get("shotHotkeyError", ""),
        }

    def errors(self) -> dict[str, str]:
        return {"hotkeyError": self._hotkey_error, "shotHotkeyError": self._shot_error}

    def hotkey_state(self) -> dict[str, str]:
        return {
            "hotkey": self.hotkey,
            "shotHotkey": self.shot_hotkey,
            "hotkeyError": self._hotkey_error,
            "shotHotkeyError": self._shot_error,
        }

    def _finish_rebind(self) -> None:
        with self._lock:
            item = self._rebind
            self._rebind = None
        if not item:
            return
        hotkey, shot_hotkey, done, box = item
        box.update(self._swap_hotkeys(hotkey, shot_hotkey))
        done.set()

    def _swap_hotkeys(self, hotkey: str, shot_hotkey: str) -> dict[str, str]:
        # Keep the shortcut the user chose. Reverting would make the box show a
        # working key while the failure belonged to the one they just set.
        self.hotkey = hotkey
        self.shot_hotkey = shot_hotkey
        self._register()
        return self.errors()

    def _ensure_hotkey(self, ident: int, spec: str, kind: str) -> tuple[str, int]:
        registered = self._registered_hotkey if kind == "hotkey" else self._registered_shot
        ready = self._hotkey_ready if kind == "hotkey" else self._shot_ready
        if ready and registered == spec:
            return "", 0
        if self.hwnd:
            user32.UnregisterHotKey(self.hwnd, ident)
        error, code = self._register_one(ident, spec)
        if kind == "hotkey":
            self._registered_hotkey = None if error else spec
        else:
            self._registered_shot = None if error else spec
        return error, code

    def _register(self, pause: bool = True) -> None:
        self._hotkey_error, self._hotkey_code = self._ensure_hotkey(1, self.hotkey, "hotkey")
        self._shot_error, self._shot_code = self._ensure_hotkey(2, self.shot_hotkey, "shot")
        if pause and (self._hotkey_error or self._shot_error):
            time.sleep(0.2)
            if self._hotkey_error:
                self._hotkey_error, self._hotkey_code = self._register_one(1, self.hotkey)
            if self._shot_error:
                self._shot_error, self._shot_code = self._register_one(2, self.shot_hotkey)
        self._hotkey_ready = not self._hotkey_error
        self._shot_ready = not self._shot_error
        self._registered_hotkey = None if self._hotkey_error else self.hotkey
        self._registered_shot = None if self._shot_error else self.shot_hotkey
        self._commit_registration()

    def _register_one(self, ident: int, spec: str) -> tuple[str, int]:
        from .hotkey import registration_failure

        try:
            modifiers, vk = parse_hotkey(spec)
        except ValueError:
            return "无效", 0
        if not self.hwnd:
            return "注册失败", 0
        if user32.RegisterHotKey(self.hwnd, ident, modifiers, vk):
            return "", 0
        code = int(kernel32.GetLastError())
        return registration_failure(code), code

    def _commit_registration(self) -> None:
        state = self.hotkey_state()
        if state != self._published:
            self._published = dict(state)
            self._log_registration()
            callback = self.on_hotkeys
            if callback is not None:
                try:
                    callback(dict(state))
                except Exception:
                    from .config import log_error
                    import traceback

                    log_error(traceback.format_exc())
        self._arm_retry()

    def _log_registration(self) -> None:
        from .config import log_error

        signature = (self.hotkey, self.shot_hotkey, self._hotkey_error, self._shot_error)
        if signature == self._logged_state:
            return
        self._logged_state = signature
        if self._hotkey_error or self._shot_error:
            if self._hotkey_error:
                log_error(f"无法注册划词热键 {self.hotkey}：{self._hotkey_error} ({self._hotkey_code})")
            if self._shot_error:
                log_error(f"无法注册截图热键 {self.shot_hotkey}：{self._shot_error} ({self._shot_code})")
            return
        log_error(f"hotkey-ready {self.hotkey} {self.shot_hotkey}")

    def _arm_retry(self) -> None:
        if not self.hwnd:
            return
        failed = bool(self._hotkey_error or self._shot_error)
        if failed and not self._retry_armed:
            user32.SetTimer(self.hwnd, ID_HOTKEY_RETRY, 2000, None)
            self._retry_armed = True
        elif not failed and self._retry_armed:
            user32.KillTimer(self.hwnd, ID_HOTKEY_RETRY)
            self._retry_armed = False

    def _add_icon(self) -> None:
        self._icon_size = small_icon_size()
        self._icon = load_tray_icon(self.icon_path(), self._icon_size)
        nid = self._nid
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self._icon or 0
        nid.szTip = self.tip[:127]
        nid.uVersion = 3
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(nid))

    def _replace_icon(self) -> None:
        previous = self._icon
        size = small_icon_size()
        icon = load_tray_icon(self.icon_path(), size)
        if not icon:
            return
        self._nid.hIcon = icon
        self._nid.uFlags = NIF_ICON
        if not shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid)):
            self._nid.hIcon = previous or 0
            destroy_icon(icon)
            return
        self._icon = icon
        self._icon_size = size
        destroy_icon(previous)

    def _remove_icon(self) -> None:
        if self.hwnd:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
        destroy_icon(self._icon)
        self._icon = None

    def _menu(self) -> None:
        if self.on_menu is None:
            return
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        self.on_menu(point.x, point.y)

    def stop(self) -> None:
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            if threading.get_ident() != self._thread_id:
                self._stopped.wait(1)

    def _wndproc(self, hwnd, message, wparam, lparam) -> int:
        try:
            if message == WM_TRAY and lparam in (WM_LBUTTONUP, WM_RBUTTONUP, WM_CONTEXTMENU):
                if lparam == WM_LBUTTONUP:
                    self.on_open()
                else:
                    self._menu()
                return 0
            if message == WM_TIMER and wparam == ID_HOTKEY_RETRY:
                self._register(pause=False)
                return 0
            if message == WM_TIMER and wparam == ID_ICON_CHECK:
                if small_icon_size() != self._icon_size:
                    self._replace_icon()
                return 0
            if message == WM_HOTKEY:
                from .config import log_error
                from .platform_win import allow_foreground

                log_error(f"wm-hotkey {int(wparam)}")
                try:
                    allow_foreground()
                except Exception:
                    log_error(traceback.format_exc())
                if wparam == 2:
                    self.on_shot()
                else:
                    self.on_hotkey()
                return 0
            if message == WM_REBIND:
                self._finish_rebind()
                return 0
            if message == WM_OPEN:
                self.on_open()
                return 0
            if message in (WM_SETTINGCHANGE, WM_THEMECHANGED):
                self._replace_icon()
                if self.on_theme is not None:
                    self.on_theme()
                return 0
            if message == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            from .config import log_error

            log_error(traceback.format_exc())
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)


_current: Shell | None = None


def current_shell() -> Shell | None:
    return _current


def run_shell(**kwargs) -> Shell:
    global _current
    shell = Shell(**kwargs)
    _current = shell
    try:
        shell.run()
    finally:
        if _current is shell:
            _current = None
    return shell


_bind()
