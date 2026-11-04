import io
import sys
import unittest
from pathlib import Path

from intext.ocr import recognition_model
from intext.screenshot import Screenshot, Selection


class OcrTests(unittest.TestCase):
    def test_recognition_language_matches_the_selected_source(self):
        for source in ("auto", "zh", "zh-Hans", "en", "ja"):
            self.assertEqual(recognition_model(source)[0], "ch")
        self.assertEqual(recognition_model("fr")[0], "latin")
        self.assertEqual(recognition_model("ko")[0], "korean")
        self.assertEqual(recognition_model("ru")[0], "cyrillic")

    @unittest.skipUnless(sys.platform == "win32", "requires packaged Windows OCR dependencies")
    def test_ppocr_reads_chinese_english_and_preserves_positioned_lines(self):
        from intext.ocr import recognize
        from PIL import Image, ImageDraw, ImageFont

        image = Image.new("RGB", (900, 220), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(str(Path("C:/Windows/Fonts/msyh.ttc")), 30)
        draw.text((24, 20), "截图翻译保留原文结构", font=font, fill="black")
        draw.text((24, 85), "Intext OCR 12345", font=font, fill="black")
        draw.text((24, 150), "a = b + 42", font=font, fill="black")
        output = io.BytesIO()
        image.save(output, format="PNG")
        shot = Screenshot(output.getvalue(), Selection((0, 0, *image.size), ()))
        for _ in range(2):
            page = recognize(shot)
            self.assertIn("截图翻译保留原文结构", page.text)
            self.assertIn("12345", page.text)
            self.assertGreaterEqual(len(page.regions), 3)
            self.assertLess(page.regions[0].rect[1], page.regions[-1].rect[1])
