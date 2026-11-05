"""Compose the translator, popup, settings window, and tray."""

from __future__ import annotations

import json
import sys
import threading
import time
import traceback
from copy import deepcopy
from pathlib import Path

from .cache import MemoryCache, SqliteCache, TieredCache
from .config import Settings, config_dir, load_settings, log_error, save_settings
from .fields import enabled_payload
from .providers import OpenAICompatibleProvider
from .translate import Translation, TranslationError, Translator, cache_key, language_label, normalize_text, system_prompt

POPUP_SIZE = (460, 312)
TRAY_MENU_SIZE = (248, 160)


def settings_visible_on_launch(*, model: str, settings_only: bool = False, preview: bool = False, silent: bool = False) -> bool:
    return not silent and (settings_only or (not model and not preview))


def asset_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "intext" / "assets"
    return Path(__file__).resolve().parent / "assets"


def _js(payload: object) -> str:
    return (
        json.dumps(payload, ensure_ascii=False)
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _boot(message: str) -> None:
    try:
        path = config_dir() / "boot.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")
    except OSError:
        return


def _apply_script(function_name: str, payload: object, kind: str) -> str:
    """Run a page function without waiting. Retries cover a late bridge."""
    data = _js(payload)
    kind_js = _js(kind)
    return (
        "(function(){"
        f"var payload={data};"
        f"var kind={kind_js};"
        "var tries=0;"
        "function mark(){"
        "try{if(window.pywebview&&window.pywebview.api&&window.pywebview.api.mark_ready){window.pywebview.api.mark_ready(kind);}}catch(e){}"
        "}"
        "function run(){"
        "var fn;"
        "try{fn=" + function_name + ";}catch(e){fn=null;}"
        "if(typeof fn==='function'){fn(payload);mark();return 'applied';}"
        "if(++tries<40){setTimeout(run,50);return 'waiting';}"
        "return 'missing';"
        "}"
        "return run();"
        "})()"
    )


_UI_DELEGATES: list = []


def _keep_delegate(callback) -> None:
    _UI_DELEGATES.append(callback)


def _drop_delegate(callback) -> None:
    if callback is None:
        return
    try:
        _UI_DELEGATES.remove(callback)
    except ValueError:
        return


def _install_exception_log() -> None:
    """Record WinForms thread exceptions instead of leaving a modal dialog up."""
    def on_thread(args) -> None:
        log_error(
            "thread-exception\n"
            + "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        )

    threading.excepthook = on_thread
    try:
        import clr

        clr.AddReference("System.Windows.Forms")
        from System import AppDomain
        from System.Windows.Forms import Application, UnhandledExceptionMode

        def on_thread(_sender, args) -> None:
            log_error("ui-exception\n" + str(getattr(args, "Exception", args)))

        def on_domain(_sender, args) -> None:
            log_error("domain-exception\n" + str(getattr(args, "ExceptionObject", args)))

        Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException)
        Application.ThreadException += on_thread
        AppDomain.CurrentDomain.UnhandledException += on_domain
        _keep_delegate(on_thread)
        _keep_delegate(on_domain)
    except Exception:
        log_error(traceback.format_exc())


def _patch_evaluate_js() -> None:
    """Keep pywebview's blocking script call off the UI thread.

    Its completion callback also has to run on that thread. Calling it there
    freezes the window. Off-thread controller access raises instead. Page
    injection uses the original call from a background thread and must stay
    ordered, so only the UI-thread path is replaced.
    """
    from webview.platforms.edgechromium import EdgeChrome

    if getattr(EdgeChrome.evaluate_js, "_intext_safe", False):
        return
    original = EdgeChrome.evaluate_js

    def evaluate_js(self, script, parse_json):
        try:
            on_ui = not self.webview.InvokeRequired
        except Exception:
            log_error(traceback.format_exc())
            return None
        if not on_ui:
            return original(self, script, parse_json)
        try:
            self.webview.ExecuteScriptAsync(script)
        except Exception:
            log_error(traceback.format_exc())
        return None

    evaluate_js._intext_safe = True
    EdgeChrome.evaluate_js = evaluate_js


def _patch_transparent_show() -> None:
    """Keep a hidden settings window hidden while transparency initializes."""
    from webview.platforms.edgechromium import EdgeChrome

    if getattr(EdgeChrome.on_navigation_start, "_intext_hide", False):
        return
    original = EdgeChrome.on_navigation_start

    def on_navigation_start(self, sender, args):
        window = self.pywebview_window
        if getattr(window, "_intext_keep_hidden", False):
            # The backend's transparent-navigation hook calls Show/Activate.
            # Hidden startup windows must not flash or take foreground focus.
            return
        original(self, sender, args)

    on_navigation_start._intext_hide = True
    EdgeChrome.on_navigation_start = on_navigation_start




