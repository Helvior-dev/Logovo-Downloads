import sys
import ctypes
from ctypes import wintypes
from typing import Optional


class WindowsTaskbar:
    TBPF_NOPROGRESS = 0x0
    TBPF_INDETERMINATE = 0x1
    TBPF_NORMAL = 0x2     # Green progress bar
    TBPF_ERROR = 0x4      # Red progress bar
    TBPF_PAUSED = 0x8     # Yellow progress bar

    def __init__(self):
        self._available = False
        self._p_taskbar = None
        self._SetProgressValue = None
        self._SetProgressState = None

        if sys.platform != 'win32':
            return

        try:
            class GUID(ctypes.Structure):
                _fields_ = [
                    ('Data1', wintypes.DWORD),
                    ('Data2', wintypes.WORD),
                    ('Data3', wintypes.WORD),
                    ('Data4', wintypes.BYTE * 8)
                ]

            ole32 = ctypes.windll.ole32
            ole32.CoInitialize(None)

            clsid = GUID()
            iid = GUID()
            ole32.CLSIDFromString(wintypes.LPCWSTR('{56FDF344-FD6D-11D0-958A-006097C9A090}'), ctypes.byref(clsid))
            ole32.CLSIDFromString(wintypes.LPCWSTR('{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}'), ctypes.byref(iid))

            p_taskbar = ctypes.c_void_p()
            hr = ole32.CoCreateInstance(
                ctypes.byref(clsid),
                None,
                1 | 4,
                ctypes.byref(iid),
                ctypes.byref(p_taskbar)
            )

            if hr == 0 and p_taskbar.value:
                self._p_taskbar = p_taskbar
                vtable = ctypes.cast(p_taskbar.value, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
                HrInit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtable[3])
                HrInit(p_taskbar)
                self._SetProgressValue = ctypes.WINFUNCTYPE(
                    ctypes.c_long, ctypes.c_void_p, wintypes.HWND, ctypes.c_uint64, ctypes.c_uint64
                )(vtable[9])
                self._SetProgressState = ctypes.WINFUNCTYPE(
                    ctypes.c_long, ctypes.c_void_p, wintypes.HWND, ctypes.c_int
                )(vtable[10])
                self._available = True
        except Exception:
            self._available = False

    def set_progress(self, hwnd: Optional[int], completed: int, total: int = 100):
        if not self._available or not hwnd or not self._p_taskbar:
            return
        try:
            if total > 0 and 0 <= completed < total:
                self._SetProgressState(self._p_taskbar, wintypes.HWND(int(hwnd)), self.TBPF_NORMAL)
                self._SetProgressValue(self._p_taskbar, wintypes.HWND(int(hwnd)), int(completed), int(total))
            elif completed >= total and total > 0:
                self._SetProgressState(self._p_taskbar, wintypes.HWND(int(hwnd)), self.TBPF_NOPROGRESS)
            else:
                self._SetProgressState(self._p_taskbar, wintypes.HWND(int(hwnd)), self.TBPF_NOPROGRESS)
        except Exception:
            pass

    def clear(self, hwnd: Optional[int]):
        if not self._available or not hwnd or not self._p_taskbar:
            return
        try:
            self._SetProgressState(self._p_taskbar, wintypes.HWND(int(hwnd)), self.TBPF_NOPROGRESS)
        except Exception:
            pass


taskbar_manager = WindowsTaskbar()
