"""Current-user, opt-in startup using the application's silent entry point."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Intext"


def startup_command() -> str:
    executable = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        args = [str(executable), "--silent"]
    else:
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.is_file():
            executable = pythonw
        launch = Path(__file__).resolve().parents[2] / "packaging" / "launch.py"
        args = [str(executable), str(launch), "--silent"]
    return subprocess.list2cmdline(args)


def is_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, kind = winreg.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return False
    return kind == winreg.REG_SZ and value == startup_command()


def set_enabled(enabled: bool) -> bool:
    import winreg

    if enabled:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, startup_command())
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass
    actual = is_enabled()
    if actual != enabled:
        raise OSError("开机启动设置没有生效")
    return actual
