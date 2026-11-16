"""Windows WebView2 regression probe for selection, clipboard and window dragging.

Uses owned test windows and restores the text clipboard. Run with --output PATH.
No translation services, settings or global hotkeys are used.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
import traceback
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'src'))
    import webview
    from intext.app import App, _patch_transparent_show
    from intext import platform_win as win
    win.enable_dpi_awareness()
    _patch_transparent_show()
    calls = []
    moving_view = [None]

    class Api:
        def copy_text(self, text):
            return win.set_clipboard_text(text)

        def begin_drag(self):
            calls.append('drag')
            if moving_view[0] is not None:
                app.begin_drag(moving_view[0])

        def begin_resize(self, edge):
            calls.append('resize:' + edge)

        def end_resize(self):
            pass

        def mark_ready(self, *args):
            pass

        def hide(self):
            calls.append('hide')

    views = [webview.create_window('Intext interaction probe ' + name,
             url=(root / 'src/intext/assets' / name).as_uri(), js_api=Api(),
             width=640, height=440, hidden=True, frameless=True, transparent=True,
             easy_drag=False, text_select=True)
             for name in ('popup.html', 'shot-overlay.html')]
    for view in views:
        view._intext_keep_hidden = True
    app = App.__new__(App)
    app._popup, app._shot_window = views
    app._settings_window = app._tray_menu = None
    app._arm_popup_blur = lambda _: None
    report = {'passed': False, 'checks': {}, 'observations': {}}

    def inspect():
        from System import Action
        from System.Drawing import Point
        previous = None
        touched_clipboard = False
        original_cursor = win.wintypes.POINT()
        win.user32.GetCursorPos(ctypes.byref(original_cursor))

        def ui(work):
            views[0].native.Invoke(Action(work))

        def check(value, name):
            report['checks'][name] = bool(value)

        def protocol(view, method, params):
            box = {}
            ui(lambda: box.update(task=view.native.webview.CoreWebView2.CallDevToolsProtocolMethodAsync(method, json.dumps(params))))
            end = time.monotonic() + 5
            while not box['task'].IsCompleted:
                if time.monotonic() > end:
                    raise TimeoutError(method)
                time.sleep(.01)
            return box['task'].GetAwaiter().GetResult()

        def key(view, name):
            codes = {'c': 67, 'x': 88, 'v': 86, 'z': 90, 'Insert': 45}
            for kind in ('keyDown', 'keyUp'):
                protocol(view, 'Input.dispatchKeyEvent', {'type': kind, 'key': name,
                    'code': 'Key' + name.upper() if len(name) == 1 else name,
                    'windowsVirtualKeyCode': codes[name], 'modifiers': 2})
            time.sleep(.15)

        def select(view, selector, start, end):
            return view.evaluate_js('''(() => {
                const el=document.querySelector(%s);
                const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);
                const node=walker.nextNode(),range=document.createRange();
                range.setStart(node,%d);range.setEnd(node,%d);
                const sel=getSelection();sel.removeAllRanges();sel.addRange(range);
                return sel.toString();
            })()''' % (json.dumps(selector), start, end))

        def copy_selection(view, selector, start, end, name, chord='c'):
            rect = view.evaluate_js('''(() => {const r=document.querySelector(%s).getBoundingClientRect();
                return {x:r.x+8,y:r.y+8};})()''' % json.dumps(selector))
            box = {}
            ui(lambda: box.update(point=view.native.PointToScreen(Point(round(rect['x'] * view.native._scale), round(rect['y'] * view.native._scale)))))
            win.user32.SetCursorPos(box['point'].X, box['point'].Y)
            win.user32.mouse_event(2, 0, 0, 0, 0)
            win.user32.mouse_event(4, 0, 0, 0, 0)
            time.sleep(.1)
            expected = select(view, selector, start, end)
            win.set_clipboard_text('clipboard sentinel')
            key(view, chord)
            actual = win.clipboard_text()
            report['observations'][name] = {'expected': expected, 'clipboardMatches': actual == expected,
                'focus': view.evaluate_js('document.hasFocus()'),
                'nativeFocus': win.focused_hwnd(),
                'trace': view.evaluate_js('window.__keys')}
            check(actual == expected, name)

        def native_copy_after_reopen(view, selector, name):
            ui(lambda: app._hide_native(view))
            ui(lambda: app._show_native(view))
            time.sleep(.2)
            expected = select(view, selector, 0, 5)
            ancestor = ctypes.WINFUNCTYPE(win.wintypes.HWND, win.wintypes.HWND, win.wintypes.UINT)(('GetAncestor', win.user32))
            owned = ancestor(win.focused_hwnd(), 2) == int(view.native.Handle.ToInt64())
            check(owned, name + ' owns keyboard focus')
            if not owned:
                return  # Never send keyboard input to another application.
            win.set_clipboard_text('clipboard sentinel')
            check(win.send_ctrl_c(), name + ' sends Ctrl+C')
            deadline = time.monotonic() + 2
            while win.clipboard_text() != expected and time.monotonic() < deadline:
                time.sleep(.01)
            check(win.clipboard_text() == expected, name + ' copies after reopening')

        def native_drag(view, selector, name, should_move=True):
            rect = view.evaluate_js('''(() => {const r=document.querySelector(%s).getBoundingClientRect();
                return {x:r.x+r.width/2,y:r.y+r.height/2};})()''' % json.dumps(selector))
            box = {}
            ui(lambda: box.update(point=view.native.PointToScreen(Point(round(rect['x'] * view.native._scale), round(rect['y'] * view.native._scale))),
                                  left=view.native.Left, top=view.native.Top))
            moving_view[0] = view
            try:
                win.user32.SetCursorPos(box['point'].X, box['point'].Y)
                win.user32.mouse_event(2, 0, 0, 0, 0)
                time.sleep(.2)
                win.user32.SetCursorPos(box['point'].X + 45, box['point'].Y + 25)
                time.sleep(.15)
            finally:
                win.user32.mouse_event(4, 0, 0, 0, 0)
                moving_view[0] = None
            time.sleep(.2)
            moved = abs(view.native.Left - box['left']) >= 30 and abs(view.native.Top - box['top']) >= 15
            check(moved == should_move, name)

        try:
            for view in views:
                if not view.events.loaded.wait(20):
                    raise TimeoutError('WebView loaded')
            if not win.clipboard_safe_to_replace():
                raise RuntimeError('Clipboard contains non-text data; clipboard probe was not run')
            previous = win.clipboard_text()
            touched_clipboard = True
            for view in views:
                ui(lambda: app._show_native(view))
                time.sleep(.3)
                view.evaluate_js('''window.__keys=[];
                    document.addEventListener('keydown',e=>setTimeout(()=>__keys.push({key:e.key,ctrl:e.ctrlKey,prevented:e.defaultPrevented}),0));''')
                protocol(view, 'Input.dispatchMouseEvent', {'type':'mousePressed','x':100,'y':80,'button':'left','clickCount':1})
                protocol(view, 'Input.dispatchMouseEvent', {'type':'mouseReleased','x':100,'y':80,'button':'left','clickCount':1})
                if view is views[0]:
                    view.evaluate_js("intext.apply({seq:1,source:'Original selection text',result:'Translated selection text',from:'English',to:'中文',model:'probe'})")
                    copy_selection(view, '#result', 0, 10, 'popup partial Ctrl+C')
                    copy_selection(view, '#source', 0, 8, 'source partial Ctrl+C')
                    copy_selection(view, '#result', 11, 20, 'popup Ctrl+Insert', 'Insert')
                    native_copy_after_reopen(view, '#result', 'popup native keyboard')
                    view.evaluate_js("intext.apply({seq:2,mode:'input',enter:true});document.getElementById('input').value='Editable draft';document.getElementById('input').setSelectionRange(0,8)")
                    win.set_clipboard_text('clipboard sentinel')
                    key(view, 'c')
                    check(win.clipboard_text() == 'Editable', 'input copy')
                    key(view, 'x')
                    check(view.evaluate_js("document.getElementById('input').value") == ' draft', 'input cut')
                    key(view, 'v')
                    check(view.evaluate_js("document.getElementById('input').value") == 'Editable draft', 'input paste')
                    key(view, 'z')
                    check(view.evaluate_js("document.getElementById('input').value") == ' draft', 'input undo')
                else:
                    view.evaluate_js("""const c=document.createElement('canvas');c.width=360;c.height=120;
                        intextShot.apply({seq:1,width:360,height:120,image:c.toDataURL(),text:'Overlay selection text',
                        blocks:[{text:'Overlay selection text',left:5,top:10,width:90,height:40,fontSize:22,background:'white',color:'black'}]})""")
                    copy_selection(view, '.region', 0, 7, 'overlay partial Ctrl+C')
                    copy_selection(view, '.region', 8, 17, 'overlay Ctrl+Insert', 'Insert')
                    copy_selection(view, '.region', 8, 12, 'overlay consecutive selection')
                    native_copy_after_reopen(view, '.region', 'overlay native keyboard')
                    # Test routing separately from actual OS window movement.
                    for selector in ('.head', '.foot', '#viewport', '#panel'):
                        before = len(calls)
                        view.evaluate_js('document.querySelector(%s).dispatchEvent(new MouseEvent("mousedown",{button:0,bubbles:true,cancelable:true}))' % json.dumps(selector))
                        time.sleep(.1)
                        check(calls[before:] == ['drag'], 'overlay drag ' + selector)
                    for selector in ('#image', '#labels', '.region', '#copy svg', '#model', '#close', '.resize-n'):
                        before = len(calls)
                        view.evaluate_js('document.querySelector(%s).dispatchEvent(new MouseEvent("mousedown",{button:0,bubbles:true,cancelable:true}))' % json.dumps(selector))
                        time.sleep(.1)
                        check('drag' not in calls[before:], 'overlay preserves ' + selector)
                    native_drag(view, '#image-frame', 'image selection does not move the window', should_move=False)
                    view.evaluate_js("intextShot.apply({...current,seq:2,busy:true,blocks:[],status:'正在翻译…'})")
                    native_drag(view, '#viewport', 'loading panel moves the native window')
                    native_drag(view, '.foot', 'footer gap moves the native window')
                ui(lambda: app._hide_native(view))
            report['passed'] = all(report['checks'].values())
        except Exception:
            report['error'] = traceback.format_exc()
        finally:
            if touched_clipboard:
                win._restore_clipboard(previous)
            win.user32.SetCursorPos(original_cursor.x, original_cursor.y)
            for view in reversed(views):
                view.destroy()

    webview.start(inspect)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
