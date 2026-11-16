"""Reproducible Windows resource/latency measurements using synthetic content.

Run --mode core or --mode webview --output report.json. No user settings,
screenshots, clipboard, global shortcuts or network translation are used.
"""
from __future__ import annotations

import argparse
import ctypes
import io
import json
import os
import statistics
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path


class Memory(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in ('peak_working', 'working', 'peak_paged', 'paged',
        'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile', 'private')]


def process_sample(pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Memory), wintypes.DWORD]
    handle = kernel.OpenProcess(0x410, False, pid)
    if not handle:
        return None
    try:
        memory = Memory(cb=ctypes.sizeof(Memory))
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
            return None
        times = [wintypes.FILETIME() for _ in range(4)]
        kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times))
        cpu = sum((t.dwHighDateTime << 32) + t.dwLowDateTime for t in times[2:]) / 10_000_000
        return {'privateMiB': round(memory.private / 2**20, 2),
                'workingSetMiB': round(memory.working / 2**20, 2),
                'peakWorkingSetMiB': round(memory.peak_working / 2**20, 2), 'cpuSeconds': cpu}
    finally:
        kernel.CloseHandle(handle)


def timed(work, count=1):
    values = []
    for _ in range(count):
        start = time.perf_counter()
        work()
        values.append(round((time.perf_counter() - start) * 1000, 3))
    return {'medianMs': statistics.median(values), 'samplesMs': values}


def idle(pids, seconds=3):
    before = {pid: process_sample(pid) for pid in pids}
    start = time.perf_counter()
    time.sleep(seconds)
    after = {pid: process_sample(pid) for pid in pids}
    elapsed = time.perf_counter() - start
    delta = sum(max(0, after[pid]['cpuSeconds'] - before[pid]['cpuSeconds']) for pid in pids if before[pid] and after[pid])
    return {'seconds': round(elapsed, 3), 'cpuSeconds': round(delta, 4),
            'oneCorePercent': round(delta / elapsed * 100, 3),
            'machinePercent': round(delta / elapsed / (os.cpu_count() or 1) * 100, 3),
            'sumPrivateMiB': round(sum(p['privateMiB'] for p in after.values() if p), 2),
            'processes': len([p for p in after.values() if p])}


def synthetic_image():
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new('RGB', (1200, 520), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 28)
    for i in range(8):
        draw.text((24, 16 + i * 60), f'Intext OCR {i + 1}: 截图翻译性能测试 12345', font=font, fill='black')
    return image


def core():
    from PIL import Image
    from intext.cache import SqliteCache
    from intext.screenshot import Screenshot, Selection, mask_screenshot
    from intext import ocr
    report = {'logicalCPUs': os.cpu_count(), 'start': process_sample(os.getpid())}
    def checkpoint():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    image = synthetic_image()
    selection = Selection((0, 0, *image.size), ((0, 0), (image.width-1, 0), (image.width-1, image.height-1), (0, image.height-1)))
    shot = mask_screenshot(image, selection)
    report['exportTextScreenshot'] = timed(lambda: mask_screenshot(image, selection), 5)
    report['dataUrl'] = timed(lambda: shot.data_url, 20)
    report['dataUrlBytes'] = len(shot.data_url)
    checkpoint()
    if not args.skip_ocr:
        if args.rec_batch_size is not None:
            ocr._engine('ch').cfg.Rec.rec_batch_num = args.rec_batch_size
            report['recognitionBatchSize'] = args.rec_batch_size
        pages = []
        report['ocrCold'] = timed(lambda: pages.append(ocr.recognize(shot)))
        checkpoint()
        page = pages[-1]
        if args.warm_runs:
            report['ocrWarm'] = timed(lambda: ocr.recognize(shot), args.warm_runs)
        checkpoint()
        report['ocrLines'] = len(page.regions)
        report['ocrIdle'] = idle([os.getpid()])
        checkpoint()
        report['secondLanguageWrapperCreate'] = timed(lambda: ocr._engine('latin'))
        report['secondLanguageWrapperMemory'] = process_sample(os.getpid())
        report['postOcrSettledIdle'] = idle([os.getpid()])
        checkpoint()
    with tempfile.TemporaryDirectory() as folder:
        cache = SqliteCache(Path(folder) / 'benchmark.sqlite')
        try:
            for i in range(2000):
                cache.put(str(i), '译文' * 100)
            report['cacheGet'] = timed(lambda: cache.get('1999'), 100)
            count = iter(range(2000, 2020))
            report['cachePutFull'] = timed(lambda: cache.put(str(next(count)), 'new result'), 20)
        finally:
            cache.close()
    # Photographic/noisy screenshots exercise PNG/base64 costs hidden by the
    # very small compressed text-only fixture above. No desktop pixels used.
    noisy = Image.effect_noise((1920, 1080), 80).convert('RGB')
    output = io.BytesIO(); noisy.save(output, format='PNG')
    large = Screenshot(output.getvalue(), Selection((0, 0, *noisy.size), ()))
    report['largeDataUrlCold'] = timed(lambda: large.data_url)
    report['largeDataUrlBytes'] = len(large.data_url)
    report['largeDataUrl'] = timed(lambda: large.data_url, 10)
    report['end'] = process_sample(os.getpid())
    return report


def webviews():
    import webview
    from intext.app import _patch_transparent_show
    _patch_transparent_show()
    assets = Path(__file__).resolve().parents[1] / 'src/intext/assets'
    views = [webview.create_window('Intext performance probe', url=(assets / name).as_uri(),
             width=640, height=440, hidden=True, frameless=True, text_select=True, easy_drag=False)
             for name in ('popup.html', 'settings.html', 'tray-menu.html', 'shot-overlay.html')]
    for view in views:
        view._intext_keep_hidden = True
    report = {}

    def run():
        from System import Action
        try:
            for view in views:
                if not view.events.loaded.wait(20):
                    raise TimeoutError('WebView loaded')
            pids = {os.getpid()}
            def read_pids():
                for view in views:
                    pids.update(int(info.ProcessId) for info in view.native.webview.CoreWebView2.Environment.GetProcessInfos())
            views[0].native.Invoke(Action(read_pids))
            report['windows'] = len(views)
            report['hiddenIdle'] = idle(pids)
            views[0].evaluate_js("intext.apply({seq:1,from:'English',to:'中文',source:'Synthetic source',result:'合成译文',model:'probe'})")
            views[0].show()
            time.sleep(.8)  # Exclude first paint/font/entrance work from idle.
            report['visibleIdle'] = idle(pids)
            views[0].hide()
            report['hiddenAgainIdle'] = idle(pids)
        except Exception:
            import traceback
            report['error'] = traceback.format_exc()
        finally:
            for view in reversed(views):
                view.destroy()
    webview.start(run)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['core', 'webview'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rec-batch-size', type=int)
    parser.add_argument('--skip-ocr', action='store_true')
    parser.add_argument('--warm-runs', type=int, default=3)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    import faulthandler
    trace = args.output.with_suffix('.trace').open('w')
    faulthandler.dump_traceback_later(30, repeat=True, file=trace)
    try:
        result = core() if args.mode == 'core' else webviews()
    except Exception:
        import traceback
        result = {'error': traceback.format_exc()}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
