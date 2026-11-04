"""Capture the installed lasso above an owned synthetic desktop; always cancel.

No user image, configuration or translation request is used by this probe.
"""
from __future__ import annotations

import ctypes
import json
import math
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'src'))
    from PIL import Image
    from intext.platform_win import enable_dpi_awareness
    enable_dpi_awareness()
    from intext import capture_win as c
    user = c.user32
    enum_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [enum_type, wintypes.LPARAM]
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user.mouse_event.argtypes = [wintypes.DWORD]*4 + [ctypes.c_size_t]
    user.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]

    def find(prefix, pid=None):
        found = []
        def visit(hwnd, _):
            owner = wintypes.DWORD()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            name = ctypes.create_unicode_buffer(128)
            user.GetClassNameW(hwnd, name, len(name))
            if name.value.startswith(prefix) and (pid is None or owner.value == pid):
                found.append((hwnd, owner.value))
            return True
        user.EnumWindows(enum_type(visit), 0)
        return found

    def wait_for(predicate):
        deadline = time.monotonic()+5
        while time.monotonic()<deadline:
            value = predicate()
            if value:
                return value
            time.sleep(.01)
        raise TimeoutError('Installed lasso fixture')

    shell, app_pid = wait_for(lambda: find('IntextShell'))[0]
    rect = c.virtual_screen()
    previous = user.GetForegroundWindow()
    cursor = wintypes.POINT()
    user.GetCursorPos(ctypes.byref(cursor))
    ready, canvas, errors = threading.Event(), [], []

    def backdrop():
        surface = c._Surface(rect[2:], Image.new('RGB', rect[2:], (250, 230, 210)).tobytes('raw', 'BGRX'))
        def paint(hwnd, message, wparam, lparam):
            if message == 0x000f:
                ps = c.PAINTSTRUCT()
                dc = user.BeginPaint(hwnd, ctypes.byref(ps))
                c.gdi32.BitBlt(dc, 0, 0, *rect[2:], surface.dc, 0, 0, 0x00CC0020)
                user.EndPaint(hwnd, ctypes.byref(ps))
                return 0
            if message == 0x0014:
                return 1
            if message == 0x0002:
                user.PostQuitMessage(0)
                return 0
            return user.DefWindowProcW(hwnd, message, wparam, lparam)
        proc = c.WNDPROC(paint)
        instance = c.kernel32.GetModuleHandleW(None)
        name = 'IntextSyntheticBackdrop'
        cls = c.WNDCLASSW(lpfnWndProc=proc, hInstance=instance, lpszClassName=name)
        try:
            if not user.RegisterClassW(ctypes.byref(cls)):
                raise ctypes.WinError(ctypes.get_last_error())
            hwnd = user.CreateWindowExW(0x88, name, name, 0x80000000, *rect, None, None, instance, None)
            if not hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            canvas.append(hwnd)
            user.ShowWindow(hwnd, 5)
            user.UpdateWindow(hwnd)
            ready.set()
            message = wintypes.MSG()
            while user.GetMessageW(ctypes.byref(message), None, 0, 0)>0:
                user.TranslateMessage(ctypes.byref(message))
                user.DispatchMessageW(ctypes.byref(message))
        except Exception as exc:
            errors.append(str(exc))
            ready.set()
        finally:
            user.UnregisterClassW(name, instance)
            surface.close()

    thread = threading.Thread(target=backdrop, daemon=True)
    thread.start()
    capture = None
    report = {'passed': False}
    try:
        assert ready.wait(5) and canvas and not errors, errors
        user.SetForegroundWindow(canvas[0])
        ctypes.WinDLL('dwmapi').DwmFlush()
        user.PostMessageW(shell, 0x312, 2, 0)
        capture, _ = wait_for(lambda: find('IntextCapture', app_pid))[0]
        points = [(round(420+250*math.cos(a)), round(350+200*math.sin(a)))
                  for a in (2*math.pi*i/240 for i in range(241))]
        user.SetCursorPos(rect[0]+points[0][0], rect[1]+points[0][1])
        time.sleep(.02)
        user.keybd_event(0x11, 0, 0, 0)
        user.mouse_event(0x0002, 0, 0, 0, 0)
        for x, y in points:
            user.SetCursorPos(rect[0]+x, rect[1]+y)
            time.sleep(.005)
        time.sleep(.08)
        assert find('IntextCapture', app_pid)
        image = c.screen_image((rect[0]+100, rect[1]+120, 650, 500))
        colors = image.getcolors(650*500)
        assert colors is not None and len(colors)>32, 'Installed edge remains binary or is an old build'
        assert image.getpixel((320, 230)) == (250, 230, 210), 'Interior hole'
        output = root/'design/lasso-edge-review'
        image.save(output/'installed-curve.png')
        image.crop((390,35,454,67)).resize((512,256), Image.Resampling.NEAREST).save(output/'installed-slope-8x.png')
        # Clear the active gesture before releasing the button, so it cannot
        # finish a screenshot and start a model request.
        user.SendMessageW(capture, 0x001f, 0, 0)
        user.mouse_event(0x0004, 0, 0, 0, 0)
        user.keybd_event(0x11, 0, 0x0002, 0)
        user.PostMessageW(capture, 0x100, 0x1b, 0)
        wait_for(lambda: not find('IntextCapture', app_pid))
        capture = None
        report.update(passed=True, installedEdgeColors=len(colors), cancelledWithoutTranslation=True)
    finally:
        if capture and find('IntextCapture', app_pid):
            user.SendMessageW(capture, 0x001f, 0, 0)
            user.PostMessageW(capture, 0x100, 0x1b, 0)
        user.mouse_event(0x0004, 0, 0, 0, 0)
        user.keybd_event(0x11, 0, 0x0002, 0)
        if canvas:
            user.PostMessageW(canvas[0], 0x10, 0, 0)
        thread.join(3)
        if previous:
            user.SetForegroundWindow(previous)
        user.SetCursorPos(cursor.x, cursor.y)
        (root/'build/installed-lasso-visual.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
