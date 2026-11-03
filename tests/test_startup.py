import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from intext import startup
from intext.__main__ import _run_gui
from intext.app import settings_visible_on_launch
from intext.geometry import tray_menu_position


class FakeRegistry:
    HKEY_CURRENT_USER = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        self.values = {"Another App": ("unrelated.exe", self.REG_SZ)}

    def OpenKey(self, *args):
        return self

    CreateKeyEx = OpenKey

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name]

    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[name] = (value, kind)

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


class StartupTests(unittest.TestCase):
    def test_option_round_trip_only_changes_our_entry(self):
        registry = FakeRegistry()
        with patch.dict(sys.modules, {"winreg": registry}):
            self.assertFalse(startup.is_enabled())
            self.assertTrue(startup.set_enabled(True))
            self.assertEqual(registry.values['Intext'][0], startup.startup_command())
            self.assertTrue(registry.values['Intext'][0].endswith(' --silent'))
            self.assertFalse(startup.set_enabled(False))
            self.assertFalse(startup.set_enabled(False))
        self.assertEqual(registry.values, {"Another App": ("unrelated.exe", 1)})

    def test_failed_registry_write_is_not_reported_as_enabled(self):
        registry = FakeRegistry()
        registry.SetValueEx = lambda *args: None
        with patch.dict(sys.modules, {"winreg": registry}):
            with self.assertRaises(OSError):
                startup.set_enabled(True)

    def test_frozen_command_quotes_executable_with_spaces(self):
        path = str(Path(tempfile.gettempdir()) / 'Intext app' / 'Intext.exe')
        with patch.object(sys, 'executable', path), patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(startup.startup_command(), subprocess.list2cmdline([str(Path(path).resolve()), '--silent']))

    def test_development_startup_uses_pythonw_without_console(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / 'pythonw.exe').touch()
            with patch.object(sys, 'executable', str(path / 'python.exe')), patch.object(sys, 'frozen', False, create=True):
                command = startup.startup_command()
            self.assertIn('pythonw.exe', command)
            self.assertIn('launch.py', command)
            self.assertTrue(command.endswith(' --silent'))

    def test_silent_start_hides_even_unconfigured_or_explicit_settings(self):
        self.assertTrue(settings_visible_on_launch(model=''))
        self.assertFalse(settings_visible_on_launch(model='configured'))
        self.assertTrue(settings_visible_on_launch(model='configured', settings_only=True))
        self.assertFalse(settings_visible_on_launch(model='', preview=True))
        for model in ('', 'configured'):
            for settings_only in (True, False):
                self.assertFalse(settings_visible_on_launch(model=model, settings_only=settings_only, silent=True))

    def test_duplicate_silent_start_does_not_raise_the_existing_window(self):
        signal = Mock()
        platform = SimpleNamespace(claim_instance=lambda: False, signal_running_instance=signal)
        with patch.dict(sys.modules, {'intext.platform_win': platform}):
            _run_gui(SimpleNamespace(silent=True, preview=False, settings=False))
            signal.assert_not_called()
            _run_gui(SimpleNamespace(silent=False, preview=False, settings=False))
            signal.assert_called_once()

    def test_tray_menu_prefers_the_right_of_the_trigger(self):
        x, y = tray_menu_position((200, 400), (248, 160), (0, 0, 1200, 800))
        self.assertGreater(x, 200)
        self.assertEqual(y, 240)

    def test_tray_menu_flips_left_when_the_right_side_has_no_room(self):
        x, y = tray_menu_position((1150, 400), (248, 160), (0, 0, 1200, 800))
        self.assertLess(x + 248, 1150)
        self.assertEqual(y, 240)

    def test_tray_menu_clamps_all_screen_edges_and_negative_monitors(self):
        size = (372, 240)
        for work in ((0, 0, 1920, 1040), (-1920, -200, 0, 840)):
            left, top, right, bottom = work
            for point in ((left, top), (right, bottom), (left, bottom), (right, top)):
                x, y = tray_menu_position(point, size, work)
                self.assertGreaterEqual(x, left)
                self.assertGreaterEqual(y, top)
                self.assertLessEqual(x + size[0], right)
                self.assertLessEqual(y + size[1], bottom)
