"""Read a Windows UI Automation text selection on a disposable MTA thread.

The client has explicit provider timeouts. The caller also imposes an overall
deadline, since a third-party provider is outside the application's control.
"""

from __future__ import annotations

import ctypes
import uuid
from ctypes import wintypes

from .translate import MAX_TEXT_CHARS


class GUID(ctypes.Structure):
    _fields_ = (("data1", ctypes.c_uint32), ("data2", ctypes.c_uint16),
                ("data3", ctypes.c_uint16), ("data4", ctypes.c_ubyte * 8))


def _guid(value: str) -> GUID:
    return GUID.from_buffer_copy(uuid.UUID(value).bytes_le)


_CLSID_AUTOMATION = _guid("e22ad333-b25f-460c-83d0-0581107395c9")
_IID_AUTOMATION2 = _guid("34723aff-0c9d-49d0-9896-7ab52df8cd8a")
_IID_TEXT_PATTERN = _guid("32eba289-3583-42c9-9c59-3b6d9a1e9b6a")
_TEXT_PATTERN_ID = 10014
_NOT_SUPPORTED = 0x80040204
_NO_INTERFACE = 0x80004002

ole32 = ctypes.WinDLL("ole32", use_last_error=True)
oleaut32 = ctypes.WinDLL("oleaut32", use_last_error=True)
ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
ole32.CoInitializeEx.restype = ctypes.c_int32
ole32.CoUninitialize.argtypes = []
ole32.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p, wintypes.DWORD,
                                   ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
ole32.CoCreateInstance.restype = ctypes.c_int32
oleaut32.SysStringLen.argtypes = [ctypes.c_void_p]
oleaut32.SysStringLen.restype = ctypes.c_uint
oleaut32.SysFreeString.argtypes = [ctypes.c_void_p]


def _method(obj, index: int, argtypes, *args) -> int:
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    call = ctypes.WINFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, *argtypes)(vtable[index])
    return call(obj, *args)


def _release(obj) -> None:
    if obj:
        vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])(obj)


def _success(code: int) -> bool:
    return code >= 0


def read_selection() -> tuple[str | None, bool]:
    """Return (text, handled); handled includes an empty or password selection."""
    initialized = ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED
    if not _success(initialized):
        return None, True
    automation = ctypes.c_void_p()
    element = ctypes.c_void_p()
    pattern = ctypes.c_void_p()
    ranges = ctypes.c_void_p()
    try:
        code = ole32.CoCreateInstance(ctypes.byref(_CLSID_AUTOMATION), None, 1,
                                      ctypes.byref(_IID_AUTOMATION2), ctypes.byref(automation))
        if not _success(code) or not automation:
            return None, True
        # IUIAutomation2 methods and their indices come from the Windows SDK
        # UIAutomationClient.h; all pointers stay on this MTA thread.
        for index in (61, 63):  # ConnectionTimeout, TransactionTimeout
            if not _success(_method(automation, index, [wintypes.DWORD], 600)):
                return None, True
        if not _success(_method(automation, 8, [ctypes.POINTER(ctypes.c_void_p)], ctypes.byref(element))) or not element:
            return None, True
        is_password = wintypes.BOOL()
        if not _success(_method(element, 35, [ctypes.POINTER(wintypes.BOOL)], ctypes.byref(is_password))):
            return None, True
        if is_password.value:
            return None, True
        code = _method(element, 14, [ctypes.c_int, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)],
                       _TEXT_PATTERN_ID, ctypes.byref(_IID_TEXT_PATTERN), ctypes.byref(pattern))
        if (code & 0xFFFFFFFF) in (_NOT_SUPPORTED, _NO_INTERFACE) or (_success(code) and not pattern):
            return None, False
        if not _success(code) or not pattern:
            return None, True
        if not _success(_method(pattern, 5, [ctypes.POINTER(ctypes.c_void_p)], ctypes.byref(ranges))):
            return None, True
        if not ranges:
            return None, False  # This control has no selectable text range.
        count = ctypes.c_int()
        if not _success(_method(ranges, 3, [ctypes.POINTER(ctypes.c_int)], ctypes.byref(count))):
            return None, True
        if count.value < 0 or count.value > 128:
            return None, True
        parts = []
        for index in range(count.value):
            item = ctypes.c_void_p()
            value = ctypes.c_void_p()
            try:
                if not _success(_method(ranges, 4, [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)], index, ctypes.byref(item))) or not item:
                    return None, True
                if not _success(_method(item, 12, [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)], MAX_TEXT_CHARS + 1, ctypes.byref(value))):
                    return None, True
                if value:
                    length = oleaut32.SysStringLen(value)
                    parts.append(ctypes.string_at(value, length * 2).decode("utf-16-le", "surrogatepass"))
                if sum(map(len, parts)) > MAX_TEXT_CHARS:
                    break
            finally:
                if value:
                    oleaut32.SysFreeString(value)
                _release(item)
        text = "\n".join(parts).strip()
        return text or None, True
    finally:
        for obj in (ranges, pattern, element, automation):
            _release(obj)
        ole32.CoUninitialize()
