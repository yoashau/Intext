"""Local PP-OCRv5 inference. Weights are verified and bundled at build time."""

from __future__ import annotations

import threading
from functools import lru_cache
from pathlib import Path

from .screenshot import OcrPage, Screenshot, TextRegion
from .translate import TranslationError

_lock = threading.Lock()


def model_directory() -> Path:
    return Path(__file__).resolve().parent / "assets" / "ocr"


def recognition_model(source: str) -> tuple[str, str]:
    if source in {"fr", "de", "es"}:
        return "latin", "latin_PP-OCRv5_rec_mobile.onnx"
    if source == "ko":
        return "korean", "korean_PP-OCRv5_rec_mobile.onnx"
    if source == "ru":
        return "cyrillic", "cyrillic_PP-OCRv5_rec_mobile.onnx"
    return "ch", "ch_PP-OCRv5_rec_server.onnx"


@lru_cache(maxsize=2)
def _engine(language: str):
    from rapidocr import ModelType, OCRVersion, RapidOCR

    name = {"ch": "ch_PP-OCRv5_rec_server.onnx", "latin": "latin_PP-OCRv5_rec_mobile.onnx",
            "korean": "korean_PP-OCRv5_rec_mobile.onnx", "cyrillic": "cyrillic_PP-OCRv5_rec_mobile.onnx"}[language]
    root = model_directory()
    paths = {"Det": root / "ch_PP-OCRv5_det_mobile.onnx",
             "Cls": root / "ch_ppocr_mobile_v2.0_cls_mobile.onnx", "Rec": root / name}
    if not all(path.is_file() for path in paths.values()):
        raise TranslationError("OCR 模型缺失，请重新安装完整安装包；源码运行请先执行 packaging/prepare_ocr.py。")
    return RapidOCR(params={
        "Global.log_level": "error",
        "Global.max_side_len": 4096,
        "Det.ocr_version": OCRVersion.PPOCRV5,
        "Det.model_type": ModelType.MOBILE,
        "Det.limit_side_len": 1280,
        "Det.limit_type": "max",
        "Rec.ocr_version": OCRVersion.PPOCRV5,
        "Rec.model_type": ModelType.SERVER if language == "ch" else ModelType.MOBILE,
        "Rec.lang_type": language,
        "EngineConfig.onnxruntime.intra_op_num_threads": 4,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        **{f"{key}.model_path": str(path) for key, path in paths.items()},
    })


def recognize(shot: Screenshot, source: str = "auto") -> OcrPage:
    import numpy as np

    try:
        with _lock:
            # A model instance has mutable pre-processing state.
            output = _engine(recognition_model(source)[0])(np.asarray(shot.image())[:, :, ::-1].copy())
    except TranslationError:
        raise
    except Exception as exc:
        from .config import log_error

        log_error(f"PP-OCRv5 failed: {exc}")
        raise TranslationError("本地 OCR 识别失败，请检查安装包是否完整。") from exc
    if output.boxes is None or not output.txts:
        return OcrPage(())
    width, height = shot.selection.rect[2:]
    regions = []
    for text, score, box in zip(output.txts, output.scores, output.boxes):
        if not str(text).strip():
            continue
        points = tuple((max(0.0, min(float(x), width)), max(0.0, min(float(y), height))) for x, y in box)
        regions.append(TextRegion(len(regions), str(text), points, float(score)))
    return OcrPage(tuple(regions))