class App:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self.cache = TieredCache(MemoryCache(), SqliteCache(config_dir() / "cache.sqlite"))
        self._gen = 0
        self._pinned = bool(self.settings.pinned)
        self._popup_requested = False
        self._last_text = ""
        self._last_shot = None
        self._shot_context = None
        self._shot_page = None
        self._shot_window = None
        self._shot_hwnd = 0
        self._shot_state = None
        self._shot_ready = False
        self._shot_requested = False
        self._popup_state = None
        self._popup = None
        self._popup_hwnd = 0
        self._settings_window = None
        self._tray_menu = None
        self._tray_ready = False
        self._tray_pending = None
        self._tray_generation = 0
        self._quitting = False
        self._quit_timer = None
        self._settings_only = False
        self._preview = False
        self._selecting = threading.Lock()
        self._settings_lock = threading.Lock()
        self._resize_token = 0
        self._hold_show = False
        self._show_epoch = 0
        self._ui_refs: list = []

    def icon_path(self, *, tray: bool = False) -> Path:
        from .platform_win import system_uses_light_theme

        prefix = "tray" if tray else "intext"
        name = f"{prefix}.ico" if system_uses_light_theme() else f"{prefix}-on-dark.ico"
        return asset_dir() / name

    def translator(self) -> Translator:
        settings = self.settings
        options = enabled_payload(settings.fields)
        provider = OpenAICompatibleProvider(
            endpoint=settings.endpoint,
            api_key=settings.api_key,
            model=settings.model,
            source=settings.source,
            target=settings.target,
            optional_fields=options,
        )
        return Translator(
            provider,
            self.cache,
            source=settings.source,
            target=settings.target,
            endpoint=settings.endpoint,
            model=settings.model,
            optional_fields=options,
        )

    def translate_text(self, text: str):
        return self.translator().translate(text)

    def on_hotkey(self) -> None:
        try:
            _boot("hotkey")
            # Read the selection before the popup is shown. Showing first
            # steals focus, and Ctrl+C then copies an empty translation pane.
            self._capture(self._read_selection)
        except Exception:
            log_error(traceback.format_exc())
            _boot("hotkey-failed")
            self._show_hotkey_failure()

    def _show_hotkey_failure(self) -> None:
        try:
            state = dict(self._popup_state or self._base_state(self._last_text))
            state["status"] = "识别失败"
            self._push(state, enter=True)
        except Exception:
            log_error(traceback.format_exc())
            _boot("hotkey-failed-ui")

    def _popup_hwnd_now(self) -> int:
        return int(self._popup_hwnd or 0)

    def on_shot(self) -> None:
        if not self._selecting.acquire(blocking=False):
            return
        was_visible = False
        captured = False
        try:
            _boot("shot")
            from .platform_win import hide_owned_window, window_visible
            from .capture_win import capture_shot

            hwnd = self._popup_hwnd_now()
            was_visible = window_visible(hwnd)
            self._hold_show = True
            hide_owned_window(hwnd)
            hide_owned_window(self._shot_hwnd)
            if self._shot_window is not None:
                self._on_ui(self._shot_window, lambda: self._hide_native(self._shot_window))
            shot = capture_shot()
            if shot is not None:
                captured = True
                self._gen += 1
                self._last_shot, self._last_text, self._shot_page = shot, "", None
                self._shot_context = deepcopy(self.settings)
        except Exception as exc:
            log_error(traceback.format_exc())
            _boot("shot-failed")
            self._hold_show = False
            state = self._error_state("", "截图失败")
            state["status"] = f"截图失败：{exc}"
            self._push(state, enter=True)
            return
        finally:
            self._hold_show = False
            self._selecting.release()
            if not captured:
                if was_visible:
                    self._reveal(dict(self._popup_state or self._base_state(self._last_text)))
                else:
                    self._show_epoch += 1
                if self._shot_requested and self._shot_state:
                    self._push_shot(self._shot_state, reveal=True)
        if captured:
            self._start_shot(self._gen, self._shot_context)

    def _start_shot(self, gen: int, settings, *, use_cache: bool = True) -> None:
        if gen != self._gen:
            return
        shot = self._last_shot
        if shot is None:
            return
        if settings.shot_display == "overlay":
            self.hide()
            self._push_shot({"seq": gen, "image": shot.data_url, "width": shot.selection.rect[2],
                             "height": shot.selection.rect[3], "blocks": [], "busy": True,
                             "model": settings.model, "status": "正在识别…"}, reveal=True)
        else:
            self.hide_shot()
            state = self._recognizing_state()
            state.update(shot=True, image=shot.data_url if settings.shot_input == "image" else "",
                         source="图片直译" if settings.shot_input == "image" else "")
            if settings.shot_input == "image":
                state["status"] = "正在翻译"
            self._push(state, enter=not self._pinned)
        threading.Thread(target=self._finish_shot, args=(shot, gen, settings),
                         kwargs={"use_cache": use_cache}, daemon=True).start()

    def _finish_shot(self, shot, gen: int, settings, *, use_cache: bool = True) -> None:
        from .ocr import recognize
        from .shot_translate import translate_shot

        state = self._base_state("")
        state.update(seq=gen, shot=True, model=settings.model, from_=language_label(settings.source),
                     to=language_label(settings.target), sourceLang=settings.source, resultLang=settings.target)
        state["from"] = state.pop("from_")
        if settings.shot_input == "image":
            state.update(source="图片直译", image=shot.data_url)
        try:
            if gen != self._gen:
                return
            page = None
            if settings.shot_input == "ocr" or settings.shot_display == "overlay":
                cached_page = self._shot_page
                page = cached_page[1] if cached_page and cached_page[0] == settings.source else recognize(shot, settings.source)
                if gen != self._gen:
                    return
                self._shot_page = (settings.source, page)
                state["source"] = page.text
            if gen != self._gen:
                return
            if settings.shot_display == "popup":
                state["status"] = "正在翻译"
                self._push(state, enter=False, reveal=False)
            else:
                self._push_shot({"seq": gen, "image": shot.data_url, "width": shot.selection.rect[2],
                                 "height": shot.selection.rect[3], "blocks": [], "busy": True,
                                 "model": settings.model, "status": "正在翻译…"})
            provider = OpenAICompatibleProvider(endpoint=settings.endpoint, api_key=settings.api_key,
                model=settings.model, source=settings.source, target=settings.target,
                optional_fields=enabled_payload(settings.fields))
            result = translate_shot(shot, provider=provider, cache=self.cache, page=page,
                input_mode=settings.shot_input, display=settings.shot_display, use_cache=use_cache)
            if gen != self._gen:
                return
            if settings.shot_display == "overlay":
                from .shot_overlay import overlay_payload

                self._push_shot({**overlay_payload(shot, page, result.regions), "seq": gen,
                                 "text": result.text, "model": settings.model, "busy": False})
            else:
                state.update(result=result.text, status="已缓存" if result.cached else "未缓存")
                self._push(state, enter=False, reveal=False)
        except Exception as exc:
            if gen != self._gen:
                return
            log_error(traceback.format_exc())
            message = str(exc) if isinstance(exc, TranslationError) else "截图翻译失败"
            if settings.shot_display == "overlay":
                self._push_shot({"seq": gen, "image": shot.data_url, "width": shot.selection.rect[2],
                                 "height": shot.selection.rect[3], "blocks": [], "model": settings.model,
                                 "busy": False, "error": message})
            else:
                state["status"] = message
                self._push(state, enter=False, reveal=False)

    def hide_shot(self) -> None:
        self._shot_requested = False
        window = self._shot_window
        if window is not None:
            window._intext_keep_hidden = True
            self._on_ui(window, lambda: self._hide_native(window))

    def _push_shot(self, state: dict, *, reveal: bool = False) -> None:
        if state.get("seq") != self._gen:
            return
        state = dict(state)
        context = self._shot_context or self.settings
        state.setdefault("from", language_label(context.source))
        state.setdefault("to", language_label(context.target))
        self._shot_state = dict(state)
        if reveal:
            self._shot_requested = True
        window = self._shot_window
        if window is None or not self._shot_requested or not self._shot_ready:
            return
        gen = self._gen

        def apply():
            if gen != self._gen or not self._shot_requested or self._hold_show:
                return
            if reveal:
                from System.Drawing import Point, Size
                from .platform_win import cursor_pos, work_area_at

                native = window.native
                scale = float(native._scale) or 1.0
                x, y, width, height = self._last_shot.selection.rect
                left, top, right, bottom = work_area_at(*cursor_pos())
                w = min(right - left, max(round(320 * scale), width + round(76 * scale)))
                h = min(bottom - top, max(round(240 * scale), height + round(156 * scale)))
                native.ClientSize = Size(w, h)
                native.Location = Point(max(left, min(x - round(38 * scale), right - w)), max(top, min(y - round(74 * scale), bottom - h)))
                window._intext_keep_hidden = False
                self._show_native(window)
            control = self._webview_control(window)
            if control is not None:
                control.ExecuteScriptAsync(_apply_script("window.intextShot.apply", state, "shot"))

        self._on_ui(window, apply)

    def _recognizing_state(self) -> dict:
        state = self._base_state("")
        state["status"] = "正在识别"
        state["result"] = ""
        return state

    def _reveal(self, state: dict) -> None:
        self._popup_requested = True
        self._push(state, enter=True)

    def _capture(self, reader, *, quiet_cancel: bool = False) -> bool:
        if not self._selecting.acquire(blocking=False):
            _boot("capture-busy")
            return False
        # A cancelled shot must not retire the translation already in flight.
        if not quiet_cancel:
            self._gen += 1
        gen = self._gen
        try:
            try:
                text = reader()
            except Exception:
                log_error(traceback.format_exc())
                text = None
        finally:
            self._selecting.release()
        if gen != self._gen:
            return False
        # A cancelled shot must keep holding until on_shot drops queued shows.
        if not (text is None and quiet_cancel):
            self._hold_show = False
        _boot("capture-cancel" if text is None and quiet_cancel else f"captured {len(text or '')}")
        if text is None and quiet_cancel:
            return False
        self._last_shot = None
        self.hide_shot()
        if quiet_cancel:
            self._gen += 1
            gen = self._gen
        if not text:
            self._last_text = ""
            self._push(dict(self._error_state("", "未识别到文字"), seq=gen), enter=True)
            return True
        self._last_text = text
        if not self.settings.model:
            self._push(dict(self._error_state(text, "未配置"), seq=gen), enter=not self._pinned)
            return True
        try:
            cached = self._cached(text)
        except TranslationError as exc:
            self._push(dict(self._error_state(text, str(exc)), seq=gen), enter=True)
            return True
        if gen != self._gen:
            return False
        if cached is not None:
            self._push(dict(self._result_state(text, cached.text, True), seq=gen), enter=not self._pinned)
            return True
        self._push(dict(self._pending_state(text), seq=gen), enter=not self._pinned)
        threading.Thread(target=self._finish, args=(text, gen), daemon=True).start()
        return True

    def _cached(self, text: str) -> Translation | None:
        settings = self.settings
        cleaned = normalize_text(text)
        key = cache_key(
            text=cleaned,
            source=settings.source,
            target=settings.target,
            endpoint=settings.endpoint,
            model=settings.model,
            prompt=system_prompt(settings.source, settings.target),
            options=enabled_payload(settings.fields),
        )
        hit = self.cache.peek(key)
        if hit is None or not str(hit).strip():
            return None
        return Translation(text=hit, cached=True, model=settings.model)

    def _finish(self, text: str, gen: int, *, use_cache: bool = True) -> None:
        if gen != self._gen:
            return
        translator = self.translator()
        state = self._base_state(text)
        state.update({
            "from": language_label(translator.source),
            "to": language_label(translator.target),
            "sourceLang": translator.source if translator.source != "auto" else "",
            "resultLang": translator.target,
            "model": translator.model,
            "seq": gen,
        })
        try:
            result = translator.translate(text, use_cache=use_cache)
        except TranslationError as exc:
            state["status"] = str(exc)
            self._push(state, enter=False, reveal=False)
            return
        except Exception:
            log_error(traceback.format_exc())
            state["status"] = "请求失败"
            self._push(state, enter=False, reveal=False)
            return
        if gen != self._gen:
            return
        state["result"] = result.text
        state["status"] = "已缓存" if result.cached else "未缓存"
        self._push(state, enter=False, reveal=False)

    def _base_state(self, text: str) -> dict:
        settings = self.settings
        return {
            "from": language_label(settings.source),
            "to": language_label(settings.target),
            "source": text,
            "sourceLang": settings.source if settings.source != "auto" else "",
            "result": "",
            "resultLang": settings.target,
            "model": settings.model,
            "pinned": self._pinned,
            "status": "",
            "seq": self._gen,
        }

    def _result_state(self, text: str, result: str, cached: bool) -> dict:
        state = self._base_state(text)
        state["result"] = result
        state["status"] = "已缓存" if cached else "未缓存"
        return state

    def _pending_state(self, text: str) -> dict:
        state = self._base_state(text)
        state["status"] = "正在翻译" if self.settings.model else "未配置"
        return state

    def _error_state(self, text: str, message: str) -> dict:
        state = self._base_state(text)
        state["status"] = message
        return state

    def _on_ui(self, window, action) -> None:
        """WebView2 rejects controller calls from the hotkey or tray thread."""
        native = getattr(window, "native", None)
        if window is None or native is None:
            _boot("ui-skip")
            log_error("ui skip: window native missing")
            return

        def run() -> None:
            try:
                action()
            except Exception:
                log_error(traceback.format_exc())
            finally:
                _drop_delegate(getattr(run, "callback", None))

        try:
            from System import Func, Type

            callback = Func[Type](run)
            run.callback = callback
            _keep_delegate(callback)
            if native.InvokeRequired:
                native.BeginInvoke(callback)
            else:
                callback()
        except Exception:
            log_error(traceback.format_exc())

    def _webview_control(self, window):
        native = getattr(window, "native", None)
        if native is None:
            return None
        control = getattr(native, "webview", None)
        if control is not None:
            return control
        browser = getattr(native, "browser", None)
        if browser is None:
            return None
        return getattr(browser, "webview", None)

    def _run_js(self, window, script: str, kind: str) -> None:
        """Queue script on the UI thread and return without waiting."""

        def apply() -> None:
            control = self._webview_control(window)
            if control is None:
                log_error(f"js skipped: {kind} webview missing")
                return
            control.ExecuteScriptAsync(script)

        _boot(f"js-queued {kind}")
        self._on_ui(window, apply)

    def _observe_script(self, kind: str, task) -> None:
        try:
            from System import Action
            from System.Threading.Tasks import Task
        except Exception:
            log_error(traceback.format_exc())
            return

        def done(completed) -> None:
            try:
                if completed.IsFaulted:
                    log_error(f"js-fault {kind}\n{completed.Exception}")
                    return
                _boot(f"js-result {kind} {completed.Result}")
            except Exception:
                log_error(traceback.format_exc())
            finally:
                _drop_delegate(getattr(done, "callback", None))

        try:
            callback = Action[Task](done)
            done.callback = callback
            _keep_delegate(callback)
            task.ContinueWith(callback)
        except Exception:
            log_error(traceback.format_exc())

    def _reset_tooltip(self, window) -> None:
        # Hiding a native WebView does not reliably dispatch DOM blur or
        # visibilitychange. Reset before focus can be restored on reopening.
        control = self._webview_control(window)
        if control is not None:
            control.ExecuteScriptAsync("if(window.intextControls){window.intextControls.resetTooltip();}")

    def _show_native(self, window) -> None:
        native = getattr(window, "native", None)
        if native is None:
            _boot("show missing native")
            return
        _boot("show-native")
        try:
            native.Opacity = 1
        except Exception:
            pass
        self._reset_tooltip(window)
        self._sync_taskbar(window, window is self._settings_window)
        try:
            native.TopMost = window is not self._settings_window
        except Exception:
            pass
        native.Show()
        try:
            native.Activate()
        except Exception:
            pass
        try:
            hwnd = int(native.Handle.ToInt64())
            if window is self._popup:
                self._popup_hwnd = hwnd
                self._popup_shown_at = time.monotonic()
                self._arm_popup_blur(native)
            elif window is self._shot_window:
                self._shot_hwnd = hwnd
            from .platform_win import foreground

            foreground(hwnd)
            _boot(f"foreground {hwnd}")
        except Exception:
            log_error(traceback.format_exc())
            _boot("foreground-failed")

    def _hide_native(self, window) -> None:
        native = getattr(window, "native", None)
        if native is None:
            return
        self._reset_tooltip(window)
        if window is self._settings_window:
            self._hide_settings_frame(native)
        native.Hide()
        if window is self._settings_window:
            self._hide_settings_frame(native)

    def _hide_settings_frame(self, native) -> None:
        try:
            from .smooth_frame import hide_smooth_frame

            hide_smooth_frame(int(native.Handle.ToInt64()))
        except Exception:
            log_error(traceback.format_exc())

    def _push(self, state: dict, *, enter: bool, reveal: bool = True) -> None:
        if state.get("seq", self._gen) != self._gen:
            return
        state["pinned"] = self._pinned
        state["enter"] = enter
        self._popup_state = dict(state)
        if reveal:
            self._popup_requested = True
        window = self._popup
        if window is None:
            _boot("popup-missing")
            log_error("popup missing")
            return

        token = self._show_epoch

        def apply() -> None:
            # A shot overlay is up, or this push was queued before a cancel.
            if (self._hold_show or token != self._show_epoch
                    or not self._popup_requested or state.get("seq") != self._gen):
                return
            native = getattr(window, "native", None)
            if reveal and (enter or not getattr(native, "Visible", False)):
                window._intext_keep_hidden = False
                try:
                    self._place(window)
                except Exception:
                    log_error(traceback.format_exc())
                    _boot("place-failed")
                try:
                    self._show_native(window)
                except Exception:
                    log_error(traceback.format_exc())
                    _boot("show-failed")
            control = self._webview_control(window)
            if control is None:
                log_error("js skipped: popup webview missing")
                _boot("popup-webview-missing")
                return
            script = _apply_script("window.intext.apply", state, "popup")
            control.ExecuteScriptAsync(script)

        _boot("js-queued popup")
        self._on_ui(window, apply)

    def _place(self, window, x: int | None = None, y: int | None = None) -> None:
        from .platform_win import clamp_window, cursor_pos

        if x is None or y is None:
            x, y = cursor_pos()
        scale = 1.0
        native = getattr(window, "native", None)
        if native is not None:
            try:
                scale = float(native._scale) or 1.0
            except Exception:
                scale = 1.0
        width = int(POPUP_SIZE[0] * scale)
        height = int(POPUP_SIZE[1] * scale)
        x, y = clamp_window(x + int(12 * scale), y + int(16 * scale), width, height)
        moved = getattr(window, "native", None)
        hwnd = 0
        if moved is not None:
            try:
                hwnd = int(moved.Handle.ToInt64())
            except Exception:
                hwnd = 0
        if hwnd:
            from .platform_win import move_window

            move_window(hwnd, x, y)
            return
        logical_x = int(x / scale)
        logical_y = int(y / scale)
        window.move(logical_x, logical_y)

    def hide(self) -> None:
        self._popup_requested = False
        self._show_epoch += 1
        window = self._popup
        if window is None:
            return
        window._intext_keep_hidden = True

        def apply() -> None:
            self._sync_taskbar(window, False)
            self._hide_native(window)

        self._on_ui(window, apply)

    def hide_settings(self) -> None:
        window = self._settings_window
        if window is not None:
            window._intext_keep_hidden = True
        if window is None or self._quitting:
            return

        def apply() -> None:
            self._sync_taskbar(window, False)
            self._hide_native(window)

        self._on_ui(window, apply)

    def retry(self) -> None:
        if self._last_shot is not None:
            settings = deepcopy(self.settings)
            settings.shot_input = self._shot_context.shot_input
            settings.shot_display = self._shot_context.shot_display
            self._shot_context = settings
            self._gen += 1
            self._start_shot(self._gen, settings, use_cache=False)
            return
        if not self._last_text:
            return
        self._gen += 1
        gen = self._gen
        self._push(self._pending_state(self._last_text), enter=False)
        threading.Thread(
            target=self._finish,
            args=(self._last_text, gen),
            kwargs={"use_cache": False},
            daemon=True,
        ).start()

    def open_input(self) -> None:
        self._last_shot = None
        self.hide_shot()
        self._gen += 1
        self._last_text = ""
        state = self._base_state("")
        # The page retains its manual draft while hidden or showing results.
        state.update(mode="input", status="输入翻译")
        self._push(state, enter=not self._pinned)

    def submit_text(self, text: str) -> None:
        if isinstance(text, str) and text.strip():
            self._capture(lambda: text.strip())

    def set_languages(self, payload: dict) -> None:
        from .translate import LABELS

        if not isinstance(payload, dict):
            return
        source, target = payload.get("source"), payload.get("target")
        if source not in LABELS or target not in LABELS or target == "auto":
            return
        with self._settings_lock:
            self.settings.source, self.settings.target = source, target
            save_settings(self.settings)
        self._sync_languages()
        if (self._popup_state or {}).get("mode") == "input":
            state = self._base_state("")
            state.update(mode="input", status="输入翻译")
            self._push(state, enter=False)
        elif self._last_shot is not None:
            self.retry()
        elif self._last_text:
            self._gen += 1
            gen = self._gen
            self._push(self._pending_state(self._last_text), enter=False)
            threading.Thread(target=self._finish, args=(self._last_text, gen), daemon=True).start()

    def _sync_languages(self) -> None:
        if self._settings_window is not None:
            self._run_js(
                self._settings_window,
                _apply_script("window.intextSettings.languages", {
                    "source": self.settings.source, "target": self.settings.target,
                }, "languages"),
                "languages",
            )

    def copy_text(self, text: str, *, report_failure: bool = True) -> bool:
        from .platform_win import set_clipboard_text

        if not (text or "").strip():
            return False
        ok = False
        try:
            ok = bool(set_clipboard_text(text or ""))
        except Exception:
            log_error(traceback.format_exc())
        if ok:
            return True
        if not report_failure:
            return False
        state = dict(self._popup_state or self._base_state(self._last_text))
        state["status"] = "复制失败"
        self._push(state, enter=False, reveal=False)
        return False

    def set_pinned(self, pinned: bool) -> None:
        self._pinned = bool(pinned)
        with self._settings_lock:
            self.settings.pinned = self._pinned
            try:
                save_settings(self.settings)
            except Exception:
                log_error(traceback.format_exc())

    def dismiss_popup_if_outside(self, x: int, y: int) -> None:
        self.dismiss_tray_if_outside(x, y)
        if self._pinned or self._quitting or self._hold_show or self._preview:
            return
        if time.monotonic() - getattr(self, "_popup_shown_at", 0) < 0.2:
            return
        window = self._popup
        native = getattr(window, "native", None) if window is not None else None
        if native is not None and getattr(native, "_intext_dragging", False):
            return
        hwnd = self._popup_hwnd_now()
        if not hwnd:
            return
        from .geometry import should_dismiss_popup
        from .platform_win import window_rect, window_visible

        if not window_visible(hwnd):
            return
        if should_dismiss_popup((int(x), int(y)), window_rect(hwnd), pinned=False, visible=True):
            self.hide()

    def _arm_popup_blur(self, native) -> None:
        """Close on focus loss, the same idea pot-desktop uses for close-on-blur.

        A click in another window does not reach this page, so the page cannot
        see it. Losing activation is the signal. The short delay lets a focus
        bounce or a drag cancel the close. Pin still keeps the window.
        """
        if getattr(native, "_intext_blur", False):
            return
        native._intext_blur = True

        def close_if_idle() -> None:
            if self._pinned or self._quitting or self._hold_show or self._preview:
                return
            if time.monotonic() - getattr(self, "_popup_shown_at", 0) < 0.2:
                return
            if getattr(native, "_intext_dragging", False):
                return
            try:
                if native.ContainsFocus or native.Focused:
                    return
            except Exception:
                pass
            self.hide()

        def on_deactivate(_sender, _args) -> None:
            if self._pinned or getattr(native, "_intext_dragging", False):
                return
            from System.Windows.Forms import Timer

            previous = getattr(native, "_intext_blur_timer", None)
            if previous is not None:
                try:
                    previous.Stop()
                    previous.Dispose()
                except Exception:
                    pass
            timer = Timer()
            timer.Interval = 80

            def tick(_s, _a) -> None:
                try:
                    timer.Stop()
                    timer.Dispose()
                except Exception:
                    pass
                native._intext_blur_timer = None
                close_if_idle()

            timer.Tick += tick
            native._intext_blur_timer = timer
            native._intext_blur_tick = tick
            timer.Start()

        native.Deactivate += on_deactivate
        native._intext_on_deactivate = on_deactivate

    def swap(self, source: str | None = None) -> None:
        from .translate import swapped_languages

        previous = self._popup_state or {}
        result = previous.get("result", "")
        if not result:
            return
        source = source or previous.get("sourceLang")
        # Auto detects language inside the translation service, which doesn't
        # return a language code. Ask the user instead of guessing English.
        from .translate import LABELS

        if source not in LABELS or source == "auto":
            return
        with self._settings_lock:
            settings = self.settings
            settings.source, settings.target = swapped_languages(
                source,
                previous.get("resultLang") or settings.target,
            )
            save_settings(settings)
        self._sync_languages()
        self._last_shot = None
        self._last_text = result
        self._gen += 1
        gen = self._gen
        self._push(self._pending_state(self._last_text), enter=False)
        threading.Thread(target=self._finish, args=(self._last_text, gen), daemon=True).start()

    def save_settings(self, payload: dict) -> dict | None:
        if not isinstance(payload, dict):
            return
        with self._settings_lock:
            self.settings.model = str(payload.get("model") or "").strip()
            self.settings.endpoint = str(payload.get("endpoint", self.settings.endpoint) or "").strip()
            self.settings.api_key = str(payload.get("apiKey") or payload.get("api_key") or "").strip()
            self.settings.source = str(payload.get("source") or "auto")
            self.settings.target = str(payload.get("target") or "zh")
            self.settings.shot_input = "image" if payload.get("shotInput", payload.get("shot_input", self.settings.shot_input)) == "image" else "ocr"
            self.settings.shot_display = "overlay" if payload.get("shotDisplay", payload.get("shot_display", self.settings.shot_display)) == "overlay" else "popup"
            incoming = payload.get("fields") or {}
            if isinstance(incoming, dict):
                from .fields import normalize_field_state

                self.settings.fields = normalize_field_state(incoming)
            hotkeys = self._take_hotkeys(payload)
            save_settings(self.settings)
        return hotkeys

    def _commit_settings(self) -> None:
        with self._settings_lock:
            save_settings(self.settings)

    def remember_settings_window(self, width: int, height: int) -> None:
        width = int(width)
        height = int(height)
        if width < 280 or height < 280:
            return
        with self._settings_lock:
            if self.settings.window_width == width and self.settings.window_height == height:
                return
            self.settings.window_width = width
            self.settings.window_height = height
            save_settings(self.settings)
        _boot(f"resize-end {width}x{height}")

    def begin_drag(self, window) -> None:
        if window is None:
            return

        def apply() -> None:
            native = getattr(window, "native", None)
            if native is None:
                return
            from .platform_win import begin_form_drag

            begin_form_drag(native)

        self._on_ui(window, apply)

    def begin_settings_resize(self, edge: str) -> None:
        window = self._settings_window
        if window is None:
            return
        self._resize_token += 1
        token = self._resize_token
        _boot(f"resize-begin {edge}")

        def apply() -> None:
            if token != self._resize_token:
                return
            native = getattr(window, "native", None)
            if native is None:
                return
            from .platform_win import begin_form_resize

            begin_form_resize(native, str(edge or ""), on_finished=self.remember_settings_window)

        self._on_ui(window, apply)

    def end_settings_resize(self) -> None:
        window = self._settings_window
        self._resize_token += 1
        if window is None:
            return

        def apply() -> None:
            native = getattr(window, "native", None)
            if native is None:
                return
            from .platform_win import end_form_resize

            end_form_resize(native)

        self._on_ui(window, apply)


    def _read_selection(self) -> str | None:
        from .platform_win import read_selected_text

        return read_selected_text()

    def _read_shot(self) -> str | None:
        from .capture_win import read_screen_text

        return read_screen_text()

    def _hotkey_status(self, hotkey_error: str | None = None, shot_error: str | None = None) -> dict:
        from .shell_win import current_shell

        shell = current_shell()
        errors = shell.errors() if shell is not None else {"hotkeyError": "", "shotHotkeyError": ""}
        if hotkey_error is not None:
            errors["hotkeyError"] = hotkey_error
        if shot_error is not None:
            errors["shotHotkeyError"] = shot_error
        return {
            "hotkey": self.settings.hotkey,
            "shotHotkey": self.settings.shot_hotkey,
            "shotInput": self.settings.shot_input,
            "shotDisplay": self.settings.shot_display,
            "hotkeyError": errors.get("hotkeyError", ""),
            "shotHotkeyError": errors.get("shotHotkeyError", ""),
        }

    def _take_hotkeys(self, payload: dict) -> dict:
        from .hotkey import resolve_hotkey_change
        from .shell_win import current_shell

        hotkey, shot, select_error, shot_error = resolve_hotkey_change(
            self.settings.hotkey,
            self.settings.shot_hotkey,
            str(payload.get("hotkey") or self.settings.hotkey),
            str(payload.get("shotHotkey") or payload.get("shot_hotkey") or self.settings.shot_hotkey),
        )
        if select_error or shot_error:
            return self._hotkey_status(select_error, shot_error)
        if hotkey == self.settings.hotkey and shot == self.settings.shot_hotkey:
            return self._hotkey_status()
        self.settings.hotkey = hotkey
        self.settings.shot_hotkey = shot
        shell = current_shell()
        if shell is None:
            return self._hotkey_status("", "")
        failed = shell.update_hotkeys(hotkey, shot)
        return self._hotkey_status(failed.get("hotkeyError", ""), failed.get("shotHotkeyError", ""))

    def settings_payload(self) -> dict:
        return {
            "endpoint": self.settings.endpoint,
            "apiKey": self.settings.api_key,
            "model": self.settings.model,
            "source": self.settings.source,
            "target": self.settings.target,
            "hotkey": self.settings.hotkey,
            "shotHotkey": self.settings.shot_hotkey,
            "fields": self.settings.fields,
            **self._hotkey_status(),
        }

    def note_hotkeys(self, state: dict) -> None:
        window = self._settings_window
        if window is None or not isinstance(state, dict):
            return
        self._run_js(
            window,
            _apply_script("window.intextSettings.hotkeys", state, "hotkeys"),
            "hotkeys",
        )

    def open_settings(self) -> None:
        self.hide_tray_menu()
        window = self._settings_window
        if window is not None:
            window._intext_keep_hidden = False
        if window is None:
            return
        payload = self.settings_payload()

        def apply() -> None:
            self._show_native(window)
            self._sync_taskbar(window, True)
            self._shape_settings()
            control = self._webview_control(window)
            if control is None:
                log_error("js skipped: settings webview missing")
                window._intext_keep_hidden = True
                self._sync_taskbar(window, False)
                self._hide_native(window)
                return
            script = _apply_script("window.intextSettings.apply", payload, "settings")
            control.ExecuteScriptAsync(script)

        _boot("js-queued settings")
        self._on_ui(window, apply)

    def mark_ready(self, kind: str = "") -> None:
        _boot(f"ui-ready {kind or 'window'}")

    def tray_payload(self) -> dict:
        from .startup import is_enabled

        try:
            return {"startup": is_enabled()}
        except OSError:
            log_error(traceback.format_exc())
            return {"startup": False, "error": "无法读取开机启动设置"}

    def open_tray_menu(self, x: int, y: int) -> None:
        window = self._tray_menu
        if window is None:
            return
        if not self._tray_ready:
            self._tray_pending = (x, y)
            return
        self._tray_generation += 1
        generation = self._tray_generation
        payload = self.tray_payload()

        def apply() -> None:
            from System import Action
            from System.Threading.Tasks import Task
            from .geometry import tray_menu_position
            from .platform_win import work_area_at

            if generation != self._tray_generation or self._quitting:
                return
            native = window.native
            # The 160px host leaves 21 logical px below the visible menu.
            # Match the Windows tray overflow's measured 20 physical px gap.
            scale = float(native._scale) or 1.0
            left, top = tray_menu_position(
                (x, y), (int(native.Width), int(native.Height)), work_area_at(x, y),
                bottom_outset=round(21 * scale - 20),
            )
            native.SetDesktopLocation(left, top)
            control = self._webview_control(window)
            if control is None:
                return
            payload["openSide"] = "right" if left >= x else "left"
            window._intext_keep_hidden = False
            task = control.ExecuteScriptAsync(_apply_script("window.intextTray.open", payload, "tray"))

            def prepared(completed) -> None:
                try:
                    if completed.IsFaulted:
                        log_error(f"tray animation preparation failed: {completed.Exception}")
                        return

                    def reveal() -> None:
                        if generation == self._tray_generation and not self._quitting and not window._intext_keep_hidden:
                            self._show_native(window)

                    self._on_ui(window, reveal)
                finally:
                    _drop_delegate(getattr(prepared, "callback", None))

            # Prepare the transparent first frame before showing the host.
            # The page begins its compositor animation on the next visible RAF.
            callback = Action[Task](prepared)
            prepared.callback = callback
            _keep_delegate(callback)
            task.ContinueWith(callback)

        self._on_ui(window, apply)

    def hide_tray_menu(self) -> None:
        self._tray_pending = None
        self._tray_generation += 1
        generation = self._tray_generation
        window = self._tray_menu
        if window is None or self._quitting:
            return
        window._intext_keep_hidden = True

        def hide() -> None:
            if generation != self._tray_generation:
                return
            control = self._webview_control(window)
            if control is not None:
                control.ExecuteScriptAsync("if(window.intextTray){window.intextTray.close();}")
            self._hide_native(window)

        self._on_ui(window, hide)

    def dismiss_tray_if_outside(self, x: int, y: int) -> None:
        window = self._tray_menu
        if window is None:
            return
        visible = bool(getattr(getattr(window, "native", None), "Visible", False))
        requested = not getattr(window, "_intext_keep_hidden", True)
        if not visible and not requested:
            return
        from .geometry import should_dismiss_popup
        from .platform_win import window_rect

        hwnd = int(window.native.Handle.ToInt64())
        if should_dismiss_popup((x, y), window_rect(hwnd), pinned=False, visible=True):
            self.hide_tray_menu()

    def tray_action(self, action: str) -> dict | None:
        if action == "startup":
            from .startup import is_enabled, set_enabled

            try:
                enabled = set_enabled(not is_enabled())
            except OSError:
                log_error(traceback.format_exc())
                payload = self.tray_payload()
                payload["error"] = "无法更改开机启动设置，请重试"
                return payload
            self.hide_tray_menu()
            return {"startup": enabled}
        if action == "input":
            self.hide_tray_menu()
            self.open_input()
        elif action == "quit":
            self.hide_tray_menu()
            self.request_quit()
        return None

    def request_quit(self) -> None:
        window = self._tray_menu
        if window is None:
            self.quit()
            return

        def schedule() -> None:
            from System.Windows.Forms import Timer

            if self._quit_timer is not None or self._quitting:
                return
            # Let the WebView API reply finish before disposing its window.
            timer = Timer()
            timer.Interval = 150

            def tick(*_) -> None:
                timer.Stop()
                timer.Tick -= tick
                timer.Dispose()
                self._quit_timer = None
                self.quit()

            timer.Tick += tick
            self._quit_timer = timer
            timer.Start()

        self._on_ui(window, schedule)

    def refresh_icons(self) -> None:
        path = str(self.icon_path())

        def apply(window) -> None:
            from System.Drawing import Icon

            native = getattr(window, "native", None)
            if native is not None:
                native.Icon = Icon(path)

        for window in (self._popup, self._settings_window, self._tray_menu, self._shot_window):
            self._on_ui(window, lambda window=window: apply(window))

    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        if sys.platform == "win32":
            from .shell_win import current_shell

            shell = current_shell()
            if shell is not None:
                shell.stop()
        # Close auxiliary views before the master view ends the UI loop.
        for window in (self._shot_window, self._tray_menu, self._settings_window, self._popup):
            if window is None:
                continue

            def apply(window=window) -> None:
                window.destroy()

            self._on_ui(window, apply)

    def preview(self) -> None:
        self._push(
            self._result_state(
                "Please leave this model's request body unchanged.",
                "请保持这个模型的请求体原样。",
                True,
            ),
            enter=True,
        )
        if self._popup is not None and not self.settings.model:
            self._run_js(
                self._popup,
                "document.getElementById('model').textContent = 'gpt 6.1 sol'",
                "preview-model",
            )

    def _sync_taskbar(self, window, visible: bool) -> None:
        native = getattr(window, "native", None)
        if native is None:
            return
        try:
            hwnd = int(native.Handle.ToInt64())
        except Exception:
            return
        from .platform_win import set_taskbar_button

        # The translation overlay is a transient tool window, including when
        # pinned. Only settings can own a taskbar entry.
        set_taskbar_button(hwnd, bool(visible and window is self._settings_window))

    def _shape_settings(self) -> None:
        window = self._settings_window
        if window is None:
            return

        def apply() -> None:
            from .platform_win import apps_use_light_theme, smooth_window_corners

            visible = not bool(getattr(window, "_intext_keep_hidden", False))
            self._sync_taskbar(window, visible)
            native = getattr(window, "native", None)
            if native is None:
                return
            smooth_window_corners(int(native.Handle.ToInt64()), apps_use_light_theme())

        self._on_ui(window, apply)

    def _prepare_popup(self) -> None:
        window = self._popup
        if window is None:
            return

        def apply() -> None:
            native = getattr(window, "native", None)
            if native is None:
                _boot("prepare missing native")
                return
            self._prepare_tool_window(window, POPUP_SIZE)
            try:
                self._popup_hwnd = int(native.Handle.ToInt64())
                _boot(f"popup-hwnd {self._popup_hwnd}")
            except Exception:
                log_error(traceback.format_exc())
            # ShowInTaskbar recreates the handle and drops the WebView, which
            # makes a later hotkey show an invisible window.
            try:
                if self._popup_hwnd:
                    from .platform_win import set_taskbar_button

                    set_taskbar_button(self._popup_hwnd, False)
            except Exception:
                log_error(traceback.format_exc())
            if not self._preview and not self._popup_requested:
                native.Hide()

        self._on_ui(window, apply)

    def _prepare_tool_window(self, window, size: tuple[int, int]) -> None:
        from System.Drawing import Color, Size
        from .platform_win import enable_window_transparency

        native = window.native
        # Transparent WebView pixels expose the WinForms backing surface.
        # A black backing plus the full DWM frame lets those pixels composite
        # with the desktop, including antialiased corners and soft shadows.
        native.BackColor = Color.Black
        native.webview.DefaultBackgroundColor = Color.Transparent
        enable_window_transparency(int(native.Handle.ToInt64()))
        # Removing the initial native border can retain a smaller client area.
        scale = float(native._scale) or 1.0
        native.ClientSize = Size(round(size[0] * scale), round(size[1] * scale))


