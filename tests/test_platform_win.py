import sys
import unittest
from unittest.mock import patch


@unittest.skipUnless(sys.platform == "win32", "requires Windows APIs")
class WindowsSelectionTests(unittest.TestCase):
    def setUp(self):
        from intext import platform_win
        self.platform = platform_win

    def test_function_keys_match_the_keys_settings_can_record(self):
        for number in range(1, 13):
            _, vk = self.platform.parse_hotkey(f"ctrl+alt+f{number}")
            self.assertEqual(vk, 0x70 + number - 1)

    def test_accessible_selection_does_not_touch_clipboard(self):
        with patch.object(self.platform, "_automation_selection", return_value=("selected", True)):
            with patch.object(self.platform, "clipboard_safe_to_replace") as clipboard:
                self.assertEqual(self.platform.read_selected_text(), "selected")
            clipboard.assert_not_called()

    def test_password_control_does_not_fall_back_to_copy(self):
        with patch.object(self.platform, "_automation_selection", return_value=(None, True)):
            with patch.object(self.platform, "clipboard_safe_to_replace") as clipboard:
                self.assertIsNone(self.platform.read_selected_text())
            clipboard.assert_not_called()

    def test_unsupported_control_keeps_image_clipboard_untouched(self):
        with patch.object(self.platform, "_automation_selection", return_value=(None, False)):
            with patch.object(self.platform, "clipboard_safe_to_replace", return_value=False):
                with patch.object(self.platform, "copy_focused_control") as copy:
                    self.assertIsNone(self.platform.read_selected_text())
                copy.assert_not_called()

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
