"""Download pinned OCR weights at build time, checking the upstream SHA-256."""

import hashlib
import sys
import urllib.request
from pathlib import Path

MODELS = {
    "ch_PP-OCRv5_det_mobile.onnx": ("PP-OCRv5/det", "4d97c44a20d30a81aad087d6a396b08f786c4635742afc391f6621f5c6ae78ae"),
    "ch_PP-OCRv5_rec_server.onnx": ("PP-OCRv5/rec", "e09385400eaaaef34ceff54aeb7c4f0f1fe014c27fa8b9905d4709b65746562a"),
    "ch_ppocr_mobile_v2.0_cls_mobile.onnx": ("PP-OCRv4/cls", "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c"),
    "latin_PP-OCRv5_rec_mobile.onnx": ("PP-OCRv5/rec", "b20bd37c168a570f583afbc8cd7925603890efbcdc000a59e22c269d160b5f5a"),
    "korean_PP-OCRv5_rec_mobile.onnx": ("PP-OCRv5/rec", "cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b"),
    "cyrillic_PP-OCRv5_rec_mobile.onnx": ("PP-OCRv5/rec", "90f761b4bfcce0c8c561c0cb5c887b0971d3ec01c32164bdf7374a35b0982711"),
}
BASE_URL = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx"


def main(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name, (folder, digest) in MODELS.items():
        path = destination / name
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
            continue
        temporary = path.with_suffix(".download")
        try:
            with urllib.request.urlopen(f"{BASE_URL}/{folder}/{name}", timeout=120) as response, temporary.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
                raise RuntimeError(f"OCR model checksum mismatch: {name}")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        print(f"Verified {name}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "src/intext/assets/ocr")