def run_gui(preview: bool = False, settings_only: bool = False, silent: bool = False) -> None:
    from .platform_win import enable_dpi_awareness, set_app_id

    _boot("build js-async")
    enable_dpi_awareness()
    set_app_id()
    import webview

    _install_exception_log()
    _patch_evaluate_js()
    _patch_transparent_show()

    app = App()
    app._preview = preview
    app._settings_only = settings_only
    assets = asset_dir()

    class PopupApi:
        def hide(self):
            app.hide()

        def open_settings(self):
            app.open_settings()

        def begin_drag(self):
            app.begin_drag(app._popup)

        def retry(self):
            app.retry()

        def copy_text(self, text):
            return app.copy_text(text)

        def set_pinned(self, pinned):
            app.set_pinned(pinned)

        def swap(self, source=None):
            app.swap(source)

        def set_languages(self, payload):
            app.set_languages(payload)

        def submit_text(self, text):
            app.submit_text(text)

        def mark_ready(self, kind):
            app.mark_ready(kind)

    class SettingsApi:
        def save(self, payload):
            return app.save_settings(payload)

        def hide(self):
            app.hide_settings()

        def mark_ready(self, kind):
            app.mark_ready(kind)

        def begin_drag(self):
            app.begin_drag(app._settings_window)

        def begin_resize(self, edge):
            app.begin_settings_resize(edge)

        def end_resize(self):
            app.end_settings_resize()

    class TrayApi:
        def activate(self, action):
            return app.tray_action(str(action))

        def hide(self):
            app.hide_tray_menu()

        def mark_ready(self, kind):
            app.mark_ready(kind)

    class ShotApi:
        def hide(self):
            app.hide_shot()

        def retry(self):
            app.retry()

        def copy_text(self, text):
            return app.copy_text(text, report_failure=False)

        def open_settings(self):
            app.open_settings()

        def begin_drag(self):
            app.begin_drag(app._shot_window)

        def begin_resize(self, edge):
            from .platform_win import begin_form_resize

            app._on_ui(app._shot_window, lambda: begin_form_resize(app._shot_window.native, str(edge), minimum=(320, 240)))

        def end_resize(self):
            from .platform_win import end_form_resize

            app._on_ui(app._shot_window, lambda: end_form_resize(app._shot_window.native))

        def mark_ready(self, kind=""):
            if app._shot_ready:
                return
            app._shot_ready = True

            def prepare():
                app._prepare_tool_window(app._shot_window, (640, 440))
                if app._shot_requested and app._shot_state:
                    app._push_shot(app._shot_state, reveal=True)

            app._on_ui(app._shot_window, prepare)

    icon = str(app.icon_path())
    app._popup = webview.create_window(
        "Intext",
        url=(assets / "popup.html").as_uri(),
        js_api=PopupApi(),
        width=POPUP_SIZE[0],
        height=POPUP_SIZE[1],
        frameless=True,
        transparent=True,
        on_top=True,
        easy_drag=False,
        shadow=False,
        hidden=not preview,
        background_color="#F7F4EF",
        text_select=True,
    )
    app._popup._intext_keep_hidden = not preview
    from .geometry import MINIMUM_SETTINGS, settings_size
    from .platform_win import logical_work_size

    settings_width, settings_height = settings_size(
        logical_work_size(),
        (app.settings.window_width, app.settings.window_height),
    )
    _boot(f"settings-size {settings_width}x{settings_height}")
    app._settings_window = webview.create_window(
        "Intext",
        url=(assets / "settings.html").as_uri(),
        js_api=SettingsApi(),
        width=settings_width,
        height=settings_height,
        min_size=MINIMUM_SETTINGS,
        resizable=True,
        frameless=True,
        easy_drag=False,
        hidden=not settings_only or silent,
        background_color="#F7F4EF" if _light_app() else "#1C1B19",
        text_select=True,
    )
    app._settings_window._intext_keep_hidden = not settings_visible_on_launch(
        model=app.settings.model, settings_only=settings_only, preview=preview, silent=silent,
    )
    app._tray_menu = webview.create_window(
        "Intext menu", url=(assets / "tray-menu.html").as_uri(), js_api=TrayApi(),
        width=TRAY_MENU_SIZE[0], height=TRAY_MENU_SIZE[1],
        frameless=True, transparent=True, on_top=True, easy_drag=False,
        shadow=False, resizable=False, hidden=True, background_color="#F7F4EF",
    )
    app._tray_menu._intext_keep_hidden = True
    app._shot_window = webview.create_window(
        "Intext screenshot", url=(assets / "shot-overlay.html").as_uri(), js_api=ShotApi(),
        width=640, height=440, min_size=(320, 240),
        frameless=True, transparent=True, shadow=False, on_top=True, easy_drag=False, resizable=True, hidden=True,
        background_color="#F7F4EF", text_select=True,
    )
    app._shot_window._intext_keep_hidden = True

    def keep_shot():
        if app._quitting:
            return True
        app.hide_shot()
        return False

    app._shot_window.events.closing += keep_shot

    def tray_loaded() -> None:
        def prepare() -> None:
            native = app._tray_menu.native
            app._prepare_tool_window(app._tray_menu, TRAY_MENU_SIZE)
            app._sync_taskbar(app._tray_menu, False)
            native.Deactivate += lambda *_: app.hide_tray_menu()
            app._tray_ready = True
            pending = app._tray_pending
            app._tray_pending = None
            if pending is not None:
                app.open_tray_menu(*pending)
        app._on_ui(app._tray_menu, prepare)

    app._tray_menu.events.loaded += tray_loaded
    for window in (app._popup, app._settings_window, app._tray_menu, app._shot_window):
        window.events.before_show += lambda *_, window=window: app._sync_taskbar(window, False)
    app._popup.events.loaded += _on_popup_loaded(app, preview)
    app._settings_window.events.shown += lambda *_: app._shape_settings()
    app._settings_window.events.loaded += _on_settings_loaded(app, settings_only, silent)
    app._settings_window.events.resized += lambda *_: app._shape_settings()

    def keep_popup():
        if app._quitting or preview:
            return True
        app.hide()
        return False

    def keep_settings():
        if app._quitting:
            return True
        app.hide_settings()
        return False

    app._popup.events.closing += keep_popup
    app._settings_window.events.closing += keep_settings

    def keep_tray():
        if app._quitting:
            return True
        app.hide_tray_menu()
        return False

    app._tray_menu.events.closing += keep_tray

    def start() -> None:
        _apply_icons(app, icon)
        if preview:
            return
        threading.Thread(target=_shell, args=(app,), daemon=True).start()

    webview.start(start, icon=icon)


