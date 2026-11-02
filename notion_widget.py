"""
Notion desktop widget for Windows: HTML/CSS interface (pywebview + Edge WebView2).
Python side: data (Notion, Google Calendar), AI chat, Spotify, tray, hotkey, reminders.
Interface: ui/index.html, ui/style.css, ui/app.js.
"""
import copy
import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
import winreg
from ctypes import wintypes
from datetime import date, datetime, timedelta
from pathlib import Path

import webview

import claude_chat
import claude_usage
import gemini_chat
import hotkey
import quick_add
import spotify
import sysstats
import tray
from ical_feed import fetch_events
from notifier import toast
from notion_api import Notion

HERE = Path(__file__).parent
CONFIG_PATH = HERE / "config.json"
STATE_PATH = HERE / "state.json"  # window position and UI toggles, written by the widget
NOTIFIED_PATH = HERE / "notified.json"  # reminders already shown, so restarts don't repeat them
CLAUDE_LIMITS_PATH = HERE / "claude_limits.json"  # written by claude_statusline.py (Claude Code status line)
UI_PATH = HERE / "ui" / "index.html"
WIDTH = 340
SECRETS = ["token", "gemini.api_key", "claude.api_key"]  # never sent to the page
WEEKDAYS =["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]

user32 = ctypes.windll.user32
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]  # HWND_TOPMOST is -1: needs a pointer-sized type


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def windows_dark_mode():
    try:
        key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def get_path(cfg, dotted):
    for part in dotted.split("."):
        cfg = cfg.get(part) if isinstance(cfg, dict) else None
    return cfg


def set_path(cfg, dotted, value):
    *parents, last = dotted.split(".")
    for part in parents:
        cfg = cfg.setdefault(part, {})
    cfg[last] = value


def serialize(item):
    return {**item, "start": item["start"].isoformat(timespec="minutes")}


def demo_data():
    """Fake data so the widget renders without a Notion token."""
    now = datetime.now().replace(second=0, microsecond=0)
    today = now.replace(hour=0, minute=0)

    def task(i, title, start, has_time=True, done=False, tag=None):
        return {"id": f"demo{i}", "title": title, "start": start, "has_time": has_time, "done": done,
                "tags": [tag] if tag else [], "url": None, "source": "notion"}

    work, home, study = ("Работа", "blue"), ("Личное", "green"), ("Учёба", "orange")
    tasks = [
        task(1, "Созвон с командой", now + timedelta(minutes=45), tag=work),
        task(2, "Написать отчёт", today + timedelta(hours=23), tag=work),
        task(3, "Утренняя пробежка", today + timedelta(hours=7), done=True, tag=home),
        task(4, "Купить продукты", today, has_time=False, tag=home),
        task(5, "Лекция", today + timedelta(days=2, hours=10), tag=study),
        task(7, "Дедлайн проекта", today + timedelta(days=3, hours=18), tag=study),
    ]
    overdue = [task(8, "Сдать реферат", today - timedelta(days=2), has_time=False, tag=study)]
    events = [{"id": "g1", "title": "Встреча (Google)", "start": today + timedelta(hours=15),
               "has_time": True, "done": False, "tags": [], "url": None, "source": "gcal"}]
    return tasks, overdue, events


