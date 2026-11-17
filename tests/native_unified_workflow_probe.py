"""Exercise input, editing and translation through the real app and WebView2.

Uses a temporary profile and a local in-memory translator. It does not read
the user's configuration, touch the clipboard or register global hotkeys.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'src'))
    profile = tempfile.TemporaryDirectory(prefix='intext-workflow-probe-')
    os.environ['APPDATA'] = profile.name
    import webview
    from intext.app import App, _patch_transparent_show
    from intext.config import Settings
    from intext.translate import Translation
    from intext import platform_win as win

    win.enable_dpi_awareness()
    _patch_transparent_show()
    app = App(Settings(model='local-fixture', source='en', target='zh', pinned=True))
    app._pinned = True
    app._place = lambda *_: None
    app._arm_popup_blur = lambda _: None
    app._sync_taskbar = lambda *_: None
    requests, cache_flags = [], []
    slow_started, release_slow = threading.Event(), threading.Event()

    def translator(**_):
        source, target = app.settings.source, app.settings.target

        class FixtureTranslator:
            model = 'local-fixture'

            def translate(self, text, *, use_cache=True):
                requests.append((text, source, target))
                cache_flags.append(use_cache)
                if text == 'Slow source':
                    slow_started.set()
                    if not release_slow.wait(8):
                        raise TimeoutError('Fixture translation')
                return Translation('译文：' + text, False, self.model)

        instance = FixtureTranslator()
        instance.source, instance.target = source, target
        return instance

    app.translator = translator

    class Api:
        def submit_text(self, text, generation=None):
            return app.submit_text(text, expected_generation=generation)

        def set_languages(self, payload):
            return app.set_languages(payload)

        def retry_after_edit(self, generation):
            return app.retry(use_cache=True, expected_generation=generation)

        def mark_ready(self, *_):
            pass

        def copy_text(self, _):
            return True

        def hide(self):
            app.hide()

    popup = webview.create_window('Intext workflow probe', url=(root / 'src/intext/assets/popup.html').as_uri(),
        js_api=Api(), width=460, height=312, hidden=True, frameless=True, transparent=True,
        easy_drag=False, text_select=True)
    popup._intext_keep_hidden = True
    app._popup = popup
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

        def wait_for(predicate):
            deadline = time.monotonic() + 8
            while not predicate():
                if time.monotonic() >= deadline:
                    raise TimeoutError('Workflow did not reach expected state')
                time.sleep(.01)

        def protocol(method, params):
            box = {}
            ui(lambda: box.update(task=popup.native.webview.CoreWebView2.CallDevToolsProtocolMethodAsync(method, json.dumps(params))))
            wait_for(lambda: box['task'].IsCompleted)
            return box['task'].GetAwaiter().GetResult()

        def key(name, code, virtual_key, modifiers=0):
            for kind in ('keyDown', 'keyUp'):
                protocol('Input.dispatchKeyEvent', {'type': kind, 'key': name, 'code': code,
                    'windowsVirtualKeyCode': virtual_key, 'modifiers': modifiers})

        def click_source():
            rect = popup.evaluate_js("(() => {const r=source.getBoundingClientRect();return {x:r.x+8,y:r.y+9};})()")
            for kind in ('mousePressed', 'mouseReleased'):
                protocol('Input.dispatchMouseEvent', {'type': kind, **rect, 'button':'left', 'clickCount':1})

        try:
            if not popup.events.loaded.wait(20):
                raise TimeoutError('WebView loaded')
            ui(lambda: (app._prepare_tool_window(popup, (460, 312)), setattr(popup.native, 'Location', Point(240, 180))))
            app.tray_action('input')
            wait_for(lambda: popup.evaluate_js("!input.hidden && document.activeElement === input"))
            check(popup.evaluate_js("(() => {const css=getComputedStyle(input);return css.backgroundColor==='rgba(0, 0, 0, 0)' && css.boxShadow==='none' && css.borderWidth==='0px'})()"),
                'tray input opens the borderless editor')
            check(app._capture(lambda: None), 'empty selection starts input')
            wait_for(lambda: popup.evaluate_js("!input.hidden && document.activeElement === input"))
            protocol('Input.insertText', {'text':'Test message'})
            key('Enter', 'Enter', 13, 2)
            wait_for(lambda: popup.evaluate_js("!result.hidden && result.textContent === '译文：Test message'"))
            check(popup.evaluate_js("source.textContent === 'Test message' && input.hidden"), 'manual input becomes an editable result')
            click_source()
            wait_for(lambda: popup.evaluate_js("!input.hidden && input.value === 'Test message'"))
            popup.evaluate_js("input.select()")
            protocol('Input.insertText', {'text':'Discard this draft'})
            popup.evaluate_js("document.getElementById('to').click();[...document.querySelectorAll('.language-option')].find(e=>e.textContent==='日语').click()")
            wait_for(lambda: popup.evaluate_js("document.getElementById('to').textContent === '日语' && !document.getElementById('submit').disabled"))
            check(popup.evaluate_js("input.value === 'Discard this draft' && !document.getElementById('edit-note').hidden") and len(requests) == 1,
                'language change keeps the draft without retranslating the old source')
            popup.evaluate_js("document.getElementById('cancel-edit').click()")
            wait_for(lambda: len(requests) == 2 and app._popup_state.get('result') == '译文：Test message' and
                popup.evaluate_js("input.hidden && result.textContent === '译文：Test message' && appliedSeq") == app._gen)
            check(requests[-1] == ('Test message', 'en', 'ja') and cache_flags[-1], 'cancel retranslates the original in the selected language')
            click_source()
            wait_for(lambda: popup.evaluate_js("!input.hidden && input.value === 'Test message'"))
            popup.evaluate_js("input.select()")
            protocol('Input.insertText', {'text':'Edited source'})
            popup.evaluate_js("document.getElementById('to').click();[...document.querySelectorAll('.language-option')].find(e=>e.textContent==='韩语').click()")
            wait_for(lambda: popup.evaluate_js("document.getElementById('to').textContent === '韩语' && !document.getElementById('submit').disabled"))
            check(len(requests) == 2 and popup.evaluate_js("input.value === 'Edited source'"), 'second language edit preserves its draft')
            popup.evaluate_js('input.focus()')
            key('Enter', 'Enter', 13, 2)
            wait_for(lambda: popup.evaluate_js("input.hidden && source.textContent === 'Edited source' && result.textContent === '译文：Edited source'"))
            check(requests[-1] == ('Edited source', 'en', 'ko'), 'edited text uses the chosen language')

            check(app._capture(lambda: 'Slow source'), 'slow selection starts translation')
            wait_for(slow_started.is_set)
            wait_for(lambda: popup.evaluate_js("source.textContent === 'Slow source' && result.textContent.includes('正在翻译')"))
            click_source()
            wait_for(lambda: popup.evaluate_js("!input.hidden && input.value === 'Slow source'"))
            popup.evaluate_js("input.setSelectionRange(input.value.length,input.value.length)")
            protocol('Input.insertText', {'text':' edited'})
            release_slow.set()
            wait_for(lambda: popup.evaluate_js("result.textContent === '译文：Slow source'"))
            check(popup.evaluate_js("!input.hidden && input.value === 'Slow source edited' && !document.getElementById('edit-note').hidden"),
                'late translation leaves an active draft intact')
            report['passed'] = True
        except Exception:
            report['error'] = traceback.format_exc()
        finally:
            release_slow.set()
            popup.destroy()
            if previous:
                win.user32.SetForegroundWindow(previous)

    webview.start(inspect)
    app.cache.disk.close()
    app._http.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    profile.cleanup()
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
