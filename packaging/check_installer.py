"""Verify embedded installer artwork and refresh the Explorer file icon.

pefile is provided by the PyInstaller build environment, not the app runtime.
"""
from __future__ import annotations

import ctypes
import hashlib
import struct
import sys
from pathlib import Path

import pefile


def icon_frames(path: Path) -> list[tuple[int, int, int, str]]:
    with pefile.PE(str(path)) as pe:
        resources = {entry.id: entry for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries}
        images = {}
        for entry in resources[3].directory.entries:
            item = entry.directory.entries[0].data.struct
            images[entry.id] = pe.get_data(item.OffsetToData, item.Size)
        group = resources[14].directory.entries[0].directory.entries[0].data.struct
        data = pe.get_data(group.OffsetToData, group.Size)
        count = struct.unpack_from('<H', data, 4)[0]
        frames = []
        for index in range(count):
            width, height, _, _, _, bits, _, ident = struct.unpack_from('<BBBBHHIH', data, 6 + 14 * index)
            frames.append((width or 256, height or 256, bits, hashlib.sha256(images[ident]).hexdigest()))
        return sorted(frames)


def main() -> None:
    app, installer = map(Path, sys.argv[1:])
    frames = icon_frames(app)
    if icon_frames(installer) != frames:
        raise SystemExit('Installer icon does not match the application')
    print(f'Installer and application icons match: {len(frames)} frames')
    if sys.platform == 'win32':
        notify = ctypes.windll.shell32.SHChangeNotify
        notify.argtypes = [ctypes.c_long, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        notify.restype = None
        # SHCNE_UPDATEITEM, SHCNF_PATHW | SHCNF_FLUSH.
        notify(0x2000, 0x1005, ctypes.c_wchar_p(str(installer.resolve())), None)
        print('Explorer notified of the updated installer icon')


if __name__ == '__main__':
    main()
