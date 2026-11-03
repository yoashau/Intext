import tempfile
import unittest
from pathlib import Path

from intext.config import Settings, load_settings, save_settings
from intext.geometry import should_dismiss_popup


class DismissTests(unittest.TestCase):
    def test_outside_click_closes_unpinned_popup(self):
        rect = (10, 20, 110, 80)
        self.assertTrue(should_dismiss_popup((0, 40), rect, pinned=False, visible=True))
        self.assertFalse(should_dismiss_popup((40, 40), rect, pinned=False, visible=True))

    def test_pin_and_hidden_window_stay(self):
        rect = (10, 20, 110, 80)
        self.assertFalse(should_dismiss_popup((0, 40), rect, pinned=True, visible=True))
        self.assertFalse(should_dismiss_popup((0, 40), rect, pinned=False, visible=False))
        self.assertFalse(should_dismiss_popup((0, 40), None, pinned=False, visible=True))

    def test_pin_preference_is_remembered(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            save_settings(Settings(pinned=True, model="m"), path)
            loaded = load_settings(path)
            self.assertTrue(loaded.pinned)
            self.assertEqual(loaded.model, "m")
            save_settings(Settings(pinned=False), path)
            self.assertFalse(load_settings(path).pinned)


if __name__ == "__main__":
    unittest.main()
