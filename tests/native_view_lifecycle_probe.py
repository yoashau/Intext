"""Compare prebuilt, lazy and low-memory WebView lifecycles on Windows.

Uses only owned windows and local assets; no user configuration or services.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import traceback
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--strategy', choices=['prebuilt', 'lazy', 'low'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / 'src'), str(root / 'tests')]
    import webview
    from intext.app import _patch_transparent_show
    from intext.platform_win import enable_dpi_awareness
    from performance_probe import process_sample
    enable_dpi_awareness()
    _patch_transparent_show()
    files = ['popup.html', 'settings.html', 'tray-menu.html', 'shot-overlay.html']
    views = {}

    def create(file):
        view = webview.create_window('Intext view lifecycle probe',
            url=(root / 'src/intext/assets' / file).as_uri(), width=640, height=440,
            hidden=True, frameless=True, text_select=True, easy_drag=False)
        view._intext_keep_hidden = True
        views[file] = view
        return view

    master = create(files[0])
    if args.strategy != 'lazy':
        for file in files[1:]:
            create(file)
    report = {'strategy': args.strategy, 'passed': False, 'firstOpenMs': {}, 'warmOpenMs': {}}

    def run():
        from System import Action

        def ui(work):
            master.native.Invoke(Action(work))

        def level(view, low):
            if args.strategy != 'low':
                return
            from Microsoft.Web.WebView2.Core import CoreWebView2MemoryUsageTargetLevel as Level
            ui(lambda: setattr(view.native.webview.CoreWebView2, 'MemoryUsageTargetLevel',
                               Level.Low if low else Level.Normal))

        def sample():
            pids = {os.getpid()}
            def enumerate_pids():
                for view in views.values():
                    pids.update(int(p.ProcessId) for p in view.native.webview.CoreWebView2.Environment.GetProcessInfos())
            ui(enumerate_pids)
            metrics = [process_sample(pid) for pid in pids]
            return {'views': len(views), 'processes': len(pids),
                    'sumPrivateMiB': round(sum(m['privateMiB'] for m in metrics if m), 2),
                    'sumProcessWorkingSetsMiB': round(sum(m['workingSetMiB'] for m in metrics if m), 2)}

        def prepare(view, file):
            if file == 'popup.html':
                view.evaluate_js("intext.apply({seq:1,from:'English',to:'中文',source:'Synthetic source',result:'合成译文',model:'probe'})")
            elif file == 'shot-overlay.html':
                view.evaluate_js("intextShot.apply({seq:1,busy:true,status:'正在识别…',blocks:[]})")

        def open_frame(file):
            start = time.perf_counter()
            view = views.get(file)
            if view is None:
                view = create(file)
                if not view.events.loaded.wait(20):
                    raise TimeoutError(file)
                prepare(view, file)
            level(view, False)
            view.show()
            view.evaluate_js('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve(true))))')
            elapsed = round((time.perf_counter() - start) * 1000, 3)
            view.hide()
            level(view, True)
            return elapsed

        try:
            for file, view in views.items():
                if not view.events.loaded.wait(20):
                    raise TimeoutError(file)
                prepare(view, file)
                level(view, True)
            time.sleep(1)
            report['initialHiddenMemory'] = sample()
            for file in files[1:]:
                report['firstOpenMs'][file] = open_frame(file)
            for file in files[1:]:
                report['warmOpenMs'][file] = [open_frame(file) for _ in range(3)]
            time.sleep(1)
            report['allCreatedHiddenMemory'] = sample()
            report['warmMedianMs'] = statistics.median(v for values in report['warmOpenMs'].values() for v in values)
            report['passed'] = True
        except Exception:
            report['error'] = traceback.format_exc()
        finally:
            for view in reversed(list(views.values())):
                view.destroy()

    webview.start(run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
