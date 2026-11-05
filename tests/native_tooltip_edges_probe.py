"""Exercise shared tooltip edge cases in an isolated Windows WebView2."""
from __future__ import annotations

import argparse
import ctypes
import json
import shutil
import tempfile
import time
import traceback
from pathlib import Path
from ctypes import wintypes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--assets', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--width', type=int, default=480)
    parser.add_argument('--height', type=int, default=320)
    parser.add_argument('--left', type=int)
    parser.add_argument('--top', type=int, default=100)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    assets = args.assets or root / 'src/intext/assets'
    import webview
    from intext.platform_win import enable_dpi_awareness
    enable_dpi_awareness()
    user = ctypes.WinDLL('user32')
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    user.mouse_event.argtypes = [wintypes.DWORD] * 4 + [ctypes.c_size_t]
    original_cursor = wintypes.POINT()
    user.GetCursorPos(ctypes.byref(original_cursor))
    original_foreground = user.GetForegroundWindow()
    report = {'passed': False}
    with tempfile.TemporaryDirectory(prefix='intext-tooltip-edges-') as temp:
        folder = Path(temp)
        for name in ('controls.js', 'controls.css'):
            shutil.copy2(assets / name, folder / name)
        (folder / 'fixture.html').write_text('''<!doctype html><html><head><meta charset="utf-8">
          <link rel="stylesheet" href="controls.css"><style>
          html,body{margin:0;height:100%;overflow:hidden}button{position:absolute;width:64px;height:32px}
          #a{left:20px;top:30px}#b{left:120px;top:30px}#long{left:220px;top:30px}
          #dynamic{left:20px;top:90px}#edge{right:0;bottom:0}#outside{position:absolute;left:10px;top:170px;width:120px;height:50px}
          </style></head><body><button id="a" data-tooltip="alpha"><span id="child">A</span></button>
          <button id="b" data-tooltip="beta">B</button><button id="long">long</button>
          <button id="dynamic">dynamic</button><button id="edge" data-tooltip="edge">edge</button>
          <div id="outside">outside</div><script>document.querySelector('#long').dataset.tooltip='Long help '.repeat(400)</script>
          <script src="controls.js"></script></body></html>''', encoding='utf-8')
        view = webview.create_window('Intext tooltip edge probe', url=(folder / 'fixture.html').as_uri(),
                                     width=args.width, height=args.height, hidden=True, frameless=True, on_top=True)
        view._intext_keep_hidden = True
        def inspect():
            try:
                if not view.events.loaded.wait(20):
                    raise TimeoutError('WebView load')
                from System import Action
                def ui(work):
                    view.native.Invoke(Action(work))
                def protocol(method, params):
                    box = {}
                    ui(lambda: box.update(task=view.native.webview.CoreWebView2.CallDevToolsProtocolMethodAsync(method, json.dumps(params))))
                    deadline = time.monotonic() + 5
                    while not box['task'].IsCompleted:
                        if time.monotonic() > deadline:
                            raise TimeoutError(method)
                        time.sleep(.01)
                    box['task'].GetAwaiter().GetResult()
                def show():
                    if args.left is not None:
                        view.native.SetDesktopLocation(args.left, args.top)
                    view.native.Show()
                    view.native.Activate()
                ui(show)
                dpi = ctypes.WinDLL('user32').GetDpiForWindow
                dpi.argtypes = [ctypes.c_void_p]
                dpi.restype = ctypes.c_uint
                hwnd = int(view.native.Handle.ToInt64())
                report['dpi'] = dpi(hwnd)
                # A real click gives this owned test window foreground rights,
                # including when another application is currently active.
                point = wintypes.POINT(8, 8)
                user.ClientToScreen(hwnd, ctypes.byref(point))
                user.SetCursorPos(point.x, point.y)
                user.mouse_event(2, 0, 0, 0, 0)
                user.mouse_event(4, 0, 0, 0, 0)
                view.evaluate_js((root / 'tests/tooltip_edges.js').read_text(encoding='utf-8'))
                view.evaluate_js('document.body.tabIndex=-1;document.body.focus();window.runTooltipEdges()')
                deadline = time.monotonic() + 35
                while time.monotonic() < deadline:
                    result = view.evaluate_js('JSON.stringify(window.tooltipEdges)')
                    if isinstance(result, str):
                        result = json.loads(result)
                    if result and result.get('done'):
                        report.update(result)
                        # Real pointer input verifies that the scrollbar on a
                        # keyboard-opened long tooltip can be clicked.
                        view.evaluate_js('intextControls.resetTooltip();document.body.focus()')
                        protocol('Input.dispatchKeyEvent', {'type':'keyDown','key':'Tab','code':'Tab','windowsVirtualKeyCode':9})
                        view.evaluate_js("document.querySelector('#long').focus()")
                        protocol('Input.dispatchKeyEvent', {'type':'keyUp','key':'Tab','code':'Tab','windowsVirtualKeyCode':9})
                        rect = view.evaluate_js('''JSON.stringify((()=>{const e=document.querySelector('#tooltip'),r=e.getBoundingClientRect();
                          return {x:r.right-2,y:r.top+Math.min(80,r.height/2),visible:!e.hidden,scrollable:e.classList.contains('is-scrollable')};})())''')
                        if isinstance(rect, str):
                            rect = json.loads(rect)
                        before_key_scroll = view.evaluate_js("document.querySelector('#tooltip').scrollTop")
                        for kind in ('keyDown', 'keyUp'):
                            protocol('Input.dispatchKeyEvent', {'type':kind,'key':'ArrowDown','code':'ArrowDown','windowsVirtualKeyCode':40})
                        after_key_scroll = view.evaluate_js("document.querySelector('#tooltip').scrollTop")
                        result['cases'].append({'name':'20 keyboard can scroll a long tooltip',
                                                'passed':after_key_scroll > before_key_scroll})
                        coords = {'x':rect['x'], 'y':rect['y']}
                        protocol('Input.dispatchMouseEvent', {'type':'mouseMoved', **coords})
                        protocol('Input.dispatchMouseEvent', {'type':'mousePressed','button':'left','clickCount':1, **coords})
                        protocol('Input.dispatchMouseEvent', {'type':'mouseReleased','button':'left','clickCount':1, **coords})
                        time.sleep(.1)
                        visible = not view.evaluate_js("document.querySelector('#tooltip').hidden")
                        before_scroll = view.evaluate_js("document.querySelector('#tooltip').scrollTop")
                        protocol('Input.dispatchMouseEvent', {'type':'mouseWheel','deltaX':0,'deltaY':120, **coords})
                        time.sleep(.1)
                        after_scroll = view.evaluate_js("document.querySelector('#tooltip').scrollTop")
                        result['cases'].append({'name':'21 keyboard tooltip scrollbar accepts pointer input',
                                                'passed':bool(rect['visible'] and rect['scrollable'] and visible and after_scroll > before_scroll),
                                                'before':rect, 'visibleAfterClick':visible,
                                                'scrolled':after_scroll > before_scroll})
                        from System.Windows.Forms import Form
                        holder = {}
                        def activate_other():
                            other = Form()
                            other.ShowInTaskbar = False
                            other.TopMost = True
                            other.Show()
                            other.Activate()
                            holder['other'] = other
                        ui(activate_other)
                        time.sleep(.2)
                        dismissed = view.evaluate_js("document.querySelector('#tooltip').hidden")
                        ui(lambda: holder['other'].Close())
                        result['cases'].append({'name':'22 switching windows dismisses help', 'passed':bool(dismissed)})
                        report['passed'] = not result.get('error') and all(case['passed'] for case in result['cases'])
                        break
                    time.sleep(.1)
                else:
                    raise TimeoutError('Tooltip edge checks')
            except Exception:
                report['error'] = traceback.format_exc()
            finally:
                view.destroy()
                user.SetCursorPos(original_cursor.x, original_cursor.y)
                if original_foreground:
                    user.SetForegroundWindow(original_foreground)
        webview.start(inspect)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
