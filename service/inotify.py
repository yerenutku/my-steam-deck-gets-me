"""Tiny inotify wrapper (ctypes only, no packages): wait in the kernel until a file in a watched folder is
opened or changed. Waiting costs no CPU at all; Linux wakes the thread when something happens."""

import ctypes
import ctypes.util
import os
import select
import struct

IN_MODIFY, IN_CLOSE_WRITE, IN_OPEN, IN_MOVED_TO, IN_CREATE = 0x002, 0x008, 0x020, 0x080, 0x100
_IN_NONBLOCK, _IN_CLOEXEC = 0o4000, 0o2000000
_libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)


class Inotify:
    def __init__(self):
        self.fd = _libc.inotify_init1(_IN_NONBLOCK | _IN_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1 failed")
        self.folders = {}

    def watch(self, folder, mask):
        wd = _libc.inotify_add_watch(self.fd, os.fsencode(str(folder)), mask)
        if wd < 0:
            raise OSError(ctypes.get_errno(), f"inotify_add_watch failed: {folder}")
        self.folders[wd] = folder

    def read(self, timeout=None):
        """Wait up to `timeout` seconds (None = until something happens); returns [(folder, file name, mask)]."""
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            return []
        try:
            data = os.read(self.fd, 65536)
        except BlockingIOError:
            return []
        events, i = [], 0
        while i + 16 <= len(data):
            wd, mask, _cookie, size = struct.unpack_from("iIII", data, i)
            name = data[i + 16:i + 16 + size].split(b"\0", 1)[0].decode(errors="replace")
            events.append((self.folders.get(wd), name, mask))
            i += 16 + size
        return events

    def close(self):
        os.close(self.fd)
