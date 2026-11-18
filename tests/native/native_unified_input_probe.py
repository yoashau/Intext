"""Exercise source selection and editing in WebView2 without touching the clipboard."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / 'src'))
    profile = tempfile.TemporaryDirectory(prefix='intext-input-probe-')
    os.environ['APPDATA'] = profile.name
    import webview
    from intext.app import App, _patch_transparent_show
    from intext import platform_win as win

    win.enable_dpi_awareness()
    _patch_transparent_show()
    calls = []

    class Api:
        def copy_text(self, text):
            calls.append(('copy', text))
            return True

        def submit_text(self, text, _generation=None):
            calls.append(('submit', text))
            return True

        def hide(self):
            calls.append(('hide', ''))

        def begin_drag(self):
            calls.append(('drag', ''))

        def mark_ready(self, *_):
            pass

    popup = webview.create_window('Intext input probe', url=(root / 'src/intext/assets/popup.html').as_uri(),
        js_api=Api(), width=460, height=312, hidden=True, frameless=True, transparent=True,
        easy_drag=False, text_select=True)
    popup._intext_keep_hidden = True
    app = App.__new__(App)
    app._popup = popup
    app._settings_window = app._shot_window = app._tray_menu = None
    app._arm_popup_blur = lambda _: None
    app._sync_taskbar = lambda *_: None
    app._sync_outside_click_watch = lambda: None
    report = {'passed': False, 'checks': {}}

    def inspect():
        from System import Action
        from System.Drawing import Point

        previous = win.user32.GetForegroundWindow()

        def ui(work):
            popup.native.Invoke(Action(work))

        def check(value, name):
            report['checks'][name] = bool(value)
            if not value:
                raise AssertionError(name)

        def protocol(method, params):
            box = {}
            ui(lambda: box.update(task=popup.native.webview.CoreWebView2.CallDevToolsProtocolMethodAsync(method, json.dumps(params))))
            deadline = time.monotonic() + 5
            while not box['task'].IsCompleted:
                if time.monotonic() >= deadline:
                    raise TimeoutError(method)
                time.sleep(.01)
            return box['task'].GetAwaiter().GetResult()

        def wait_for(predicate):
            deadline = time.monotonic() + 4
            while not predicate():
                if time.monotonic() >= deadline:
                    raise TimeoutError('WebView interaction')
                time.sleep(.01)

        def key(name, code, virtual_key, modifiers=0):
            for kind in ('keyDown', 'keyUp'):
                protocol('Input.dispatchKeyEvent', {'type': kind, 'key': name, 'code': code,
                    'windowsVirtualKeyCode': virtual_key, 'modifiers': modifiers})

        try:
            if not popup.events.loaded.wait(20):
                raise TimeoutError('WebView loaded')
            ui(lambda: (app._prepare_tool_window(popup, (460, 312)), setattr(popup.native, 'Location', Point(240, 180)), app._show_native(popup)))
            popup.evaluate_js("intext.apply({seq:1,source:'Original selection text',result:'Initial translation',from:'English',to:'中文',sourceLang:'en',resultLang:'zh'})")
            rect = popup.evaluate_js("(() => {const r=document.querySelector('#source').getBoundingClientRect();return {x:r.x+4,y:r.y+9};})()")
            protocol('Input.dispatchMouseEvent', {'type':'mousePressed', **rect, 'button':'left', 'clickCount':1})
            protocol('Input.dispatchMouseEvent', {'type':'mouseMoved', 'x':rect['x']+85, 'y':rect['y'], 'button':'left', 'buttons':1})
            protocol('Input.dispatchMouseEvent', {'type':'mouseReleased', 'x':rect['x']+85, 'y':rect['y'], 'button':'left', 'clickCount':1})
            selected = popup.evaluate_js('getSelection().toString()')
            check(bool(selected) and popup.evaluate_js("document.getElementById('input').hidden"), 'source drag selects without editing')
            key('c', 'KeyC', 67, 2)
            wait_for(lambda: ('copy', selected) in calls)
            check(('copy', selected) in calls and not any(name == 'drag' for name, _ in calls), 'selected source reaches copy bridge')
            protocol('Input.dispatchMouseEvent', {'type':'mousePressed', **rect, 'button':'left', 'clickCount':1})
            protocol('Input.dispatchMouseEvent', {'type':'mouseReleased', **rect, 'button':'left', 'clickCount':1})
            check(popup.evaluate_js("!input.hidden && input.value === 'Original selection text' && !result.hidden"), 'source click opens editor beside result')
            check(popup.evaluate_js("(() => {input.focus();input.setSelectionRange(0,8);const e=new KeyboardEvent('keydown',{key:'c',ctrlKey:true,bubbles:true,cancelable:true});input.dispatchEvent(e);return !e.defaultPrevented && input.selectionEnd===8})()"), 'editable selection retains native copying')
            popup.evaluate_js("input.setSelectionRange(input.value.length,input.value.length)")
            protocol('Input.insertText', {'text':' revised'})
            check(popup.evaluate_js("input.value === 'Original selection text revised' && !document.getElementById('edit-note').hidden"), 'native typing updates draft and stale-result hint')
            popup.evaluate_js("intext.apply({seq:1,source:'Original selection text',result:'Late translation',from:'English',to:'中文',sourceLang:'en',resultLang:'zh'})")
            check(popup.evaluate_js("!input.hidden && input.value === 'Original selection text revised' && result.textContent === 'Late translation'"), 'late result preserves native draft')
            key('Enter', 'Enter', 13, 2)
            wait_for(lambda: ('submit', 'Original selection text revised') in calls)
            check(('submit', 'Original selection text revised') in calls, 'Ctrl+Enter submits edited source')
            wait_for(lambda: not popup.evaluate_js("document.getElementById('submit').disabled"))
            key('Escape', 'Escape', 27)
            check(popup.evaluate_js("input.hidden && !source.hidden") and not any(name == 'hide' for name, _ in calls), 'Escape cancels editing')
            lines = '\n'.join(f'Editable line {i:02d} of input.' for i in range(20))
            popup.evaluate_js('intext.apply(' + json.dumps({'seq': 2, 'mode': 'input', 'draft': lines, 'enter': True}) + ')')
            wait_for(lambda: popup.evaluate_js("!input.hidden && input.scrollHeight > input.clientHeight"))
            popup.evaluate_js('input.scrollTop = 0')
            wait_for(lambda: popup.evaluate_js("parseFloat(getComputedStyle(input).getPropertyValue('--scroll-fade-bottom')) === 28"))
            check(popup.evaluate_js("parseFloat(getComputedStyle(input).getPropertyValue('--scroll-fade-top')) === 0"), 'native input starts with a clear first line and a fading bottom')
            popup.evaluate_js('input.scrollTop = (input.scrollHeight - input.clientHeight) / 2')
            wait_for(lambda: popup.evaluate_js("parseFloat(getComputedStyle(input).getPropertyValue('--scroll-fade-top')) === 28"))
            check(popup.evaluate_js("parseFloat(getComputedStyle(input).getPropertyValue('--scroll-fade-bottom')) === 28"), 'native input fades both edges while scrolling')
            key('End', 'End', 35, 2)
            for _ in range(7):
                key('ArrowUp', 'ArrowUp', 38)
            wait_for(lambda: popup.evaluate_js("input.selectionStart < input.value.length"))
            caret_clear = """(() => {
                const s = getComputedStyle(input), h = parseFloat(s.lineHeight);
                const row = input.value.slice(0, input.selectionStart).split('\\n').length - 1;
                const y = parseFloat(s.paddingTop) + row * h - input.scrollTop;
                return y >= parseFloat(s.getPropertyValue('--scroll-fade-top')) - 3 &&
                  y + h <= input.clientHeight - parseFloat(s.getPropertyValue('--scroll-fade-bottom')) + 3;
            })()"""
            check(popup.evaluate_js(caret_clear), 'native keyboard navigation keeps the caret outside the fade')
            report['passed'] = True
        except Exception:
            report['error'] = traceback.format_exc()
        finally:
            popup.destroy()
            if previous:
                win.user32.SetForegroundWindow(previous)

    webview.start(inspect)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    profile.cleanup()
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
