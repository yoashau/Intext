"""Windows entry point used by the frozen executable."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

BOOT = Path.home() / "AppData" / "Roaming" / "Intext" / "boot.log"


def _boot(message: str) -> None:
    try:
        BOOT.parent.mkdir(parents=True, exist_ok=True)
        with BOOT.open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")
    except Exception:
        return


if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

_boot("launch")
try:
    import bottle  # noqa: F401
    import clr  # noqa: F401
    import webview  # noqa: F401
    from intext.__main__ import main

    _boot("imported")
    code = main()
    _boot(f"exit {code}")
    raise SystemExit(code)
except SystemExit:
    raise
except Exception:
    _boot(traceback.format_exc())
    raise
