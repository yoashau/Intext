import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from intext.app import App
from intext.config import Settings, load_settings, save_settings
from intext.translate import Translation


class AppTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        env = patch.dict(os.environ, {"APPDATA": folder.name})
        env.start()
        self.addCleanup(env.stop)
        self.app = App(Settings(model="m", source="en", target="zh"))
        self.addCleanup(self.app.cache.disk.close)
        self.calls = []
        native = SimpleNamespace(Visible=True)
        self.app._popup = SimpleNamespace(native=native)
        self.app._on_ui = lambda window, callback: callback()
        self.app._webview_control = lambda window: SimpleNamespace(
            ExecuteScriptAsync=lambda script: self.calls.append("script")
        )
        self.app._show_native = lambda window: self.calls.append("show")
        self.app._hide_native = lambda window: self.calls.append("hide")
        self.app._sync_taskbar = lambda *_: None
        self.app._place = lambda *_: self.calls.append("move")

    def test_result_update_does_not_move_or_activate_popup(self):
        self.app._push(self.app._pending_state("hello"), enter=True)
        self.calls.clear()
        self.app._push(self.app._result_state("hello", "你好", False), enter=False, reveal=False)
        self.assertEqual(self.calls, ["script"])

    def test_startup_toggle_failure_preserves_menu_and_reports_actual_state(self):
        with patch('intext.startup.is_enabled', return_value=False), patch('intext.startup.set_enabled', side_effect=OSError('failed')), patch.object(self.app, 'hide_tray_menu') as hide:
            result = self.app.tray_action('startup')
        self.assertFalse(result['startup'])
        self.assertTrue(result['error'])
        hide.assert_not_called()

    def test_startup_toggle_success_closes_menu_after_confirmed_write(self):
        with patch('intext.startup.is_enabled', return_value=False), patch('intext.startup.set_enabled', return_value=True) as enable, patch.object(self.app, 'hide_tray_menu') as hide:
            result = self.app.tray_action('startup')
        enable.assert_called_once_with(True)
        hide.assert_called_once()
        self.assertTrue(result['startup'])

    def test_saved_pin_does_not_reopen_popup_during_startup(self):
        self.app._pinned = True
        native = self.app._popup.native
        native.Hide = Mock()
        with patch.object(self.app, '_prepare_tool_window'):
            self.app._prepare_popup()
            native.Hide.assert_called_once()
            native.Hide.reset_mock()
            self.app._popup_requested = True
            self.app._prepare_popup()
            native.Hide.assert_not_called()

    def test_tray_quit_allows_api_reply_before_disposing_windows(self):
        with patch.object(self.app, 'request_quit') as request, patch.object(self.app, 'quit') as quit_now:
            self.app.tray_action('quit')
        request.assert_called_once()
        quit_now.assert_not_called()

    def test_result_does_not_reopen_a_dismissed_popup(self):
        self.app._push(self.app._pending_state("hello"), enter=True)
        self.app.hide()
        self.calls.clear()
        self.app._push(self.app._result_state("hello", "你好", False), enter=False, reveal=False)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.app._popup_state["result"], "你好")

    def test_pinned_capture_preserves_position_and_explicit_hide_works(self):
        self.app._pinned = True
        self.app._push(self.app._pending_state("hello"), enter=False)
        self.assertEqual(self.calls, ["script"])
        self.app.hide()
        self.assertEqual(self.calls, ["script", "hide"])
        self.assertTrue(self.app._pinned)

    def test_queued_older_result_cannot_replace_newer_selection(self):
        queue = []
        self.app._on_ui = lambda window, callback: queue.append(callback)
        self.app._push(self.app._pending_state("old"), enter=True)
        self.app._gen += 1
        self.app._push(self.app._pending_state("new"), enter=True)
        queue[0]()
        self.assertEqual(self.calls, [])
        queue[1]()
        self.assertEqual(self.calls, ["move", "show", "script"])
        self.app._push({"seq": 0, "source": "old"}, enter=False)
        self.assertEqual(self.app._popup_state["source"], "new")

    def test_queued_show_is_cancelled_by_hide(self):
        queue = []
        self.app._on_ui = lambda window, callback: queue.append(callback)
        self.app._push(self.app._pending_state("hello"), enter=True)
        self.app.hide()
        queue[0]()
        self.assertEqual(self.calls, [])

    def test_finishing_request_keeps_its_original_language_and_model(self):
        def finish(text, **kwargs):
            self.app.settings.model = "new-model"
            self.app.settings.source = "ja"
            self.app.settings.target = "en"
            return Translation("你好", False, "m")

        self.app.translator = lambda: SimpleNamespace(
            source="en", target="zh", model="m", translate=finish
        )
        self.app._finish("hello", 0)
        self.assertEqual(self.app._popup_state["model"], "m")
        self.assertEqual(self.app._popup_state["resultLang"], "zh")
        self.assertEqual(self.app._popup_state["from"], "英语")

    def test_superseded_worker_does_not_start_a_request(self):
        self.app._gen = 2
        with patch.object(self.app, "translator") as translator:
            self.app._finish("old", 1)
        translator.assert_not_called()

    def test_swapping_translates_the_previous_result(self):
        self.app._last_text = "hello"
        self.app._popup_state = self.app._result_state("hello", "你好", False)
        with patch("intext.app.threading.Thread") as thread:
            self.app.swap()
        self.assertEqual(thread.call_args.kwargs["args"][0], "你好")
        self.assertEqual((self.app.settings.source, self.app.settings.target), ("zh", "en"))

    def test_failed_capture_cannot_retry_a_previous_selection(self):
        self.app._last_text = "previous selection"
        self.app._capture(lambda: "")
        self.assertEqual(self.app._last_text, "")
        with patch("intext.app.threading.Thread") as thread:
            self.app.retry()
        thread.assert_not_called()

    def test_unconfigured_hotkey_only_opens_the_translation_popup(self):
        self.app.settings.model = ""
        self.app._read_selection = lambda: "selected text"
        with patch.object(self.app, "open_settings") as settings:
            self.app.on_hotkey()
        settings.assert_not_called()
        self.assertEqual(self.app._popup_state["source"], "selected text")
        self.assertEqual(self.app._popup_state["status"], "未配置")
        self.assertEqual(self.calls, ["move", "show", "script"])

    def test_auto_language_swap_waits_for_a_language_and_uses_the_selected_one(self):
        self.app.settings.source = "auto"
        self.app._popup_state = self.app._result_state("こんにちは", "你好", False)
        with patch("intext.app.threading.Thread") as thread:
            self.app.swap()
            thread.assert_not_called()
            self.app.swap("ja")
        self.assertEqual((self.app.settings.source, self.app.settings.target), ("zh", "ja"))
        self.assertEqual(thread.call_args.kwargs["args"][0], "你好")

    def test_input_submission_uses_the_same_translation_path(self):
        self.app.open_input()
        self.assertEqual(self.app._popup_state["mode"], "input")
        self.assertTrue(self.app._popup_requested)
        self.assertEqual(self.app._last_text, "")
        with patch.object(self.app, "_capture") as capture:
            self.app.submit_text("  First paragraph.\n\nSecond paragraph.  ")
        self.assertEqual(capture.call_args.args[0](), "First paragraph.\n\nSecond paragraph.")

    def test_changing_input_language_preserves_the_draft(self):
        self.app.open_input()
        self.app.set_languages({"source": "auto", "target": "ja"})
        self.assertEqual(self.app._popup_state["mode"], "input")
        self.assertNotIn("draft", self.app._popup_state)
        self.assertEqual(self.app._popup_state["resultLang"], "ja")

    def test_changing_result_language_retranslates_the_original_text(self):
        self.app._last_text = "hello"
        with patch("intext.app.threading.Thread") as thread:
            self.app.set_languages({"source": "en", "target": "ja"})
        self.assertEqual(thread.call_args.kwargs["args"][0], "hello")
        self.assertEqual(self.app._popup_state["resultLang"], "ja")
        self.assertEqual(self.app.settings.target, "ja")

    def test_user_shortcuts_survive_restart(self):
        path = Path(os.environ["APPDATA"]) / "settings.json"
        for key in ("ctrl+alt+t", "ctrl+alt+m", "ctrl+alt+n"):
            save_settings(Settings(hotkey=key, shot_hotkey="ctrl+alt+x"), path)
            loaded = load_settings(path)
            self.assertEqual(loaded.hotkey, key)
            self.assertEqual(loaded.shot_hotkey, "ctrl+alt+x")

    def test_save_trims_pasted_connection_values_and_returns_hotkey_feedback(self):
        self.app._take_hotkeys = lambda _: {"hotkeyError": "无效"}
        feedback = self.app.save_settings({
            "model": " m ", "endpoint": " https://example.test/completions ", "apiKey": " secret "
        })
        self.assertEqual(feedback, {"hotkeyError": "无效"})
        self.assertEqual(self.app.settings.model, "m")
        self.assertEqual(self.app.settings.endpoint, "https://example.test/completions")
        self.assertEqual(self.app.settings.api_key, "secret")


if __name__ == "__main__":
    unittest.main()
