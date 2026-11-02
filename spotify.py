"""
Control the Spotify desktop app locally: no Spotify account setup or Premium needed.
- Track, artist, cover, play state and controls: Windows media session API (the same data as the
  volume flyout), via the `winrt-*` packages.
- Fallbacks without them: track from the window title, controls via WM_APPCOMMAND (like media keys).
- Volume: Spotify's own volume in the Windows mixer via `pycaw` (falls back to system volume keys).
"""
import asyncio
import base64
import ctypes
import os
from ctypes import wintypes
from datetime import datetime, timezone

try:
    from pycaw.pycaw import AudioUtilities
    HAS_VOLUME = True
except ImportError:
    HAS_VOLUME = False

try:
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as _Manager
    from winrt.windows.storage.streams import Buffer, DataReader, InputStreamOptions
    HAS_MEDIA = True
except ImportError:
    HAS_MEDIA = False

PLAYING = 4  # GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

WM_APPCOMMAND = 0x0319
APPCOMMAND = {"next": 11, "previous": 12, "play_pause": 14}
VK = {"next": 0xB0, "previous": 0xB1, "play_pause": 0xB3, "vol_down": 0xAE, "vol_up": 0xAF}

_last_track = ""


def _process_name(pid):
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf, size = ctypes.create_unicode_buffer(260), wintypes.DWORD(260)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def find_window():
    """Return (hwnd, title) of the main Spotify window, or None."""
    found = []

    def callback(hwnd, _):
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if not cls.value.startswith("Chrome_WidgetWin"):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if _process_name(pid.value) == "spotify.exe":
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, length + 1)
            found.append((hwnd, title.value))
            return False
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return found[0] if found else None


def _press(vk):
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 2, 0)  # KEYEVENTF_KEYUP


async def _session():
    manager = await _Manager.request_async()
    for s in manager.get_sessions():
        if "spotify" in s.source_app_user_model_id.lower():
            return s
    return None


async def _media_info():
    s = await _session()
    if not s:
        return None
    props = await s.try_get_media_properties_async()
    info = s.get_playback_info()
    playing = info.playback_status == PLAYING
    # Windows only updates the position on events; add the time played since then
    t = s.get_timeline_properties()
    duration = t.end_time.total_seconds()
    position = t.position.total_seconds()
    if playing and t.last_updated_time:
        position += (datetime.now(timezone.utc) - t.last_updated_time).total_seconds()
    return {"title": props.title, "artist": props.artist, "playing": playing,
            "position": round(max(0.0, min(position, duration)), 1), "duration": round(duration, 1),
            "can_seek": bool(info.controls.is_playback_position_enabled) and duration > 0}


async def _seek(seconds):
    s = await _session()
    return bool(s and await s.try_change_playback_position_async(int(seconds * 10_000_000)))  # 100 ns units


def seek(seconds):
    """Jump to `seconds` in the current track."""
    if HAS_MEDIA:
        try:
            asyncio.run(_seek(max(0.0, float(seconds))))
        except Exception:
            pass


async def _cover():
    s = await _session()
    if not s:
        return None
    props = await s.try_get_media_properties_async()
    if not props.thumbnail:
        return None
    stream = await props.thumbnail.open_read_async()
    buf = Buffer(stream.size)
    await stream.read_async(buf, stream.size, InputStreamOptions.READ_AHEAD)
    data = bytearray(buf.length)
    DataReader.from_buffer(buf).read_bytes(data)
    return f"data:{stream.content_type or 'image/png'};base64,{base64.b64encode(bytes(data)).decode()}"


async def _media_command(method):
    s = await _session()
    return bool(s and await getattr(s, method)())


def cover_data_url():
    """Current track cover as a data: URL, or None."""
    if not HAS_MEDIA:
        return None
    try:
        return asyncio.run(_cover())
    except Exception:
        return None


def _command(name):
    method = {"play_pause": "try_toggle_play_pause_async", "next": "try_skip_next_async",
              "previous": "try_skip_previous_async"}[name]
    if HAS_MEDIA:
        try:
            if asyncio.run(_media_command(method)):
                return
        except Exception:
            pass
    win = find_window()
    if win:
        user32.PostMessageW(win[0], WM_APPCOMMAND, win[0], APPCOMMAND[name] << 16)
    else:
        _press(VK[name])  # global media key


def play_pause():
    _command("play_pause")


def next_track():
    _command("next")


def previous():
    _command("previous")


def _sessions():
    return [s for s in AudioUtilities.GetAllSessions()
            if s.Process and s.Process.name().lower() == "spotify.exe"]


def get_volume():
    """Spotify volume 0-100, or None if Spotify has no audio session yet."""
    if not HAS_VOLUME:
        return None
    sessions = _sessions()
    if not sessions:
        return None
    return round(sessions[0].SimpleAudioVolume.GetMasterVolume() * 100)


def set_volume(percent):
    for s in _sessions():
        s.SimpleAudioVolume.SetMasterVolume(max(0, min(100, percent)) / 100, None)


def volume_step(direction):
    """Fallback without pycaw: system volume keys."""
    _press(VK["vol_up"] if direction > 0 else VK["vol_down"])


def status():
    global _last_track
    win = find_window()
    if not win:
        return {"running": False}
    media = None
    if HAS_MEDIA:
        try:
            media = asyncio.run(_media_info())
        except Exception:
            media = None
    timeline = {}
    if media and media["title"]:
        title, artist, playing = media["title"], media["artist"], media["playing"]
        _last_track = f"{artist} — {title}" if artist else title
        timeline = {k: media[k] for k in ("position", "duration", "can_seek")}
    else:
        window_title = win[1]
        playing = " - " in window_title  # when paused the title is just "Spotify Premium"/"Spotify Free"
        if playing:
            _last_track = window_title.replace(" - ", " — ", 1)
        artist, _, title = _last_track.rpartition(" — ")
    return {"running": True, "playing": playing, "track": _last_track,
            "title": title, "artist": artist, "volume": get_volume(), **timeline}


def focus_or_launch():
    win = find_window()
    if win:
        user32.ShowWindow(win[0], 9)  # SW_RESTORE
        user32.SetForegroundWindow(win[0])
    else:
        os.startfile("spotify:")
