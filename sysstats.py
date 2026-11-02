"""
CPU, GPU and RAM load from Windows performance counters (the same numbers Task Manager shows).
Standard library only. GPU load is read from WDDM counters, so it works for NVIDIA, AMD and Intel
and doesn't wake a sleeping laptop GPU (unlike polling nvidia-smi).
"""
import ctypes
from ctypes import wintypes

pdh = ctypes.windll.pdh
kernel32 = ctypes.windll.kernel32
PDH_FMT_DOUBLE = 0x200
PDH_MORE_DATA = 0x800007D2


class _FmtValue(ctypes.Structure):
    _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]


class _FmtItem(ctypes.Structure):
    _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", _FmtValue)]


class _MemoryStatus(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


class SysStats:
    def __init__(self):
        self.query = wintypes.HANDLE()
        self.cpu = wintypes.HANDLE()
        self.gpu = wintypes.HANDLE()
        if pdh.PdhOpenQueryW(None, None, ctypes.byref(self.query)) != 0:
            raise OSError("PdhOpenQuery failed")
        # "Processor Utility" matches Task Manager (accounts for turbo); fall back to classic "% Processor Time"
        if pdh.PdhAddEnglishCounterW(self.query, r"\Processor Information(_Total)\% Processor Utility",
                                     None, ctypes.byref(self.cpu)) != 0:
            pdh.PdhAddEnglishCounterW(self.query, r"\Processor(_Total)\% Processor Time", None, ctypes.byref(self.cpu))
        self.has_gpu = pdh.PdhAddEnglishCounterW(
            self.query, r"\GPU Engine(*engtype_3D)\Utilization Percentage", None, ctypes.byref(self.gpu)) == 0
        pdh.PdhCollectQueryData(self.query)  # rates need two samples; the first read happens on the next call

    def _cpu(self):
        value = _FmtValue()
        if pdh.PdhGetFormattedCounterValue(self.cpu, PDH_FMT_DOUBLE, None, ctypes.byref(value)) != 0:
            return None
        return min(100.0, value.doubleValue)

    def _gpu(self):
        """Busiest GPU: sum the 3D engines per adapter (luid), take the max, like Task Manager."""
        if not self.has_gpu:
            return None
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        status = pdh.PdhGetFormattedCounterArrayW(self.gpu, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count), None)
        if status & 0xFFFFFFFF != PDH_MORE_DATA:
            return 0.0
        buf = (ctypes.c_byte * size.value)()
        if pdh.PdhGetFormattedCounterArrayW(self.gpu, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count), buf) != 0:
            return None
        items = ctypes.cast(buf, ctypes.POINTER(_FmtItem))
        per_adapter = {}
        for i in range(count.value):
            name = items[i].szName or ""
            luid = name.split("_phys")[0].split("luid_")[-1]
            per_adapter[luid] = per_adapter.get(luid, 0.0) + items[i].FmtValue.doubleValue
        return min(100.0, max(per_adapter.values(), default=0.0))

    @staticmethod
    def _ram():
        m = _MemoryStatus()
        m.dwLength = ctypes.sizeof(m)
        kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        used_gb = (m.ullTotalPhys - m.ullAvailPhys) / 1024 ** 3
        return m.dwMemoryLoad, round(used_gb, 1), round(m.ullTotalPhys / 1024 ** 3)

    def read(self):
        pdh.PdhCollectQueryData(self.query)
        ram, used, total = self._ram()
        cpu, gpu = self._cpu(), self._gpu()
        return {
            "cpu": None if cpu is None else round(cpu),
            "gpu": None if gpu is None else round(gpu),
            "ram": ram, "ram_used": used, "ram_total": total,
        }
