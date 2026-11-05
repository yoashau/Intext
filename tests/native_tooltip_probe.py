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
                view.evaluate_js('''window.__tooltipTrace=[];
                    const trace=(name,target)=>__tooltipTrace.push({name,target,time:Date.now(),
                      focused:document.hasFocus(),visibility:document.visibilityState,
                      hidden:document.getElementById('tooltip').hidden});
                    for(const name of ['pointerover','pointerout','focusin','focusout','visibilitychange'])
                      document.addEventListener(name,e=>trace(name,e.target.id||e.target.dataset?.action||''),true);
                    for(const name of ['focus','blur'])window.addEventListener(name,()=>trace(name,''));
                    const reset=intextControls.resetTooltip;
                    intextControls.resetTooltip=(...args)=>{trace('reset',String(args[0]||''));return reset(...args)};
                    new MutationObserver(()=>trace('tooltip-changed','')).observe(document.getElementById('tooltip'),
                      {attributes:true,attributeFilter:['hidden']});''')
                if file == 'tray-menu.html':
                    view.evaluate_js('intextTray.open({startup:false});document.querySelector(\'[data-action="startup"]\').dataset.tooltip="tray help"')
                target = 'document.querySelector(' + json.dumps(selector) + ')'
                rect = view.evaluate_js('JSON.stringify((()=>{const r=' + target + '.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})())')
                if isinstance(rect, str):
                    rect = json.loads(rect)
                # The native window can be visible before WebView receives
                # keyboard focus. A real hover must still work immediately.
                ui(lambda: background.Activate())
                time.sleep(.1)
                check(not view.evaluate_js('document.hasFocus()'), file + ' hover starts without WebView focus')
                protocol(view, 'Input.dispatchMouseEvent', {'type':'mouseMoved','x':300,'y':300})
                protocol(view, 'Input.dispatchMouseEvent', {'type':'mouseMoved', **rect})
                # A visible transition arriving after pointerover must not
                # cancel the user's pending hover.
                view.evaluate_js('document.dispatchEvent(new Event("visibilitychange"))')
                time.sleep(.4)
                check(not hidden(view), file + ' unfocused early hover shows help')
                protocol(view, 'Input.dispatchMouseEvent', {'type':'mouseMoved','x':300,'y':300})
                ui(lambda: app._show_native(view))
                view.evaluate_js(target + '.focus()')
                check(hidden(view), file + ' programmatic focus stays quiet')
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

            # Esc must cancel hotkey recording even if a help tooltip is up.
            view = views[0]
            ui(lambda: app._show_native(view))
            view.evaluate_js("document.getElementById('hotkey-select').focus();document.getElementById('hotkey-select').click()")
            check(view.evaluate_js("document.getElementById('hotkey-select').classList.contains('is-on')"),
                  'hotkey recording starts')
            help_rect = view.evaluate_js('''JSON.stringify((()=>{
              const r=document.getElementById('select-tip').parentElement.getBoundingClientRect();
              return {x:r.x+r.width/2,y:r.y+r.height/2};})())''')
            if isinstance(help_rect, str):
                help_rect = json.loads(help_rect)
            protocol(view, 'Input.dispatchMouseEvent', {'type':'mouseMoved','x':300,'y':300})
            protocol(view, 'Input.dispatchMouseEvent', {'type':'mouseMoved', **help_rect})
            time.sleep(.4)
            check(not hidden(view), 'help is visible during hotkey recording')
            view.evaluate_js("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',isComposing:true,bubbles:true}))")
            check(view.evaluate_js("document.getElementById('hotkey-select').classList.contains('is-on')") and not hidden(view),
                  'composing Escape does not cancel recording or help')
            for kind in ('keyDown', 'keyUp'):
                protocol(view, 'Input.dispatchKeyEvent', {'type':kind,'key':'Escape','code':'Escape','windowsVirtualKeyCode':27})
            check(not view.evaluate_js("document.getElementById('hotkey-select').classList.contains('is-on')"),
                  'Escape cancels hotkey recording with help open')
            check(hidden(view), 'canceling hotkey recording also dismisses help')
            view.evaluate_js("document.getElementById('hotkey-select').click()")
            for kind in ('keyDown', 'keyUp'):
                protocol(view, 'Input.dispatchKeyEvent', {'type':kind,'key':'Escape','code':'Escape','windowsVirtualKeyCode':27})
            check(not view.evaluate_js("document.getElementById('hotkey-select').classList.contains('is-on')"),
                  'Escape cancels hotkey recording without help')
            view.evaluate_js("window.hides=0;window.pywebview.api={save:async()=>({}),hide:()=>{window.hides++}}")
            protocol(view, 'Input.dispatchMouseEvent', {'type':'mouseMoved','x':300,'y':300})
            protocol(view, 'Input.dispatchMouseEvent', {'type':'mouseMoved', **help_rect})
            time.sleep(.4)
            check(not hidden(view), 'help is visible when not recording')
            for kind in ('keyDown', 'keyUp'):
                protocol(view, 'Input.dispatchKeyEvent', {'type':kind,'key':'Escape','code':'Escape','windowsVirtualKeyCode':27})
            check(hidden(view) and view.evaluate_js('window.hides') == 0, 'first Escape dismisses help only')
            for kind in ('keyDown', 'keyUp'):
                protocol(view, 'Input.dispatchKeyEvent', {'type':kind,'key':'Escape','code':'Escape','windowsVirtualKeyCode':27})
            time.sleep(.1)
            check(view.evaluate_js('window.hides') == 1, 'second Escape retains settings close behavior')
            # Repeated native toggles must not let a late reset suppress the
            # next deliberate hover or resurrect old tooltip state.
            for _ in range(6):
                ui(lambda: (app._hide_native(view), app._show_native(view)))
            time.sleep(.15)
            check(hidden(view) and not view.native.TopMost, 'rapid reopens keep settings quiet and non-topmost')
            protocol(view, 'Input.dispatchMouseEvent', {'type':'mouseMoved','x':300,'y':300})
            protocol(view, 'Input.dispatchMouseEvent', {'type':'mouseMoved', **help_rect})
            time.sleep(.4)
            check(not hidden(view), 'hover still works after rapid reopens')

            endpoint_rect = view.evaluate_js('''JSON.stringify((()=>{
              const r=document.getElementById('endpoint-tip').parentElement.getBoundingClientRect();
              return {x:r.x+r.width/2,y:r.y+r.height/2};})())''')
            if isinstance(endpoint_rect, str):
                endpoint_rect = json.loads(endpoint_rect)
            protocol(view, 'Input.dispatchMouseEvent', {'type':'mouseMoved','x':300,'y':300})
            protocol(view, 'Input.dispatchMouseEvent', {'type':'mouseMoved', **endpoint_rect})
            time.sleep(.4)
            check(not hidden(view), 'endpoint help is visible')
            view.evaluate_js('''const endpoint=document.getElementById('endpoint');endpoint.value='invalid';
              endpoint.dispatchEvent(new Event('input',{bubbles:true}));''')
            time.sleep(.1)
            check(view.evaluate_js('''!document.getElementById('tooltip').hidden &&
              document.getElementById('tooltip').textContent === document.getElementById('endpoint-tip').textContent'''),
              'visible endpoint help follows validation changes')
            view.evaluate_js("document.getElementById('sheet').scrollTop=100")
            time.sleep(.1)
            check(view.evaluate_js("document.getElementById('sheet').scrollTop > 0") and hidden(view),
                  'scrolling settings dismisses help')
            report['passed'] = True
        except Exception:
            report['error'] = traceback.format_exc()
            try:
                report['trace'] = view.evaluate_js('JSON.stringify(window.__tooltipTrace)')
            except Exception:
                pass
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
