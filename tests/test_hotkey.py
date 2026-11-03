from pathlib import Path
from intext.hotkey import canonical_hotkey, display_hotkey, registration_failure, resolve_hotkey_change


def test_canonical_orders_modifiers():
    assert canonical_hotkey("alt+ctrl+t") == "ctrl+alt+t"
    assert display_hotkey("ctrl+alt+x") == "Ctrl + Alt + X"


def test_duplicate_modifier_is_rejected():
    try:
        canonical_hotkey("ctrl+ctrl+a")
    except ValueError:
        return
    raise AssertionError("duplicate modifier should be rejected")


def test_canonical_rejects_plain_key():
    try:
        canonical_hotkey("t")
    except ValueError:
        return
    raise AssertionError("plain key should be rejected")


def test_registration_failure_names_the_windows_conflict():
    assert registration_failure(1409) == "已被占用"
    assert registration_failure(5) == "注册失败"


def test_invalid_hotkey_stays_on_the_previous_shortcut():
    select, shot, select_error, shot_error = resolve_hotkey_change(
        "ctrl+alt+q",
        "ctrl+alt+e",
        "q",
        "ctrl+alt+e",
    )
    assert (select, shot, select_error, shot_error) == ("ctrl+alt+q", "ctrl+alt+e", "无效", "")


def test_duplicate_hotkey_is_rejected_without_replacing_either():
    select, shot, select_error, shot_error = resolve_hotkey_change(
        "ctrl+alt+q",
        "ctrl+alt+e",
        "ctrl+alt+e",
        "ctrl+alt+e",
    )
    assert (select, shot, select_error, shot_error) == ("ctrl+alt+q", "ctrl+alt+e", "重复", "")


def test_invalid_side_cannot_collapse_into_the_other_shortcut():
    select, shot, select_error, shot_error = resolve_hotkey_change(
        "ctrl+alt+q",
        "ctrl+alt+e",
        "q",
        "ctrl+alt+q",
    )
    assert (select, shot, select_error, shot_error) == ("ctrl+alt+q", "ctrl+alt+e", "无效", "重复")


def test_settings_failure_stays_inside_the_existing_keycap():
    html = (Path(__file__).resolve().parents[1] / "src" / "intext" / "assets" / "settings.html").read_text(encoding="utf-8")
    assert "keycap-state" in html
    assert "hotkey-alert" not in html
    assert "alert(" not in html
    assert 'class="keycap" id="hotkey-select"' in html
    assert 'id="stash"' in html
    assert 'id="close"' not in html
    assert "box-sizing: border-box" in html
    assert "pop.style.width = rect.width" in html
