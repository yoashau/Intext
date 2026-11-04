"""Run Intext."""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="intext")
    parser.add_argument("--preview", action="store_true", help="open the locked popup with sample text")
    parser.add_argument("--settings", action="store_true", help="open request settings")
    parser.add_argument("--silent", action="store_true", help="start in the tray without opening a window")
    parser.add_argument("--text", help="translate one string and print it")
    parser.add_argument("--check", action="store_true", help="verify the install without opening a window")
    parser.add_argument("--check-ocr", type=Path, metavar="IMAGE", help="recognize a local test image without opening a window or sending a request")
    args = parser.parse_args(argv)

    if args.check:
        return _check()

    if args.check_ocr is not None:
        import io
        from PIL import Image
        from .ocr import recognize
        from .screenshot import Screenshot, Selection

        with Image.open(args.check_ocr) as image:
            image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="PNG")
            text = recognize(Screenshot(output.getvalue(), Selection((0, 0, *image.size), ()))).text
        print(text)
        return 0 if text else 1

    if args.text is not None:
        from .app import App
        from .translate import TranslationError

        try:
            result = App().translate_text(args.text)
        except TranslationError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(result.text)
        return 0

    if sys.platform != "win32":
        print("图形界面目前只在 Windows 上运行。", file=sys.stderr)
        return 2

    try:
        return _run_gui(args)
    except Exception:
        trace = traceback.format_exc()
        try:
            boot = Path.home() / "AppData" / "Roaming" / "Intext" / "boot.log"
            with boot.open("a", encoding="utf-8") as handle:
                handle.write(trace)
        except Exception:
            pass
        from .config import log_error
        log_error(trace)
        return 1


def _run_gui(args) -> int:

    from .platform_win import claim_instance, signal_running_instance

    if not claim_instance():
        if not args.silent:
            signal_running_instance()
        return 0

    from .app import run_gui

    run_gui(preview=args.preview and not args.silent, settings_only=args.settings and not args.preview, silent=args.silent)
    return 0


def _check() -> int:
    from .app import asset_dir
    from .fields import request_preview

    body = request_preview("gpt 6.1 sol", "auto", "zh", {})
    missing = [name for name in ("popup.html", "settings.html", "tray-menu.html", "shot-overlay.html", "shot-overlay.css", "shot-overlay.js", "controls.css", "controls.js", "scroll.js", "markdown.js", "markdown.css", "request-policy.js", "vendor/markdown-it/markdown-it.min.js", "vendor/katex/katex.min.js", "vendor/katex/katex.min.css", "vendor/katex/fonts/KaTeX_Main-Regular.woff2", "mark.png", "mark-light.png", "intext.ico", "intext-on-dark.ico", "tray.ico", "tray-on-dark.ico", "ocr/ch_PP-OCRv5_det_mobile.onnx", "ocr/ch_PP-OCRv5_rec_server.onnx") if not (asset_dir() / name).is_file()]
    if missing or "temperature" in body or body["messages"][1]["content"] != "<选中文字>":
        print("check failed", file=sys.stderr)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
