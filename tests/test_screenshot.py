import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

from intext.config import Settings, load_settings, save_settings
from intext.screenshot import Selection, freehand_path, lasso_selection, mask_screenshot, rectangle_selection


class ScreenshotTests(unittest.TestCase):
    def test_rectangle_drags_in_all_directions_and_on_negative_monitors(self):
        for start, end in (((10, 20), (110, 120)), ((110, 120), (10, 20)),
                           ((10, 120), (110, 20)), ((110, 20), (10, 120))):
            with self.subTest(start=start, end=end):
                selection = rectangle_selection(start, end, (-1920, -200))
                self.assertEqual(selection.rect, (-1910, -180, 101, 101))
                self.assertEqual(selection.points, ((0, 0), (100, 0), (100, 100), (0, 100)))
        self.assertIsNone(rectangle_selection((10, 10), (17, 40)))

    def test_lasso_keeps_nonrectangular_points_and_negative_monitor_coordinates(self):
        selection = lasso_selection([(10, 20), (110, 20), (10, 120), (10, 20)], (-1920, -200))
        self.assertEqual(selection.rect, (-1910, -180, 101, 101))
        self.assertEqual(selection.points, ((0, 0), (100, 0), (0, 100)))
        self.assertTrue(selection.freehand)

    def test_smooth_path_is_closed_bounded_and_translation_invariant(self):
        raw = [(10, 20), (110, 20), (140, 80), (110, 120), (10, 120)]
        path, kinds = freehand_path(raw)
        self.assertEqual(path[0], path[-1])
        self.assertTrue(kinds[-1] & 0x80)
        self.assertTrue(all(10 <= x <= 140 and 20 <= y <= 120 for x, y in path))
        shifted, shifted_kinds = freehand_path([(x-1920, y-200) for x, y in raw])
        self.assertEqual(kinds, shifted_kinds)
        for (x, y), (sx, sy) in zip(path, shifted):
            self.assertAlmostEqual(x-1920, sx)
            self.assertAlmostEqual(y-200, sy)
        for i, corner in enumerate(raw):
            start, c1, c2, end = path[i*4:i*4+4]
            middle = tuple((start[d]+3*c1[d]+3*c2[d]+end[d])/8 for d in (0, 1))
            self.assertLessEqual(sum((middle[d]-corner[d])**2 for d in (0, 1)), 1.5**2 + 1e-8)

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "requires Pillow")
    def test_freehand_export_antialiases_edges_and_discards_outside_rgb(self):
        from PIL import Image

        selection = lasso_selection([(10, 10), (160, 30), (140, 150), (30, 130)])
        image = mask_screenshot(Image.new("RGB", (180, 180), "black"), selection).image()
        self.assertEqual(image.mode, "RGB")
        self.assertEqual(image.getpixel((70, 70)), (0, 0, 0))
        self.assertEqual(image.getpixel((0, 140)), (255, 255, 255))
        colors = image.getcolors(image.width*image.height)
        self.assertGreater(sum(count for count, color in colors if 0 < color[0] < 255), 50)

    def test_click_line_and_tiny_regions_do_not_finish_selection(self):
        for points in ([], [(1, 1)], [(0, 0), (80, 80)], [(0, 0), (1, 1), (2, 2)], [(0, 0), (7, 0), (0, 7)]):
            self.assertIsNone(lasso_selection(points))

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "requires Pillow")
    def test_pixels_outside_the_lasso_are_discarded_before_encoding(self):
        from PIL import Image

        selection = Selection((0, 0, 101, 101), ((0, 0), (100, 0), (0, 100)))
        shot = mask_screenshot(Image.new("RGB", (101, 101), "red"), selection)
        image = Image.open(io.BytesIO(shot.png))
        self.assertEqual(image.getpixel((10, 10)), (255, 0, 0))
        self.assertEqual(image.getpixel((90, 90)), (255, 255, 255))
        self.assertEqual(image.mode, "RGB")

    def test_old_settings_default_to_ocr_popup_and_new_modes_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text('{"model":"custom"}')
            old = load_settings(path)
            self.assertEqual((old.shot_input, old.shot_display), ("ocr", "popup"))
            save_settings(Settings(shot_input="image", shot_display="overlay"), path)
            new = load_settings(path)
            self.assertEqual((new.shot_input, new.shot_display), ("image", "overlay"))