def _on_popup_loaded(app: App, preview: bool):
    def loaded() -> None:
        app._prepare_popup()
        if preview:
            app.preview()

    return loaded


def _light_app() -> bool:
    from .platform_win import apps_use_light_theme

    return apps_use_light_theme()


def _on_settings_loaded(app: App, settings_only: bool, silent: bool = False):
    def loaded() -> None:
        # pywebview runs loaded handlers on a background thread.
        app._shape_settings()
        window = app._settings_window
        if window is None:
            return
        app._run_js(
            window,
            _apply_script("window.intextSettings.apply", app.settings_payload(), "settings"),
            "settings",
        )
        show = settings_visible_on_launch(model=app.settings.model, settings_only=settings_only, preview=app._preview, silent=silent)
        window._intext_keep_hidden = not show
        if show:
            app.open_settings()
        else:
            app.hide_settings()

    return loaded


def _apply_icons(app: App, icon: str) -> None:
    def apply(window) -> None:
        from System.Drawing import Icon

        native = getattr(window, "native", None)
        if native is not None:
            native.Icon = Icon(icon)

    for window in (app._popup, app._settings_window, app._tray_menu, app._shot_window):
        app._on_ui(window, lambda window=window: apply(window))


def _shell(app: App) -> None:
    from .hotkey import display_hotkey

    def dispatch() -> None:
        threading.Thread(target=app.on_hotkey, daemon=True).start()

    def dispatch_shot() -> None:
        threading.Thread(target=app.on_shot, daemon=True).start()

    try:
        from .shell_win import run_shell

        run_shell(
            hotkey=app.settings.hotkey,
            shot_hotkey=app.settings.shot_hotkey,
            tip=("Intext  " + display_hotkey(app.settings.hotkey))[:127],
            icon_path=lambda: str(app.icon_path(tray=True)),
            on_hotkey=dispatch,
            on_shot=dispatch_shot,
            on_open=app.open_settings,
            on_menu=app.open_tray_menu,
            on_quit=app.quit,
            on_theme=app.refresh_icons,
            on_hotkeys=app.note_hotkeys,
            on_outside_click=app.dismiss_popup_if_outside,
        )
    except Exception:
        log_error(traceback.format_exc())
