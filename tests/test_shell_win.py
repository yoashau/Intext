import sys
import unittest
from unittest.mock import Mock, patch


@unittest.skipUnless(sys.platform == 'win32', 'requires Windows tray APIs')
class ShellTests(unittest.TestCase):
    def setUp(self):
        from intext import shell_win

        self.module = shell_win
        self.shell = shell_win.Shell(
            hotkey='ctrl+alt+q', tip='Intext', icon_path=lambda: 'fixture.ico',
            on_hotkey=Mock(), on_open=Mock(), on_quit=Mock(),
        )

    def test_taskbar_recreation_adds_the_icon_again(self):
        self.assertGreater(self.shell._taskbar_created, 0)
        with patch.object(self.shell, '_add_icon') as add:
            result = self.shell._wndproc(0, self.shell._taskbar_created, 0, 0)
        self.assertEqual(result, 0)
        add.assert_called_once()

    def test_readding_icon_releases_the_old_handle_and_keeps_notification_version(self):
        self.shell.hwnd = 123
        self.shell._icon = 10
        with patch.object(self.module, 'small_icon_size', return_value=16), \
             patch.object(self.module, 'load_tray_icon', return_value=20), \
             patch.object(self.module, 'destroy_icon') as destroy, \
             patch.object(self.module.shell32, 'Shell_NotifyIconW', return_value=True) as notify:
            self.shell._add_icon()
        self.assertEqual(self.shell._icon, 20)
        destroy.assert_called_once_with(10)
        self.assertEqual([call.args[0] for call in notify.call_args_list],
                         [self.module.NIM_ADD, self.module.NIM_SETVERSION])

    def test_readding_can_reuse_the_existing_icon_when_loading_fails(self):
        self.shell._icon = 10
        with patch.object(self.module, 'small_icon_size', return_value=16), \
             patch.object(self.module, 'load_tray_icon', return_value=None), \
             patch.object(self.module, 'destroy_icon') as destroy, \
             patch.object(self.module.shell32, 'Shell_NotifyIconW', return_value=True):
            self.shell._add_icon()
        self.assertEqual(self.shell._icon, 10)
        destroy.assert_not_called()
