"""Windows desktop-composition regression, separate from headless unit tests.

Run with Windows Python and pywebview installed. Only synthetic app content
and an owned solid-color background are captured; no user windows or settings.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import sys
import tempfile
import time
import traceback
from pathlib import Path


def main() -> int:
    if sys.platform != "win32":
        raise SystemExit("Run this integration probe on Windows")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(tempfile.gettempdir()) / "intext-transparency")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))

    import webview
    from intext.app import App, _patch_transparent_show
    from intext.platform_win import enable_dpi_awareness

    enable_dpi_awareness()
    _patch_transparent_show()
    assets = root / "src/intext/assets"
    popup = webview.create_window(
        "Intext transparency probe", url=(assets / "popup.html").as_uri(),
        width=460, height=312, frameless=True, transparent=True, hidden=True,
        on_top=True, shadow=False,
    )
    tray = webview.create_window(
        "Intext tray transparency probe", url=(assets / "tray-menu.html").as_uri(),
        width=248, height=160, frameless=True, transparent=True, hidden=True,
        on_top=True, shadow=False,
    )
    shot = webview.create_window(
        "Intext screenshot transparency probe", url=(assets / "shot-overlay.html").as_uri(),
        width=480, height=312, frameless=True, transparent=True, hidden=True,
        on_top=True, shadow=False,
    )
    views = (popup, tray, shot)
    for view in views:
        view._intext_keep_hidden = True
    report: dict = {"passed": False, "cases": []}

    def inspect() -> None:
        from System import Action
        from System.Drawing import Bitmap, Color, Graphics, Point, Size
        from System.Drawing.Imaging import ImageFormat
        from System.Windows.Forms import Form, FormBorderStyle, FormStartPosition

        holder: dict = {}

        def ui(work):
            popup.native.Invoke(Action(work))

        def emulate(view, theme):
            params = {"features": [
                {"name": "prefers-color-scheme", "value": theme},
                {"name": "prefers-reduced-motion", "value": "reduce"},
            ]}
            ui(lambda: holder.update(task=view.native.webview.CoreWebView2.CallDevToolsProtocolMethodAsync(
                "Emulation.setEmulatedMedia", json.dumps(params))))
            task = holder["task"]
            started = time.monotonic()
            while not task.IsCompleted:
                if time.monotonic() - started > 5:
                    raise TimeoutError("Emulation.setEmulatedMedia")
                time.sleep(0.02)
            task.GetAwaiter().GetResult()

        try:
            for view in views:
                if not view.events.loaded.wait(15):
                    raise TimeoutError("WebView load")

            def prepare():
                background = Form()
                background.Text = "Intext test background"
                background.FormBorderStyle = getattr(FormBorderStyle, "None")
                background.StartPosition = FormStartPosition.Manual
                background.ShowInTaskbar = False
                background.TopMost = True
                background.Location = Point(180, 120)
                background.Size = Size(900, 700)
                background.Show()
                holder["background"] = background
                for view, size in ((popup, (460, 312)), (tray, (248, 160)), (shot, (480, 312))):
                    App._prepare_tool_window(None, view, size)
                    view.native.Location = Point(240, 180)

            ui(prepare)
            for theme in ("light", "dark"):
                for mode, view in (("input", popup), ("result", popup), ("tray", tray), ("screenshot", shot)):
                    emulate(view, theme)
                    if mode == "tray":
                        view.evaluate_js("intextTray.open({startup:true,openSide:'right'})")
                    elif mode == "screenshot":
                        import base64
                        import io
                        from PIL import Image

                        buffer = io.BytesIO()
                        Image.new("RGB", (360, 140), "white").save(buffer, format="PNG")
                        state = {"seq": len(report["cases"]) + 1, "from": "英语", "to": "简体中文",
                                 "image": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode(),
                                 "width": 360, "height": 140, "model": "transparency-test", "busy": False,
                                 "text": "原位译文", "blocks": [{"text": "原位译文", "left": 8, "top": 20,
                                     "width": 70, "height": 30, "fontSize": 24, "background": "white", "color": "black"}]}
                        view.evaluate_js("intextShot.apply(" + json.dumps(state, ensure_ascii=False) + ")")
                    else:
                        state = {"seq": len(report["cases"]) + 1, "from": "英语", "to": "简体中文",
                                 "model": "transparency-test", "status": "输入翻译" if mode == "input" else "未缓存"}
                        if mode == "input":
                            state.update(mode="input", draft="Hello, world.")
                        else:
                            state.update(mode="result", source="Original text.", result="翻译结果。")
                        view.evaluate_js("intext.apply(" + json.dumps(state, ensure_ascii=False) + ")")
                    for color in ((35, 62, 91), (210, 130, 80)):
                        def show():
                            for other in views:
                                other.native.Hide()
                            holder["background"].BackColor = Color.FromArgb(*color)
                            holder["background"].Refresh()
                            view.native.Show()
                            view.native.BringToFront()
                        ui(show)
                        time.sleep(0.25)

                        def capture():
                            native = view.native
                            if not holder["background"].Bounds.Contains(native.Bounds):
                                raise AssertionError("Owned background must cover the entire capture")
                            bitmap = Bitmap(native.Width, native.Height)
                            graphics = Graphics.FromImage(bitmap)
                            graphics.CopyFromScreen(native.Left, native.Top, 0, 0, bitmap.Size)
                            graphics.Dispose()
                            points = [(3, 3), (native.Width - 4, 4), (native.Width - 4, native.Height - 4)]
                            pixels = []
                            for x, y in points:
                                p = bitmap.GetPixel(x, y)
                                pixels.append((p.R, p.G, p.B))
                            inside = bitmap.GetPixel(native.Width // 3, native.Height // 3)
                            error = max(abs(a - b) for pixel in pixels for a, b in zip(pixel, color))
                            content_visible = sum(abs(a - b) for a, b in zip((inside.R, inside.G, inside.B), color)) > 40
                            name = f"{mode}-{theme}-{color[0]}.png"
                            bitmap.Save(str(args.output / name), ImageFormat.Png)
                            bitmap.Dispose()
                            case = {"mode": mode, "theme": theme, "background": color,
                                    "outsidePixels": pixels, "maxOutsideError": error,
                                    "contentVisible": content_visible, "screenshot": name}
                            report["cases"].append(case)
                            if error > 2 or not content_visible:
                                raise AssertionError(case)
                        ui(capture)
            report["passed"] = True
        except Exception:
            report["error"] = traceback.format_exc()
        finally:
            # Close the owned test background while the WebView host exists.
            # Closing it after the last WebView can dispatch callbacks into a
            # pywebview instance that has already been removed.
            def cleanup():
                for view in views:
                    view.native.Hide()
                background = holder.get("background")
                if background is not None:
                    background.Close()
                    background.Dispose()
            try:
                ui(cleanup)
            finally:
                shot.destroy()
                tray.destroy()
                popup.destroy()

    webview.start(inspect)
    (args.output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "cases": len(report["cases"])}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
