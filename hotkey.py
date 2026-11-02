"""Global Windows hotkey (works while the widget is hidden), standard library only."""
import ctypes
import threading
from ctypes import wintypes

user32 = ctypes.windll.user32
MODIFIERS = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4, "win": 0x8}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312


def parse(combo):
    """'ctrl+alt+n' -> (modifiers, virtual key code)."""
    *mods, key = [p.strip().lower() for p in combo.split("+")]
    if len(key) != 1 or not key.isalnum() or any(m not in MODIFIERS for m in mods):
        raise ValueError(f"непонятная комбинация: {combo}")
    flags = MOD_NOREPEAT
    for m in mods:
        flags |= MODIFIERS[m]
    return flags, ord(key.upper())


def register(combo, callback):
    """Register combo in a background thread; callback runs in that thread.
    Returns True if registered, False if the combo is taken by another program."""
    flags, vk = parse(combo)
    result = {}
    ready = threading.Event()

    def loop():
        # RegisterHotKey(NULL, ...) posts WM_HOTKEY to this thread's queue, so register and listen here
        result["ok"] = bool(user32.RegisterHotKey(None, 1, flags, vk))
        ready.set()
        if not result["ok"]:
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                callback()

    threading.Thread(target=loop, daemon=True).start()
    ready.wait(2)
    return result.get("ok", False)
