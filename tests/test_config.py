import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from intext.config import Settings, load_settings, save_settings


class ConfigTests(unittest.TestCase):
    def test_invalid_encoding_is_backed_up_and_startup_can_recover(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            broken = b'\xff\xfeinvalid'
            path.write_bytes(broken)
            with patch("intext.config.log_error"):
                self.assertEqual(load_settings(path).model, "")
            self.assertEqual(path.with_name("config.json.bak").read_bytes(), broken)
            self.assertEqual(load_settings(path).target, "zh")
            self.assertTrue(path.exists())

    def test_windows_bom_preserves_settings_and_nonfinite_size_does_not_abort_startup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text('{"model":"saved","window_width":1e999,"window_height":480}', encoding="utf-8-sig")
            settings = load_settings(path)
            self.assertEqual(settings.model, "saved")
            self.assertEqual(settings.window_width, 0)
            self.assertEqual(settings.window_height, 480)

    def test_failed_save_preserves_previous_config_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            save_settings(Settings(model="saved"), path)
            original = path.read_bytes()
            for operation in ("os.fsync", "os.replace"):
                with self.subTest(operation=operation):
                    with patch("intext.config." + operation, side_effect=OSError("disk unavailable")):
                        with self.assertRaises(OSError):
                            save_settings(Settings(model="new"), path)
                    self.assertEqual(path.read_bytes(), original)
                    self.assertEqual(list(Path(folder).iterdir()), [path])
            self.assertEqual(load_settings(path).model, "saved")
            save_settings(Settings(model="新模型"), path)
            self.assertEqual(load_settings(path).model, "新模型")
