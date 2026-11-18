"""Validate scoped mouse hooks using an owned Win32 window, without hotkeys."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import threading
import time
import traceback
from ctypes import wintypes
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
    from intext import platform_win as win, shell_win as native
    win.enable_dpi_awareness()
    ready, clicked = threading.Event(), threading.Event()
    callbacks, windows = [], []
    report = {'passed': False, 'checks': []}
    user = win.user32
    user.GetForegroundWindow.restype = wintypes.HWND
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    user.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel = ctypes.WinDLL('kernel32')
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    original_cursor = wintypes.POINT()
    user.GetCursorPos(ctypes.byref(original_cursor))
    foreground = user.GetForegroundWindow()

    def check(value, name):
        if not value:
            raise AssertionError(name)
        report['checks'].append(name)

    def await_state(predicate):
        end = time.monotonic() + 3
        while not predicate():
            if time.monotonic() >= end:
                raise TimeoutError('native hook transition')
            time.sleep(.005)

    def on_click(x, y):
        frame = sys._getframe()
        inside_hook = False
        while frame is not None:
            inside_hook |= frame.f_code.co_name == 'proc' and frame.f_code.co_filename.endswith('platform_win.py')
            frame = frame.f_back
        callbacks.append({'x': x, 'y': y, 'insideHook': inside_hook})
        clicked.set()

    shell = native.Shell(hotkey='ctrl+alt+q', tip='probe', icon_path=lambda: '',
        on_hotkey=lambda: None, on_open=lambda: None, on_quit=lambda: None,
        on_outside_click=on_click)
    shell._class = 'IntextHookProbe' + str(os.getpid())
    shell._add_icon = shell._remove_icon = lambda: None

    def prepare():
        hwnd = user.CreateWindowExW(0, 'STATIC', 'Intext input probe', 0x90000000,
                                    200, 200, 400, 200, shell.hwnd, None, None, None)
        if hwnd:
            windows.append(hwnd)
        ready.set()

    shell._register = prepare  # Do not register or modify the user's hotkeys.
    worker = threading.Thread(target=shell.run, daemon=True)
    worker.start()
    try:
        check(ready.wait(5) and windows, 'owned input window created')
        check(not win._OUTSIDE_HOOK, 'idle shell has no global mouse hook')
        resources = user.GetGuiResources(kernel.GetCurrentProcess(), 1)
        shell.set_outside_click_enabled(True)
        await_state(lambda: shell._outside_active)
        check(bool(win._OUTSIDE_HOOK), 'visible dismissible window enables native hook')
        user.SetCursorPos(380, 280)
        start = time.perf_counter()
        user.mouse_event(2, 0, 0, 0, 0)
        user.mouse_event(4, 0, 0, 0, 0)
        check(clicked.wait(3), 'real click reaches deferred dispatcher')
        report['clickDeliveryMs'] = round((time.perf_counter() - start) * 1000, 3)
        check(not any(c['insideHook'] for c in callbacks), 'application callback runs after low-level hook returns')
        shell.set_outside_click_enabled(False)
        await_state(lambda: not win._OUTSIDE_HOOK)
        count = len(callbacks)
        user.mouse_event(2, 0, 0, 0, 0)
        user.mouse_event(4, 0, 0, 0, 0)
        time.sleep(.05)
        check(len(callbacks) == count, 'hidden or pinned state observes no global clicks')
        for _ in range(20):
            shell.set_outside_click_enabled(True)
            await_state(lambda: shell._outside_active)
            shell.set_outside_click_enabled(False)
            await_state(lambda: not win._OUTSIDE_HOOK)
        check(user.GetGuiResources(kernel.GetCurrentProcess(), 1) <= resources + 2,
              'repeated hook toggles do not accumulate USER handles')
        report['passed'] = True
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        for hwnd in windows:
            user.PostMessageW(hwnd, 0x0010, 0, 0)
        shell.stop()
        worker.join(3)
        user.SetCursorPos(original_cursor.x, original_cursor.y)
        if foreground:
            user.SetForegroundWindow(foreground)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
