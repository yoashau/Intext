"""Exercise real OCR inside the frozen executable before distributing it."""

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main(executable: str) -> None:
    with tempfile.TemporaryDirectory(prefix="intext-ocr-check-") as folder:
        path = Path(folder) / "OCR test.png"
        image = Image.new("RGB", (640, 120), "white")
        font = ImageFont.truetype("arial.ttf", 32)
        ImageDraw.Draw(image).text((20, 30), "Intext OCR 12345", font=font, fill="black")
        image.save(path)
        result = subprocess.run([executable, "--check-ocr", str(path)], capture_output=True, timeout=45)
        if result.returncode != 0 or b"12345" not in result.stdout or b"OCR" not in result.stdout:
            raise RuntimeError(f"Frozen OCR check failed (exit {result.returncode})")
        print("Frozen PP-OCRv5 read the test image successfully")


if __name__ == "__main__":
    main(sys.argv[1])
