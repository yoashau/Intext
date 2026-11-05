"""Exercise tooltip input and native reactivation in owned WebView2 windows.

Run on Windows; --assets can point at the installed application's assets.
No settings, clipboard, hotkeys or translation services are used.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--assets', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'src'))
    import webview
    from intext.app import App, _patch_transparent_show
    from intext.platform_win import enable_dpi_awareness
    enable_dpi_awareness()
    _patch_transparent_show()
    assets = args.assets or root / 'src/intext/assets'
    cases = [('settings.html', '#stash'), ('popup.html', '#copy'),
             ('shot-overlay.html', '#copy'), ('tray-menu.html', '[data-action="startup"]')]
    views = [webview.create_window('Intext tooltip probe ' + file,
             url=(assets / file).as_uri(), width=640, height=600,
             hidden=True, on_top=True, frameless=True) for file, _ in cases]
    for view in views:
        view._intext_keep_hidden = True
    app = App.__new__(App)
    app._settings_window, app._popup, app._shot_window, app._tray_menu = views
    app._arm_popup_blur = lambda _: None
    report = {'passed': False, 'checks': []}

    def check(value, name):
        if not value:
            raise AssertionError(name)
        report['checks'].append(name)

    def inspect():
        from System import Action
        from System.Windows.Forms import Form
        background = None
        def ui(work):
            views[0].native.Invoke(Action(work))
        def protocol(view, method, params):
            box = {}
            ui(lambda: box.update(task=view.native.webview.CoreWebView2.CallDevToolsProtocolMethodAsync(method, json.dumps(params))))
            end = time.monotonic() + 5
            while not box['task'].IsCompleted:
                if time.monotonic() > end:
                    raise TimeoutError(method)
                time.sleep(.01)
            box['task'].GetAwaiter().GetResult()
        def hidden(view):
            return view.evaluate_js('document.getElementById("tooltip").hidden')
        try:
            for view in views:
                check(view.events.loaded.wait(20), 'WebView loaded')
            def prepare():
                nonlocal background
                background = Form()
                background.Text = 'Intext tooltip probe background'
                background.ShowInTaskbar = False
                background.Show()
            ui(prepare)
            for view, (file, selector) in zip(views, cases):
                ui(lambda: app._show_native(view))
                time.sleep(.15)
                check(bool(view.native.TopMost) == (view is not app._settings_window), file + ' correct native topmost state')
                # Every page uses the shared tooltip component. The tray's
                # regular items have no tooltip, so add one to cover errors.
                view.evaluate_js('''window.pywebview = window.pywebview || {};
                    window.pywebview.api = {hide:()=>Promise.resolve(),activate:()=>Promise.resolve()};''')
                if file == 'tray-menu.html':
                    view.evaluate_js('intextTray.open({startup:false});document.querySelector(\'[data-action="startup"]\').dataset.tooltip="tray help"')
                target = 'document.querySelector(' + json.dumps(selector) + ')'
                view.evaluate_js(target + '.focus()')
                check(hidden(view), file + ' programmatic focus stays quiet')
                rect = view.evaluate_js('JSON.stringify((()=>{const r=' + target + '.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})())')
                if isinstance(rect, str):
                    rect = json.loads(rect)
                protocol(view, 'Input.dispatchMouseEvent', {'type':'mouseMoved', **rect})
                time.sleep(.4)
                check(not hidden(view), file + ' pointer hover shows help')
                protocol(view, 'Input.dispatchMouseEvent', {'type':'mouseMoved','x':300,'y':300})
                view.evaluate_js(target + '.focus()')
                check(hidden(view), file + ' pointer focus stays quiet')
                keys = ({'type':'keyDown','key':'Tab','code':'Tab','windowsVirtualKeyCode':9},
                            {'type':'keyUp','key':'Tab','code':'Tab','windowsVirtualKeyCode':9},
                            {'type':'keyDown','key':'Tab','code':'Tab','windowsVirtualKeyCode':9,'modifiers':8},
                            {'type':'keyUp','key':'Tab','code':'Tab','windowsVirtualKeyCode':9,'modifiers':8})
                if file == 'tray-menu.html':
                    keys = tuple({'type': kind, 'key': key, 'code': key, 'windowsVirtualKeyCode': code}
                                 for key, code in (('ArrowDown', 40), ('ArrowUp', 38))
                                 for kind in ('keyDown', 'keyUp'))
                for key in keys:
                    protocol(view, 'Input.dispatchKeyEvent', key)
                check(not hidden(view), file + ' keyboard navigation shows help')
                # Restoring the previously focused button must not revive its
                # help, including after the user had used keyboard navigation.
                ui(lambda: (app._hide_native(view), background.Activate()))
                time.sleep(.15)
                ui(lambda: app._show_native(view))
                time.sleep(.2)
                check(hidden(view), file + ' native hide and reopen stays quiet')
                view.evaluate_js(target + '.blur();' + target + '.focus()')
                check(hidden(view), file + ' restored button focus stays quiet')
                protocol(view, 'Input.dispatchMouseEvent', {'type':'mouseMoved', **rect})
                time.sleep(.05)
                ui(lambda: (app._hide_native(view), background.Activate()))
                time.sleep(.4)
                check(hidden(view), file + ' hide cancels pending hover')
            report['passed'] = True
        except Exception:
            report['error'] = traceback.format_exc()
        finally:
            if background is not None:
                ui(lambda: background.Close())
            for view in reversed(views):
                view.destroy()

    webview.start(inspect)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
