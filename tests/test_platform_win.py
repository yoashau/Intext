import sys
import unittest
from unittest.mock import patch


@unittest.skipUnless(sys.platform == "win32", "requires Windows APIs")
class WindowsSelectionTests(unittest.TestCase):
    def setUp(self):
        from intext import platform_win
        self.platform = platform_win

    def test_ready_clipboard_is_read_without_a_fixed_initial_delay(self):
        ready = self.platform._ClipboardSnapshot('ready', (2, 100))
        with patch.object(self.platform, '_clipboard_snapshot', return_value=ready), \
             patch.object(self.platform, 'focused_hwnd', return_value=100), \
             patch.object(self.platform, '_window_process', return_value=10), \
             patch.object(self.platform.time, 'sleep') as sleep:
            self.assertEqual(self.platform._await_clipboard(0.6, original=(1, 0), focus=100, process=10), ready)
        sleep.assert_not_called()

    def test_focus_change_while_waiting_for_hotkey_release_cannot_inject_copy(self):
        with patch.object(self.platform, 'modifiers_clear', return_value=True), \
             patch.object(self.platform, 'focused_hwnd', return_value=200), \
             patch.object(self.platform, 'send_ctrl_c') as send, \
             patch.object(self.platform, 'send_ctrl_c_after_release') as release:
            self.assertFalse(self.platform._inject_copy(0.35, expected_focus=100, expected_clipboard=(1, 100)))
        send.assert_not_called()
        release.assert_not_called()

    def test_focus_change_during_clipboard_wait_abandons_stale_text(self):
        with patch.object(self.platform, 'focused_hwnd', return_value=200), \
             patch.object(self.platform, '_clipboard_snapshot') as read:
            self.assertIsNone(self.platform._await_clipboard(0.6, original=(1, 0), focus=100, process=10))
        read.assert_not_called()

    def test_function_keys_match_the_keys_settings_can_record(self):
        for number in range(1, 13):
            _, vk = self.platform.parse_hotkey(f"ctrl+alt+f{number}")
            self.assertEqual(vk, 0x70 + number - 1)

    def test_accessible_selection_does_not_touch_clipboard(self):
        with patch.object(self.platform, "_automation_selection", return_value=("selected", True)):
            with patch.object(self.platform, "_clipboard_snapshot") as clipboard:
                self.assertEqual(self.platform.read_selected_text(), "selected")
            clipboard.assert_not_called()

    def test_password_control_does_not_fall_back_to_copy(self):
        with patch.object(self.platform, "_automation_selection", return_value=(None, True)):
            with patch.object(self.platform, "_clipboard_snapshot") as clipboard:
                self.assertIsNone(self.platform.read_selected_text())
            clipboard.assert_not_called()

    def test_accessibility_timeout_is_bounded_and_recovers_without_extra_workers(self):
        import threading
        import time
        from intext import uia_win

        release = threading.Event()
        started = threading.Event()
        reader = self.platform._AutomationReader(timeout=0.08)

        def stalled():
            started.set()
            release.wait(3)
            return "stale", True

        with patch.object(uia_win, "read_selection", side_effect=stalled) as call, patch("intext.config.log_error"):
            try:
                start = time.monotonic()
                self.assertEqual(reader.read(), (None, True))
                self.assertLess(time.monotonic() - start, 1)
                self.assertTrue(started.is_set())
                self.assertEqual(reader.read(), (None, True))
                self.assertEqual(call.call_count, 1)
            finally:
                release.set()
            deadline = time.monotonic() + 2
            while not reader._pending.done() and time.monotonic() < deadline:
                time.sleep(0.01)
            call.side_effect = None
            call.return_value = ("new selection", True)
            self.assertEqual(reader.read(), ("new selection", True))

    def test_focus_change_during_accessibility_read_cannot_copy_or_translate_stale_text(self):
        with patch.object(self.platform, "focused_hwnd", side_effect=[100, 200]), \
             patch.object(self.platform, "_automation_selection", return_value=("old text", True)), \
             patch.object(self.platform, "_SendMessageTimeoutW") as copy:
            self.assertIsNone(self.platform.read_selected_text())
            copy.assert_not_called()

    def test_native_accessibility_reads_selected_text_and_leaves_empty_caret_alone(self):
        import ctypes
        import threading
        import time
        from ctypes import wintypes

        user = ctypes.WinDLL("user32", use_last_error=True)
        user.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
            wintypes.HINSTANCE, ctypes.c_void_p]
        user.CreateWindowExW.restype = wintypes.HWND
        user.SetFocus.argtypes = [wintypes.HWND]
        user.SetForegroundWindow.argtypes = [wintypes.HWND]
        user.GetForegroundWindow.restype = wintypes.HWND
        user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        previous, ready, windows = user.GetForegroundWindow(), threading.Event(), []

        def create():
            hwnd = user.CreateWindowExW(0, "EDIT", "Intext synthetic text 12345", 0x90000084,
                                        200, 180, 400, 100, None, None, None, None)
            if hwnd:
                windows.append(hwnd)
                user.SetForegroundWindow(hwnd)
                user.SetFocus(hwnd)
            ready.set()
            if not hwnd:
                return
            message = wintypes.MSG()
            while user.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user.TranslateMessage(ctypes.byref(message))
                user.DispatchMessageW(ctypes.byref(message))

        thread = threading.Thread(target=create, daemon=True)
        thread.start()
        try:
            self.assertTrue(ready.wait(5))
            self.assertTrue(windows)
            hwnd = windows[0]
            deadline = time.monotonic() + 2
            while self.platform.focused_hwnd() != hwnd and time.monotonic() < deadline:
                time.sleep(0.02)
            if self.platform.focused_hwnd() != hwnd:
                self.skipTest("the test window could not take foreground focus")
            user.SendMessageW(hwnd, 0x00B1, 0, 6)  # EM_SETSEL
            with patch.object(self.platform, "_clipboard_snapshot") as clipboard:
                self.assertEqual(self.platform.read_selected_text(), "Intext")
                clipboard.assert_not_called()
            user.SendMessageW(hwnd, 0x00B1, 2, 2)
            with patch.object(self.platform, "_clipboard_snapshot") as clipboard:
                self.assertIsNone(self.platform.read_selected_text())
                clipboard.assert_not_called()
        finally:
            if windows:
                user.PostMessageW(windows[0], 0x0010, 0, 0)
            if thread.native_id:
                user.PostThreadMessageW(thread.native_id, 0x0012, 0, 0)
            thread.join(3)
            if previous:
                user.SetForegroundWindow(previous)

    def test_unsupported_control_keeps_image_clipboard_untouched(self):
        with patch.object(self.platform, "_automation_selection", return_value=(None, False)):
            with patch.object(self.platform, "_clipboard_snapshot", return_value=None):
                with patch.object(self.platform, "_SendMessageTimeoutW") as copy:
                    self.assertIsNone(self.platform.read_selected_text())
                copy.assert_not_called()

    def test_only_the_copy_from_the_original_application_is_restored(self):
        platform = self.platform
        original = platform._ClipboardSnapshot(" previous ", (1, 999))
        focus = 100
        current = original

        def copy(_, *_args):
            nonlocal focus, current
            current = platform._ClipboardSnapshot(" selected ", (2, owner))
            focus = focus_after_copy
            return 1

        for owner, focus_after_copy in [(101, 100), (201, 200), (201, 100)]:
            with self.subTest(owner=owner, focus=focus_after_copy):
                focus, current = 100, original
                with patch.object(platform, "_automation_selection", return_value=(None, False)), \
                     patch.object(platform, "focused_hwnd", side_effect=lambda: focus), \
                     patch.object(platform, "_window_process", side_effect=lambda hwnd: hwnd // 100), \
                     patch.object(platform, "_clipboard_snapshot", side_effect=lambda **_: current), \
                     patch.object(platform, "_clipboard_version", side_effect=lambda: current.version), \
                     patch.object(platform, "_SendMessageTimeoutW", side_effect=copy), \
                     patch.object(platform, "modifiers_clear", return_value=True), \
                     patch.object(platform, "send_ctrl_c") as inject, \
                     patch.object(platform, "set_clipboard_text") as restore:
                    if owner == 101:
                        self.assertEqual(platform.read_selected_text(), "selected")
                        restore.assert_called_once_with(" previous ", expected=current)
                    else:
                        self.assertIsNone(platform.read_selected_text())
                        restore.assert_not_called()
                    inject.assert_not_called()

    def test_clipboard_write_checks_revision_after_acquiring_clipboard(self):
        platform = self.platform
        version = (3, 100)

        def acquire(_owner):
            # The user copied again from the same app before we acquired the clipboard.
            nonlocal version
            version = (4, 100)
            return True

        with patch.object(platform, "_open_clipboard", side_effect=acquire), \
             patch.object(platform, "_has_non_text_clipboard_data", return_value=False), \
             patch.object(platform, "_clipboard_version", side_effect=lambda: version), \
             patch.object(platform.user32, "CloseClipboard"), \
             patch.object(platform.user32, "EmptyClipboard") as empty:
            self.assertFalse(platform.set_clipboard_text(
                "previous", expected=platform._ClipboardSnapshot("captured", (3, 100)),
            ))
        empty.assert_not_called()

    def test_ignored_window_copy_falls_back_to_ctrl_c_and_restores_text(self):
        platform = self.platform
        original = platform._ClipboardSnapshot("previous", (1, 999))
        captured = platform._ClipboardSnapshot("selected", (2, 101))
        current = original

        def send():
            nonlocal current
            current = captured
            return True

        with patch.object(platform, "_automation_selection", return_value=(None, False)), \
             patch.object(platform, "focused_hwnd", return_value=100), \
             patch.object(platform, "_window_process", return_value=1), \
             patch.object(platform, "_clipboard_snapshot", side_effect=lambda **_: current), \
             patch.object(platform, "_clipboard_version", side_effect=lambda: current.version), \
             patch.object(platform, "_SendMessageTimeoutW", return_value=1), \
             patch.object(platform, "modifiers_clear", return_value=True), \
             patch.object(platform, "send_ctrl_c", side_effect=send) as inject, \
             patch.object(platform, "set_clipboard_text") as restore:
            self.assertEqual(platform.read_selected_text(), "selected")
        inject.assert_called_once()
        restore.assert_called_once_with("previous", expected=captured)

    def test_clipboard_write_uses_and_releases_a_real_owner_window(self):
        owners = []
        # Refuse the open so this check never modifies the user's clipboard.
        with patch.object(self.platform, "_open_clipboard", side_effect=lambda owner: owners.append(owner) or False):
            self.assertFalse(self.platform.set_clipboard_text("test"))
        self.assertEqual(len(owners), 1)
        self.assertTrue(owners[0])
        self.assertFalse(self.platform.user32.IsWindow(owners[0]))

    def test_transparency_failure_keeps_the_backend_api_binding_unchanged(self):
        import ctypes

        backend_api = ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea
        before = (backend_api.argtypes, backend_api.restype)
        with self.assertRaises(OSError):
            self.platform.enable_window_transparency(0)
        self.assertEqual((backend_api.argtypes, backend_api.restype), before)

    def test_pending_tray_presentation_can_be_dismissed_before_the_host_is_visible(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from intext.app import App

        app = object.__new__(App)
        app._tray_menu = SimpleNamespace(
            native=SimpleNamespace(Visible=False, Handle=SimpleNamespace(ToInt64=lambda: 1)),
            _intext_keep_hidden=False,
        )
        app.hide_tray_menu = Mock()
        with patch.object(self.platform, "window_rect", return_value=(100, 100, 348, 260)):
            app.dismiss_tray_if_outside(10, 10)
        app.hide_tray_menu.assert_called_once()

    def test_mouse_observation_is_only_needed_for_a_visible_dismissible_window(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from intext.app import App
        from intext import shell_win

        app = object.__new__(App)
        app._popup = SimpleNamespace(native=SimpleNamespace(Visible=True))
        app._tray_menu = SimpleNamespace(native=SimpleNamespace(Visible=False), _intext_keep_hidden=True)
        app._popup_requested = True
        app._pinned = app._quitting = app._hold_show = app._preview = False
        shell = Mock()
        with patch.object(shell_win, 'current_shell', return_value=shell):
            app._sync_outside_click_watch()
            self.assertTrue(shell.set_outside_click_enabled.call_args.args[0])
            app._pinned = True
            app._sync_outside_click_watch()
            self.assertFalse(shell.set_outside_click_enabled.call_args.args[0])
            app._tray_menu._intext_keep_hidden = False
            app._sync_outside_click_watch()
            self.assertTrue(shell.set_outside_click_enabled.call_args.args[0])
            app._hold_show = True
            app._sync_outside_click_watch()
            self.assertFalse(shell.set_outside_click_enabled.call_args.args[0])

    def test_only_settings_can_have_a_taskbar_button(self):
        from types import SimpleNamespace
        from intext.app import App

        app = object.__new__(App)
        popup = SimpleNamespace(native=SimpleNamespace(Handle=SimpleNamespace(ToInt64=lambda: 1)))
        settings = SimpleNamespace(native=SimpleNamespace(Handle=SimpleNamespace(ToInt64=lambda: 2)))
        app._popup, app._settings_window = popup, settings
        with patch.object(self.platform, "set_taskbar_button") as taskbar:
            app._sync_taskbar(popup, True)
            app._sync_taskbar(settings, True)
            app._sync_taskbar(settings, False)
        self.assertEqual([call.args for call in taskbar.call_args_list], [(1, False), (2, True), (2, False)])


if __name__ == "__main__":
    unittest.main()