class Widget:
    """State and background work; the UI talks to it through Api."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.prefs = load_json(STATE_PATH)
        self.notion = Notion(cfg) if cfg.get("token") and cfg.get("database_id") else None
        provider = cfg.get("ai_provider", "claude")
        self.chat = gemini_chat.GeminiChat(cfg) if provider == "gemini" else claude_chat.ClaudeChat(cfg)
        self.tasks, self.overdue, self.events = [], [], []
        self.status = ""
        self.updated = ""
        self.view_month = date.today().replace(day=1)
        self.notified = self._load_notified()
        self.window = None
        self.ready = False  # UI loaded and listening
        self.visible = True
        self.tray = None
        self.hotkey = None
        self._fetch_lock = threading.Lock()
        self._move_timer = None

    # ------------------------------------------------------------ UI bridge
    def push(self, event, data):
        """Send an event to the page: app.on(event, data)."""
        if not (self.ready and self.window):
            return
        payload = json.dumps(data, ensure_ascii=False)
        try:
            self.window.evaluate_js(f"window.app && app.on({json.dumps(event)}, {payload})")
        except Exception:
            pass  # window closing

    def snapshot(self):
        return {
            "tasks": [serialize(t) for t in self.tasks],
            "overdue": [serialize(t) for t in self.overdue],
            "events": [serialize(e) for e in self.events],
            "status": self.status,
            "updated": self.updated,
            "view_month": self.view_month.isoformat(),
        }

    def settings(self):
        return {
            "prefs": self.prefs,
            "ai_name": self.chat.name,
            "spotify": self.cfg.get("spotify", True),
            "spotify_volume": spotify.HAS_VOLUME,
            "can_check": self.notion is None or self.notion.can_check,
            "demo": self.notion is None,
            "hotkey": self.hotkey,
            "stats": self.cfg.get("stats", True),
            "claude_limits": self.cfg.get("claude_limits", True),
        }

    def claude_limits(self):
        """5-hour and weekly Claude usage saved by the status line script, or None if there's no data yet."""
        data = load_json(CLAUDE_LIMITS_PATH)
        limits = data.get("rate_limits")
        if not limits:
            return None
        now = time.time()
        out = {"saved_at": data.get("saved_at")}
        for key in ("five_hour", "seven_day"):
            window = limits.get(key)
            if not window:
                continue
            resets_at = window.get("resets_at")
            # A window that already reset is back to 0%, even if Claude Code hasn't run since
            fresh = resets_at is None or resets_at > now
            out[key] = {"pct": round(window.get("used_percentage", 0)) if fresh else 0,
                        "resets_at": resets_at if fresh else None}
        return out

    def save_prefs(self):
        STATE_PATH.write_text(json.dumps(self.prefs, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------------------ data
    def refresh(self):
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        with self._fetch_lock:
            # Visible month plus the next week (for the "upcoming" block)
            today = date.today()
            start = min(self.view_month, today)
            end = max((self.view_month + timedelta(days=32)).replace(day=1), today + timedelta(days=8))
            errors = []

            if self.notion:
                try:
                    tasks, overdue = self.notion.query(start, end), self.notion.overdue()
                except Exception as e:  # network / auth / wrong property names
                    tasks, overdue = self.tasks, self.overdue
                    errors.append(f"Notion: {e}")
                events = []
            else:
                tasks, overdue, events = demo_data()
                errors.append("демо-режим: заполни config.json")

            if self.cfg.get("ical_urls"):
                try:
                    events = fetch_events(self.cfg["ical_urls"], start, end)
                except Exception as e:
                    events = self.events
                    errors.append(f"календарь: {e}")

            self.tasks, self.overdue, self.events = tasks, overdue, events
            self.status = "; ".join(errors)
            self.updated = datetime.now().strftime("%H:%M")
        self.push("data", self.snapshot())

    def chat_context(self):
        now, today = datetime.now(), date.today()

        def line(t):
            when = t["start"].strftime("%d.%m %H:%M" if t["has_time"] else "%d.%m, весь день")
            src = " [Google Календарь]" if t["source"] == "gcal" else ""
            return f"- {when} — {t['title']}{' (выполнено)' if t['done'] else ''}{src}"

        week = sorted((x for x in self.tasks + self.events if today <= x["start"].date() < today + timedelta(days=7)),
                      key=lambda x: x["start"])
        parts = [f"Сейчас: {WEEKDAYS[now.weekday()]}, {now:%d.%m.%Y %H:%M}.",
                 "Задачи на 7 дней:", *(map(line, week) if week else ["- нет"])]
        overdue = [t for t in self.overdue if not t["done"]]
        if overdue:
            parts += ["Просрочено:", *map(line, overdue)]
        return "\n".join(parts)

    # ------------------------------------------------------------ background loops
    def start_background(self):
        """Runs once in a worker thread after the window is created."""
        self.tray = tray.start(self)
        combo = self.cfg.get("hotkey", "ctrl+alt+n")
        try:
            if combo and hotkey.register(combo, self.toggle_visible):
                self.hotkey = combo
        except ValueError:
            pass
        self.refresh()
        threading.Thread(target=self._refresh_loop, daemon=True).start()
        threading.Thread(target=self._notify_loop, daemon=True).start()
        if self.cfg.get("spotify", True):
            threading.Thread(target=self._spotify_loop, daemon=True).start()
        if self.cfg.get("stats", True):
            threading.Thread(target=self._stats_loop, daemon=True).start()
        if self.cfg.get("claude_limits", True):
            threading.Thread(target=self._claude_limits_loop, daemon=True).start()

    def _claude_limits_loop(self):
        """Watch the limits file (status line or background refresh). Refresh once ~20 s after the widget
        starts (i.e. after the computer boots), then every hour, but only while Claude is running."""
        every = self.cfg.get("claude_refresh_minutes", 60) * 60
        self.push("claude", self.claude_limits())
        time.sleep(20)  # let the network come up after boot
        if every:
            self.refresh_claude_limits()
        last, last_refresh = None, time.time()
        while True:
            if every and time.time() - last_refresh >= every and claude_usage.claude_running():
                self.refresh_claude_limits()
                last_refresh = time.time()
            limits = self.claude_limits()
            if limits != last:
                last = limits
                self.push("claude", limits)
            time.sleep(15)

    _claude_lock = threading.Lock()

    def refresh_claude_limits(self):
        """One tiny background request through the terminal Claude Code; skipped if one is already running."""
        if not self._claude_lock.acquire(blocking=False):
            return False
        try:
            self.push("claude_busy", True)
            limits = claude_usage.fetch_limits()
            if limits:
                claude_usage.save_limits(CLAUDE_LIMITS_PATH, limits)
            self.push("claude", self.claude_limits())
            return bool(limits)
        finally:
            self.push("claude_busy", False)
            self._claude_lock.release()

    def _stats_loop(self):
        try:
            stats = sysstats.SysStats()
        except OSError:
            return
        while True:
            time.sleep(2)
            if self.visible:  # no point updating a hidden window
                self.push("stats", stats.read())

    def _refresh_loop(self):
        while True:
            time.sleep(self.cfg.get("refresh_minutes", 5) * 60)
            self.refresh()

    @staticmethod
    def _load_notified():
        """Keys "task id|start" of reminders already shown; entries older than a day are dropped."""
        data = load_json(NOTIFIED_PATH)
        cutoff = (datetime.now() - timedelta(days=1)).isoformat(timespec="minutes")
        return {key for key in data.get("shown", []) if key.rsplit("|", 1)[-1] >= cutoff}

    def _notify_loop(self):
        while self.cfg.get("notify_minutes", 10):
            self.check_reminders()
            time.sleep(30)

    def check_reminders(self):
        minutes = self.cfg.get("notify_minutes", 10)
        now = datetime.now()
        for t in self.tasks + self.events:
            if not t["has_time"] or t["done"]:
                continue
            left = (t["start"] - now).total_seconds()
            key = f"{t['id']}|{t['start'].isoformat(timespec='minutes')}"
            if 0 <= left <= minutes * 60 and key not in self.notified:
                # Exactly one reminder per task and start time, also across restarts
                self.notified.add(key)
                NOTIFIED_PATH.write_text(json.dumps({"shown": sorted(self.notified)}, ensure_ascii=False),
                                         encoding="utf-8")
                try:
                    toast(t["title"], f"в {t['start']:%H:%M} — через {max(1, round(left / 60))} мин")
                except OSError:
                    pass

    def _spotify_loop(self):
        try:
            import comtypes  # pycaw needs COM in this thread; multithreaded so WinRT media calls work too
            comtypes.CoInitializeEx(0)  # COINIT_MULTITHREADED
        except Exception:
            pass
        while True:
            self.push_spotify()
            time.sleep(2)

    _spotify_state = None
    _cover = None  # {"track": ..., "url": data URL or None}

    def push_spotify(self):
        """Send the Spotify state to the page when it changed; fetch the cover when the track changes."""
        try:
            st = spotify.status()
        except Exception:
            return
        if st != self._spotify_state:
            self._spotify_state = st
            self.push("spotify", st)
        track = st.get("track") if st.get("running") else None
        if track and (self._cover or {}).get("track") != track:
            self._cover = {"track": track, "url": spotify.cover_data_url()}
            self.push("cover", self._cover)

    # ------------------------------------------------------------ window
    _hwnd = None
    _drag_offset = None

    def on_shown(self):
        """Windows 11 rounded corners and no taskbar button for the frameless window."""
        try:
            hwnd = self._hwnd = int(self.window.native.Handle.ToInt64())
        except Exception:
            return
        try:
            pref = ctypes.c_int(2)  # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref))
        except Exception:
            pass
        GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = -20, 0x80, 0x40000
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
        # pywebview's frameless window comes out a little narrower than asked; set the exact size
        r = self.window_rect()
        width, height = self.prefs.get("size") or [WIDTH, r.bottom - r.top]
        self.set_size(width, height)

    def drag_start(self):
        """Remember where in the window the cursor grabbed it (screen pixels, no DPI conversions)."""
        if not self._hwnd:
            return
        pt, r = wintypes.POINT(), wintypes.RECT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.GetWindowRect(self._hwnd, ctypes.byref(r))
        self._drag_offset = (pt.x - r.left, pt.y - r.top)

    def drag_move(self):
        if not (self._hwnd and self._drag_offset):
            return
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        dx, dy = self._drag_offset
        SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x4, 0x10
        user32.SetWindowPos(self._hwnd, 0, pt.x - dx, pt.y - dy, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)

    # --- size (screen pixels). prefs["size"] = [w, h] once the user resized; None = height follows content
    MIN_W, MIN_H = 260, 150
    _resize_start = None

    def window_rect(self):
        r = wintypes.RECT()
        user32.GetWindowRect(self._hwnd, ctypes.byref(r))
        return r

    def set_size(self, width, height):
        SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x2, 0x4, 0x10
        user32.SetWindowPos(self._hwnd, 0, 0, 0, int(width), int(height), SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE)

    def fit_height(self, height):
        """Auto mode: keep the width, make the height match the content."""
        if self._hwnd:
            r = self.window_rect()
            self.set_size(r.right - r.left, max(60, height))

    def resize_start(self):
        if not self._hwnd:
            return
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        r = self.window_rect()
        self._resize_start = (pt.x, pt.y, r.right - r.left, r.bottom - r.top)

    def resize_move(self):
        if not (self._hwnd and self._resize_start):
            return
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        x0, y0, w0, h0 = self._resize_start
        self.set_size(max(self.MIN_W, w0 + pt.x - x0), max(self.MIN_H, h0 + pt.y - y0))

    def resize_end(self):
        if not (self._hwnd and self._resize_start):
            return
        self._resize_start = None
        r = self.window_rect()
        self.prefs["size"] = [r.right - r.left, r.bottom - r.top]
        self.save_prefs()

    def restore_size(self):
        """Back to the size the user chose (after mini mode or the settings panel)."""
        if self._hwnd and self.prefs.get("size"):
            self.set_size(*self.prefs["size"])

    def reset_size(self):
        """Back to the standard width with the height following the content."""
        self.prefs["size"] = None
        self.save_prefs()
        if self._hwnd:
            self.set_size(WIDTH, self.window_rect().bottom - self.window_rect().top)

    def on_moved(self, x, y):
        # Save the position once dragging stops
        if self._move_timer:
            self._move_timer.cancel()

        def save():
            self.prefs["position"] = [x, y]
            self.save_prefs()
        self._move_timer = threading.Timer(0.8, save)
        self._move_timer.start()

    def call(self, fn):
        """Tray compatibility: pywebview window methods are thread-safe, so run directly."""
        fn()

    def toggle_visible(self):
        if self.visible:
            self.window.hide()
        else:
            self.window.show()
        self.visible = not self.visible

    def toggle_topmost(self):
        on = not self.prefs.get("always_on_top", False)
        self.prefs["always_on_top"] = on
        self.save_prefs()
        # Not window.on_top: pywebview changes the WinForms TopMost property from this (non-UI) thread,
        # which can deadlock the window. Plain SetWindowPos with ASYNCWINDOWPOS never waits on the UI thread.
        if self._hwnd:
            HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
            SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_ASYNCWINDOWPOS = 0x1, 0x2, 0x10, 0x4000
            user32.SetWindowPos(self._hwnd, HWND_TOPMOST if on else HWND_NOTOPMOST, 0, 0, 0, 0,
                                SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS)
        # The page updates the pin itself from the return value; the tray needs a push (sent off-thread)
        threading.Thread(target=self.push, args=("settings", self.settings()), daemon=True).start()
        return on

    def quit_app(self):
        if self.tray:
            self.tray.stop()
        self.window.destroy()

    def restart(self):
        """Start a fresh copy (it waits for this one to release the hotkey) and quit."""
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
        subprocess.Popen([sys.executable, str(HERE / "notion_widget.py"), "--restart"], creationflags=flags, close_fds=True)
        threading.Timer(0.3, self.quit_app).start()

    # ------------------------------------------------------------ settings
    def config_for_ui(self):
        cfg = copy.deepcopy(self.cfg)
        saved = {}
        for key in SECRETS:
            saved[key] = bool(get_path(cfg, key))
            if get_path(cfg, key) is not None:
                set_path(cfg, key, "")
        return {"config": cfg, "secrets_saved": saved}

    def save_config(self, values):
        """values: {"dotted.key": value}. Empty secrets keep the saved value."""
        cfg = copy.deepcopy(self.cfg)
        for key, value in values.items():
            if key in SECRETS and not str(value).strip():
                continue
            if isinstance(value, str):
                value = value.strip()
            set_path(cfg, key, value)

        db = str(cfg.get("database_id", "")).replace("-", "")
        match = re.search(r"[0-9a-fA-F]{32}", db)  # accepts a full database link too
        if db and not match:
            return {"ok": False, "error": "ID базы: вставь ссылку на базу или 32-символьный ID"}
        if match:
            cfg["database_id"] = match.group(0).lower()
        if cfg.get("hotkey"):
            try:
                hotkey.parse(cfg["hotkey"])
            except ValueError as e:
                return {"ok": False, "error": f"Горячая клавиша: {e}. Пример: ctrl+alt+n"}
        for key in ("notify_minutes", "refresh_minutes"):
            try:
                cfg[key] = max(0 if key == "notify_minutes" else 1, int(cfg.get(key, 0)))
            except (TypeError, ValueError):
                return {"ok": False, "error": "Минуты должны быть числом"}

        CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.restart()
        return {"ok": True}


class Api:
    """Methods callable from the page as pywebview.api.<name>(...)."""

    def __init__(self, widget):
        self._w = widget  # underscore: pywebview doesn't expose private attributes

    def init(self):
        self._w.ready = True
        w = self._w
        return {"settings": w.settings(), "data": w.snapshot(), "spotify": w._spotify_state, "cover": w._cover,
                "claude": w.claude_limits()}

    def refresh_claude(self):
        threading.Thread(target=self._w.refresh_claude_limits, daemon=True).start()

    def open_claude(self):
        """Open the Claude desktop app (its claude:// link handler), or claude.ai if the app isn't installed."""
        try:
            os.startfile("claude://")
        except OSError:
            webbrowser.open("https://claude.ai")

    def get_config(self):
        return self._w.config_for_ui()

    def save_config(self, values):
        return self._w.save_config(values)

    def refresh(self):
        self._w.refresh()

    def set_month(self, iso):
        self._w.view_month = date.fromisoformat(iso)
        self._w.refresh()

    def toggle_done(self, task_id, done):
        w = self._w
        for t in w.tasks + w.overdue:
            if t["id"] == task_id:
                t["done"] = done
        if not w.notion:
            return {"ok": True}
        try:
            w.notion.set_done(task_id, done)
            return {"ok": True}
        except Exception as e:
            for t in w.tasks + w.overdue:
                if t["id"] == task_id:
                    t["done"] = not done
            return {"ok": False, "error": f"не удалось отметить: {e}"}

    def quick_add(self, text):
        w = self._w
        try:
            title, when = quick_add.parse(text)
        except ValueError as e:
            return {"ok": False, "error": f"не понял: {e}"}
        timed = isinstance(when, datetime)
        start = when if timed else datetime.combine(when, datetime.min.time())
        label = f"{start:%d.%m %H:%M}" if timed else f"{start:%d.%m}"
        if not w.notion:
            w.tasks.append({"id": f"demo-{text}", "title": title, "start": start, "has_time": timed,
                            "done": False, "tags": [], "url": None, "source": "notion"})
            w.push("data", w.snapshot())
            return {"ok": True, "message": f"добавлено (демо): {title} — {label}"}
        try:
            w.notion.create(title, when)
        except Exception as e:
            return {"ok": False, "error": f"не удалось добавить: {e}"}
        w.refresh()
        return {"ok": True, "message": f"добавлено: {title} — {label}"}

    def open_url(self, url):
        if url:
            if self._w.cfg.get("open_in_app", True):
                url = url.replace("https://", "notion://", 1)  # open in the Notion desktop app
            webbrowser.open(url)

    def save_pref(self, key, value):
        self._w.prefs[key] = value
        self._w.save_prefs()

    def resize(self, height):
        self._w.fit_height(int(height))

    def drag_start(self):
        self._w.drag_start()

    def drag_move(self):
        self._w.drag_move()

    def resize_start(self):
        self._w.resize_start()

    def resize_move(self):
        self._w.resize_move()

    def resize_end(self):
        self._w.resize_end()

    def reset_size(self):
        self._w.reset_size()

    def restore_size(self):
        self._w.restore_size()

    def hide(self):
        if self._w.visible:
            self._w.toggle_visible()

    def toggle_topmost(self):
        return self._w.toggle_topmost()

    # --- AI chat
    def ask(self, question):
        w = self._w
        if not w.chat.available:
            return {"ok": False, "error": "Не хватает пакета: pip install -r requirements.txt"}
        if not w.chat.has_key:
            return {"ok": False, "error": w.chat.key_hint}
        context = w.chat_context()

        def work():
            try:
                w.chat.ask(question, context, lambda chunk: w.push("chat", {"chunk": chunk}))
                w.push("chat", {"done": True})
            except Exception as e:
                w.push("chat", {"error": w.chat.describe_error(e)})
        threading.Thread(target=work, daemon=True).start()
        return {"ok": True}

    def new_chat(self):
        self._w.chat.reset()

    # --- Spotify
    def spotify(self, action):
        {"previous": spotify.previous, "play_pause": spotify.play_pause, "next": spotify.next_track}[action]()
        threading.Timer(0.6, self._w.push_spotify).start()

    def set_volume(self, value):
        spotify.set_volume(int(value))

    def spotify_seek(self, seconds):
        spotify.seek(seconds)
        threading.Timer(0.5, self._w.push_spotify).start()

    def spotify_open(self):
        spotify.focus_or_launch()


def single_instance(wait_seconds):
    """Hold a named mutex so only one widget runs. Returns False if another copy keeps running."""
    ERROR_ALREADY_EXISTS = 183
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    deadline = time.time() + wait_seconds
    while True:
        handle = kernel32.CreateMutexW(None, False, "Local\\NotionDesktopWidget")
        if ctypes.get_last_error() != ERROR_ALREADY_EXISTS:
            single_instance.handle = handle  # keep it alive for the life of the process
            return True
        kernel32.CloseHandle(handle)
        if time.time() >= deadline:
            return False
        time.sleep(0.5)


def main():
    # After "save settings" the old copy is still exiting: wait for it; otherwise a second copy just quits
    if not single_instance(wait_seconds=10 if "--restart" in sys.argv else 0):
        return
    cfg = load_json(CONFIG_PATH)
    widget = Widget(cfg)
    theme = widget.prefs.get("theme", "auto")
    dark = theme == "dark" or (theme == "auto" and windows_dark_mode())
    x, y = widget.prefs.get("position") or [user32.GetSystemMetrics(0) - WIDTH - 40, 40]
    width, height = widget.prefs.get("size") or [WIDTH, 640]
    window = webview.create_window(
        "Notion виджет", url=str(UI_PATH), js_api=Api(widget),
        width=width, height=height, x=x, y=y,
        frameless=True, easy_drag=False, resizable=False, shadow=True,
        on_top=widget.prefs.get("always_on_top", False),
        background_color="#191919" if dark else "#FFFFFF",
    )
    widget.window = window
    window.events.shown += widget.on_shown
    window.events.moved += widget.on_moved
    webview.start(widget.start_background)


if __name__ == "__main__":
    main()
