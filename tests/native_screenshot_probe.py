"""Exercise all four screenshot modes in real Windows WebViews with local fixtures.

No user configuration, screenshot, credentials or remote service is used.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path


def main() -> int:
    if sys.platform != 'win32':
        raise SystemExit('Run with Windows Python')
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'src'))
    output = Path(tempfile.gettempdir()) / 'intext-screenshot-probe'
    output.mkdir(exist_ok=True)
    os.environ['APPDATA'] = tempfile.mkdtemp(prefix='profile-', dir=output)
    from PIL import Image, ImageDraw, ImageFont
    from intext import app as module
    from intext.config import Settings
    from intext.screenshot import Screenshot, Selection
    from intext import capture_win

    image = Image.new('RGB', (760, 270), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 30)
    draw.text((24, 22), 'Preserve the original structure', fill='black', font=font)
    draw.text((24, 105), 'Intext OCR 12345', fill='black', font=font)
    draw.text((24, 190), 'a = b + 42', fill='black', font=font)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    shot = Screenshot(buffer.getvalue(), Selection((200, 200, *image.size), ()))
    capture_win.capture_shot = lambda: shot
    # Keep the fixture visible while OS focus moves among the test WebViews.
    # Unpinned dismiss behavior is covered by test_app and test_dismiss.
    app = module.App(Settings(model='local-integration-fixture', source='en', pinned=True))
    module.App = lambda: app
    requests = []

    class FixtureProvider:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
        def translate(self, text):
            from intext.translate import messages_for
            return self.complete(messages_for(text, self.source, self.target))
        def complete(self, messages):
            requests.append(messages)
            content = messages[1]['content']
            text = content[0]['text'] if isinstance(content, list) else content
            if text.startswith('{"regions"'):
                regions = json.loads(text)['regions']
                return json.dumps({'regions': [{'id': r['id'], 'text': f'原位译文 {r["id"]}'} for r in regions]}, ensure_ascii=False)
            return '# 保留原文结构\n\n- 截图翻译测试\n- 12345\n\n公式 $a=b+42$'

    module.OpenAICompatibleProvider = FixtureProvider
    report = {'passed': False, 'cases': []}

    def wait_for(predicate, seconds=30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.05)
        raise TimeoutError('Native screenshot integration wait')

    def inspect(_app):
        try:
            for window in (app._popup, app._settings_window, app._shot_window, app._tray_menu):
                if not window.events.loaded.wait(15):
                    raise TimeoutError('WebView did not load')
            wait_for(lambda: app._shot_ready)
            for method in ('ocr', 'image'):
                for view in ('popup', 'overlay'):
                    app.settings.shot_input, app.settings.shot_display = method, view
                    app.on_shot()
                    gen = app._gen
                    if view == 'overlay':
                        wait_for(lambda: app._shot_state and app._shot_state.get('seq') == gen and not app._shot_state.get('busy'))
                        if app._shot_state.get('error'):
                            raise RuntimeError(app._shot_state['error'])
                        window = app._shot_window
                        wait_for(lambda: window.evaluate_js("document.querySelectorAll('.region').length") == len(app._shot_state['blocks']))
                        observed = window.evaluate_js("({blocks:document.querySelectorAll('.region').length, image:!!document.querySelector('#image').naturalWidth, text:document.querySelector('#labels').textContent})")
                        if not observed['image'] or observed['blocks'] < 3:
                            raise AssertionError(observed)
                        window.evaluate_js("document.getElementById('original').click()")
                        if not window.evaluate_js("document.getElementById('labels').hidden"):
                            raise AssertionError('Original comparison failed')
                        window.evaluate_js("document.getElementById('original').click()")
                    else:
                        wait_for(lambda: app._popup_state and app._popup_state.get('seq') == gen and bool(app._popup_state.get('result')))
                        window = app._popup
                        wait_for(lambda: window.evaluate_js("document.querySelectorAll('#result h1').length") == 1)
                        observed = window.evaluate_js("({heading:document.querySelector('#result h1').textContent, math:!!document.querySelector('#result .katex'), sourceImage:!document.querySelector('#shot-image').hidden})")
                        if not observed['math'] or observed['sourceImage'] != (method == 'image'):
                            raise AssertionError(observed)
                    if not window.native.Visible:
                        raise AssertionError('Result window is hidden')
                    report['cases'].append({'method': method, 'view': view, 'observed': observed})
                    if method == 'ocr' and view == 'popup':
                        source = app._shot_page[1].text
                        count = len(requests)
                        if app._cached(source) is None:
                            raise AssertionError('Selection fast path cannot find OCR result')
                        app.submit_text(source)
                        if app._popup_state.get('status') != '已缓存' or len(requests) != count:
                            raise AssertionError('Input translation did not reuse OCR result')
                        app.retry()
                        refresh_gen = app._gen
                        wait_for(lambda: app._popup_state.get('seq') == refresh_gen and bool(app._popup_state.get('result')))
                        if len(requests) != count + 1:
                            raise AssertionError('Text retry did not refresh')
                        app.on_shot()
                        shot_gen = app._gen
                        wait_for(lambda: app._popup_state.get('seq') == shot_gen and bool(app._popup_state.get('result')))
                        if app._popup_state.get('status') != '已缓存' or len(requests) != count + 1:
                            raise AssertionError('OCR did not reuse refreshed text result')
                        app.retry()
                        retry_gen = app._gen
                        wait_for(lambda: app._popup_state.get('seq') == retry_gen and bool(app._popup_state.get('result')))
                        if len(requests) != count + 2 or app._cached(source) is None:
                            raise AssertionError('OCR retry did not update shared text cache')
                        report['sharedCache'] = {'selectionFastPath': True, 'inputFromOcr': True,
                                                 'ocrFromTextRefresh': True, 'ocrRetryUpdatesText': True}
                    app.hide_shot()
                    app.hide()
            report['requests'] = len(requests)
            if len(requests) != 6:
                raise AssertionError('Unexpected number of provider calls')
            report['passed'] = True
        except Exception:
            report['error'] = traceback.format_exc()
            report['popup'] = {'requested': app._popup_requested,
                               'visible': bool(app._popup.native.Visible),
                               'status': (app._popup_state or {}).get('status'),
                               'resultLength': len((app._popup_state or {}).get('result', ''))}
        finally:
            (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            app.quit()

    module._shell = inspect
    module.run_gui(silent=True)
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
