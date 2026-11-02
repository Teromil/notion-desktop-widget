"""
Notion desktop widget for Windows.
Light "paper" theme in the style of Notion: tasks with times, overdue tasks, tag filters,
quick add, reminders, month calendar and Google Calendar events.
"""
import calendar
import ctypes
import json
import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path

import claude_chat
import gemini_chat
import hotkey
import quick_add
import spotify
import tray
from ical_feed import fetch_events
from notifier import toast
from notion_api import Notion

HERE = Path(__file__).parent
CONFIG_PATH = HERE / "config.json"
STATE_PATH = HERE / "state.json"  # window position and UI toggles, written by the widget

# --- Theme
PAPER = "#ffffff"
BORDER = "#e9e9e7"
TEXT = "#37352f"
MUTED = "#9b9a97"
FAINT = "#d3d1cb"
HOVER = "#f7f7f5"
BUSY_BG = "#f1f1ef"
ACCENT = "#2383e2"
SELECT_BG = "#e7f3f8"
RED, RED_BG = "#d44c47", "#fdebec"
GCAL = "#9065b0"
FONT = "Segoe UI"
WIDTH = 340

# Notion tag colors: name -> (background, text)
NOTION_COLORS = {
    "default": ("#f1f1ef", "#787774"), "gray": ("#f1f1ef", "#787774"),
    "brown": ("#f4eeee", "#9f6b53"), "orange": ("#fbecdd", "#d9730d"),
    "yellow": ("#fbf3db", "#cb912f"), "green": ("#edf3ec", "#448361"),
    "blue": ("#e7f3f8", "#337ea9"), "purple": ("#f6f3f9", "#9065b0"),
    "pink": ("#faf1f5", "#c14c8a"), "red": ("#fdebec", "#d44c47"),
}

WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
WD_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]
MONTHS_NOM = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
              "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
PLACEHOLDER = "+ Новая задача: созвон завтра 15:00"


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def plural_tasks(n):
    if n % 10 == 1 and n % 100 != 11:
        return "задача"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "задачи"
    return "задач"


def shorten(text, limit):
    return text if len(text) <= limit else text[:limit - 1] + "…"


def clear(frame):
    for w in frame.winfo_children():
        w.destroy()


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
        task(6, "Тренировка", today + timedelta(days=2, hours=19), tag=home),
        task(7, "Дедлайн проекта", today + timedelta(days=3, hours=18), tag=study),
    ]
    overdue = [task(8, "Сдать реферат", today - timedelta(days=2), has_time=False, tag=study)]
    events = [{"id": "g1", "title": "Встреча (Google)", "start": today + timedelta(hours=15),
               "has_time": True, "done": False, "tags": [], "url": None, "source": "gcal"}]
    return tasks, overdue, events


class NotionWidget(tk.Tk):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.prefs = load_json(STATE_PATH)
        self.notion = Notion(cfg) if cfg.get("token") and cfg.get("database_id") else None
        self.tasks, self.overdue, self.events = [], [], []
        self.today = date.today()
        self.view_month = self.today.replace(day=1)
        self.selected_day = self.today
        self.notified = set()
        self.calls = queue.Queue()
        provider = cfg.get("ai_provider", "claude")
        self.chat = gemini_chat.GeminiChat(cfg) if provider == "gemini" else claude_chat.ClaudeChat(cfg)
        self._asking = False
        self._sp_dragging = False

        self.title("Notion виджет")
        self.overrideredirect(True)  # frameless
        self.configure(bg=BORDER)
        self.attributes("-topmost", self.prefs.get("always_on_top", cfg.get("always_on_top", False)))
        self.attributes("-alpha", cfg.get("opacity", 1.0))
        x, y = self.prefs.get("position") or cfg.get("position") or [self.winfo_screenwidth() - WIDTH - 40, 40]
        self.geometry(f"+{x}+{y}")

        self.f = {
            "day": tkfont.Font(family="Georgia", size=17),
            "clock": tkfont.Font(family=FONT, size=11),
            "small": tkfont.Font(family=FONT, size=9),
            "small_b": tkfont.Font(family=FONT, size=9, weight="bold"),
            "task": tkfont.Font(family=FONT, size=10),
            "task_done": tkfont.Font(family=FONT, size=10, overstrike=1),
            "pill": tkfont.Font(family=FONT, size=8),
        }
        self.paper = tk.Frame(self, bg=PAPER, padx=16, pady=12)
        self.paper.pack(padx=1, pady=1, fill="both")  # 1px BORDER around the paper
        self._build()
        self.update_idletasks()
        self._round_corners()

        self.tray = tray.start(self)
        combo = cfg.get("hotkey", "ctrl+alt+n")
        try:
            self.hotkey = combo if combo and hotkey.register(combo, lambda: self.call(self.toggle_visible)) else None
        except ValueError:
            self.hotkey = None
        self._poll_calls()
        self._tick()
        self._notify_loop()
        if self.cfg.get("spotify", True):
            self._spotify_loop()
        self.refresh()

    # ------------------------------------------------------------ layout
    def _build(self):
        p = self.paper
        tk.Frame(p, width=WIDTH - 34, height=0, bg=PAPER).pack()  # fixes the width

        head = tk.Frame(p, bg=PAPER)
        head.pack(fill="x")
        self.day_lbl = tk.Label(head, font=self.f["day"], fg=TEXT, bg=PAPER)
        self.day_lbl.pack(side="left")
        tk.Button(head, text="—", command=self.close, **self._flat_btn()).pack(side="right")
        tk.Button(head, text="⟳", command=self.refresh, **self._flat_btn()).pack(side="right")
        self.pin_btn = tk.Button(head, text="📌", command=self.toggle_topmost, **self._flat_btn())
        self.pin_btn.pack(side="right")
        self.ask_btn = tk.Button(head, text="✦", command=self.toggle_ask, **self._flat_btn(12))
        self.ask_btn.pack(side="right")
        self.clock_lbl = tk.Label(head, font=self.f["clock"], fg=MUTED, bg=PAPER)
        self.clock_lbl.pack(side="right", padx=(0, 6))
        self.date_lbl = tk.Label(p, font=self.f["small"], fg=MUTED, bg=PAPER, anchor="w")
        self.date_lbl.pack(fill="x")
        self._make_draggable(p, head, self.day_lbl, self.clock_lbl, self.date_lbl)
        for w in (head, self.day_lbl, self.clock_lbl, self.date_lbl):
            w.bind("<Double-Button-1>", lambda e: self.toggle_mini())
        self._update_pin()

        # Everything below the date lives in `body`, so mini mode can hide it in one go
        self.body = tk.Frame(p, bg=PAPER)
        if not self.prefs.get("mini", False):
            self.body.pack(fill="x")
        p = self.body

        self.ask_frame = tk.Frame(p, bg=PAPER)
        self.ask_frame.pack(fill="x")
        self._build_ask()
        if not self.prefs.get("ask_open", False):
            self.ask_frame.pack_forget()
        self._ask_anchor = tk.Frame(p, height=0, bg=PAPER)  # keeps the panel's position when re-shown
        self._ask_anchor.pack(fill="x")

        self.overdue_frame = tk.Frame(p, bg=PAPER)
        self.overdue_frame.pack(fill="x")
        self.chips_frame = tk.Frame(p, bg=PAPER)
        self.chips_frame.pack(fill="x")
        self.list_title = tk.Label(p, font=self.f["small_b"], fg=MUTED, bg=PAPER, anchor="w")
        self.list_title.pack(fill="x", pady=(10, 4))
        self.list_frame = tk.Frame(p, bg=PAPER)
        self.list_frame.pack(fill="x")

        self.entry = tk.Entry(p, font=self.f["task"], relief="flat", bd=0, bg=HOVER, fg=MUTED,
                              insertbackground=TEXT, highlightthickness=0)
        self.entry.pack(fill="x", pady=(10, 0), ipady=5)
        self._set_placeholder()
        self.entry.bind("<Button-1>", lambda e: (self.focus_force(), self.entry.focus_set()))
        self.entry.bind("<FocusIn>", self._clear_placeholder)
        self.entry.bind("<FocusOut>", lambda e: self._set_placeholder())
        self.entry.bind("<Return>", self.quick_add)

        tk.Frame(p, height=1, bg=BORDER).pack(fill="x", pady=(12, 6))
        self.upcoming_frame = tk.Frame(p, bg=PAPER)
        self.upcoming_frame.pack(fill="x")

        cal_head = tk.Frame(p, bg=PAPER)
        cal_head.pack(fill="x", pady=(8, 2))
        self.cal_toggle = tk.Label(cal_head, font=self.f["small_b"], fg=MUTED, bg=PAPER, cursor="hand2")
        self.cal_toggle.pack(side="left")
        self.cal_toggle.bind("<Button-1>", lambda e: self.toggle_calendar())
        self.next_btn = tk.Button(cal_head, text="›", command=lambda: self.shift_month(1), **self._flat_btn())
        self.prev_btn = tk.Button(cal_head, text="‹", command=lambda: self.shift_month(-1), **self._flat_btn())
        self.month_lbl = tk.Label(cal_head, font=self.f["small"], fg=TEXT, bg=PAPER)
        self.cal_frame = tk.Frame(p, bg=PAPER)
        self.cal_frame.pack()

        if self.cfg.get("spotify", True):
            self._build_spotify()

        self.status_lbl = tk.Label(p, font=self.f["pill"], fg=MUTED, bg=PAPER, anchor="w",
                                   justify="left", wraplength=WIDTH - 40)
        self.status_lbl.pack(fill="x", pady=(8, 0))

    def _flat_btn(self, size=10):
        return dict(bg=PAPER, fg=MUTED, activebackground=HOVER, activeforeground=TEXT,
                    relief="flat", bd=0, padx=4, font=(FONT, size), cursor="hand2")

    def _focusable(self, widget):
        """Frameless windows don't take keyboard focus on their own: grab it on click."""
        widget.bind("<Button-1>", lambda e: (self.focus_force(), widget.focus_set()), add="+")

    # --- Claude panel
    def _build_ask(self):
        f = self.ask_frame
        tk.Frame(f, height=1, bg=BORDER).pack(fill="x", pady=(10, 8))
        top = tk.Frame(f, bg=PAPER)
        top.pack(fill="x")
        tk.Label(top, text=f"✦ Спросить {self.chat.name}", font=self.f["small_b"], fg=TEXT, bg=PAPER).pack(side="left")
        tk.Button(top, text="Новый чат", command=self.new_chat, **self._flat_btn(8)).pack(side="right")

        self.ask_input = tk.Text(f, height=2, width=1, wrap="word", font=self.f["task"], relief="flat", bd=0,
                                 bg=HOVER, fg=TEXT, insertbackground=TEXT, highlightthickness=0, padx=8, pady=6)
        self.ask_input.pack(fill="x", pady=(6, 0))
        self._focusable(self.ask_input)
        self.ask_input.bind("<Return>", self.send_question)
        self.ask_input.bind("<Shift-Return>", lambda e: None)  # newline
        tk.Label(f, text="Enter — отправить · Shift+Enter — новая строка", font=self.f["pill"],
                 fg=MUTED, bg=PAPER).pack(anchor="w")

        self.ask_output = tk.Text(f, height=7, width=1, wrap="word", font=self.f["task"], relief="flat", bd=0,
                                  bg=PAPER, fg=TEXT, highlightthickness=0, padx=0, pady=4, state="disabled",
                                  cursor="arrow", spacing3=2)
        self.ask_output.tag_configure("q", foreground=MUTED, font=self.f["small_b"], spacing1=6)
        self.ask_output.tag_configure("err", foreground=RED)
        self.ask_output.pack(fill="x")
        self._out(f"Задай вопрос — {self.chat.name} видит твои задачи на неделю.\n", "q")

    def _out(self, text, tag=None):
        self.ask_output.config(state="normal")
        self.ask_output.insert("end", text, tag or ())
        self.ask_output.config(state="disabled")
        self.ask_output.see("end")

    def toggle_ask(self):
        is_open = not self.prefs.get("ask_open", False)
        self.prefs["ask_open"] = is_open
        self.save_prefs()
        if is_open:
            self.ask_frame.pack(fill="x", before=self._ask_anchor)
            self.ask_input.focus_force()
        else:
            self.ask_frame.pack_forget()
        self.ask_btn.config(fg=ACCENT if is_open else MUTED)

    def new_chat(self):
        self.chat.reset()
        self.ask_output.config(state="normal")
        self.ask_output.delete("1.0", "end")
        self.ask_output.config(state="disabled")

    def send_question(self, event=None):
        question = self.ask_input.get("1.0", "end").strip()
        if not question or self._asking:
            return "break"
        if not self.chat.available:
            self._out("Не хватает пакета: pip install -r requirements.txt\n", "err")
            return "break"
        if not self.chat.has_key:
            self._out(self.chat.key_hint + "\n", "err")
            return "break"
        self.ask_input.delete("1.0", "end")
        self._asking = True
        self._out(question + "\n", "q")
        context = self._chat_context()

        def work():
            try:
                self.chat.ask(question, context, lambda chunk: self.call(lambda: self._out(chunk)))
            except Exception as e:
                msg = self.chat.describe_error(e)
                self.call(lambda: self._out(f"Ошибка: {msg}", "err"))
            finally:
                self.call(lambda: (self._out("\n"), setattr(self, "_asking", False)))
        threading.Thread(target=work, daemon=True).start()
        return "break"

    def _chat_context(self):
        now, today = datetime.now(), date.today()

        def line(t):
            when = t["start"].strftime("%d.%m %H:%M" if t["has_time"] else "%d.%m, весь день")
            src = " [Google Календарь]" if t["source"] == "gcal" else ""
            return f"- {when} — {t['title']}{' (выполнено)' if t['done'] else ''}{src}"

        week = sorted((x for x in self.tasks + self.events if today <= x["start"].date() < today + timedelta(days=7)),
                      key=lambda x: x["start"])
        parts = [f"Сейчас: {WEEKDAYS[now.weekday()].lower()}, {now:%d.%m.%Y %H:%M}.",
                 "Задачи на 7 дней:", *(map(line, week) if week else ["- нет"])]
        overdue = [t for t in self.overdue if not t["done"]]
        if overdue:
            parts += ["Просрочено:", *map(line, overdue)]
        return "\n".join(parts)

    # --- Spotify bar
    def _build_spotify(self):
        f = tk.Frame(self.body, bg=PAPER)
        f.pack(fill="x", pady=(10, 0))
        tk.Frame(f, height=1, bg=BORDER).pack(fill="x", pady=(0, 6))
        self.sp_track = tk.Label(f, font=self.f["small"], fg=TEXT, bg=PAPER, anchor="w", cursor="hand2")
        self.sp_track.pack(fill="x")
        self.sp_track.bind("<Button-1>", lambda e: spotify.focus_or_launch())

        ctr = tk.Frame(f, bg=PAPER)
        ctr.pack(fill="x")
        for text, action in (("⏮", spotify.previous), ("⏯", spotify.play_pause), ("⏭", spotify.next_track)):
            tk.Button(ctr, text=text, command=lambda a=action: (a(), self.after(500, self._spotify_update)),
                      **self._flat_btn(12)).pack(side="left")
        if spotify.HAS_VOLUME:
            self.sp_volume = tk.Scale(ctr, from_=0, to=100, orient="horizontal", showvalue=0, length=150, width=8,
                                      sliderlength=14, bd=0, highlightthickness=0, sliderrelief="flat",
                                      bg=MUTED, troughcolor=BUSY_BG, activebackground=ACCENT,
                                      command=lambda v: spotify.set_volume(int(float(v))))
            self.sp_volume.pack(side="right", pady=(4, 0))
            self.sp_volume.bind("<ButtonPress-1>", lambda e: setattr(self, "_sp_dragging", True))
            self.sp_volume.bind("<ButtonRelease-1>", lambda e: setattr(self, "_sp_dragging", False))
            tk.Label(ctr, text="🔊", font=self.f["small"], fg=MUTED, bg=PAPER).pack(side="right", padx=(0, 4))
        else:  # no pycaw: system volume keys
            tk.Button(ctr, text="＋", command=lambda: spotify.volume_step(1), **self._flat_btn()).pack(side="right")
            tk.Button(ctr, text="－", command=lambda: spotify.volume_step(-1), **self._flat_btn()).pack(side="right")

    def _spotify_update(self):
        try:
            st = spotify.status()
        except Exception:
            return
        if not st["running"]:
            self.sp_track.config(text="♫ Spotify не запущен — открыть", fg=MUTED)
            return
        icon = "▶" if st["playing"] else "⏸"
        self.sp_track.config(text=shorten(f"{icon}  {st['track'] or 'Spotify'}", 48),
                             fg=TEXT if st["playing"] else MUTED)
        if spotify.HAS_VOLUME and st["volume"] is not None and not self._sp_dragging:
            if abs(self.sp_volume.get() - st["volume"]) > 1:
                self.sp_volume.set(st["volume"])

    def _spotify_loop(self):
        self._spotify_update()
        self.after(2000, self._spotify_loop)

    def _round_corners(self):
        """Windows 11 rounded corners for the frameless window (ignored on Windows 10)."""
        try:
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            pref = ctypes.c_int(2)  # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref))
        except Exception:
            pass

    def _make_draggable(self, *widgets):
        for w in widgets:
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)

    def _drag_start(self, e):
        self._drag = (e.x_root - self.winfo_x(), e.y_root - self.winfo_y())

    def _drag_move(self, e):
        self.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _drag_end(self, e):
        self.prefs["position"] = [self.winfo_x(), self.winfo_y()]
        self.save_prefs()

    def _set_placeholder(self):
        if not self.entry.get():
            self.entry.insert(0, PLACEHOLDER)
            self.entry.config(fg=MUTED)

    def _clear_placeholder(self, e=None):
        if self.entry.get() == PLACEHOLDER:
            self.entry.delete(0, "end")
            self.entry.config(fg=TEXT)

    # ------------------------------------------------------------ loops
    def call(self, fn):
        """Run fn on the Tk thread (safe to use from worker/tray threads)."""
        self.calls.put(fn)

    def _poll_calls(self):
        while not self.calls.empty():
            self.calls.get()()
        self.after(150, self._poll_calls)

    def _tick(self):
        now = datetime.now()
        self.day_lbl.config(text=WEEKDAYS[now.weekday()])
        self.clock_lbl.config(text=now.strftime("%H:%M"))
        self._update_date_line(now)
        if now.date() != self.today:  # midnight: move "today" forward
            if self.selected_day == self.today:
                self.selected_day = now.date()
            self.today = now.date()
            self.refresh()
        elif now.second == 0:  # each minute: recolour tasks whose time has passed
            self.render_list()
        self.after(1000, self._tick)

    def _notify_loop(self):
        minutes = self.cfg.get("notify_minutes", 10)
        if minutes:
            now = datetime.now()
            for t in self.tasks + self.events:
                if not t["has_time"] or t["done"]:
                    continue
                left = (t["start"] - now).total_seconds()
                key = (t["id"], t["start"])
                if 0 <= left <= minutes * 60 and key not in self.notified:
                    self.notified.add(key)
                    try:
                        toast(t["title"], f"в {t['start']:%H:%M} — через {max(1, round(left / 60))} мин")
                    except OSError:
                        pass
        self.after(30_000, self._notify_loop)

    # ------------------------------------------------------------ data
    def refresh(self):
        self.set_status("обновление…")
        threading.Thread(target=self._fetch, daemon=True).start()
        if hasattr(self, "_refresh_job"):
            self.after_cancel(self._refresh_job)
        self._refresh_job = self.after(self.cfg.get("refresh_minutes", 5) * 60_000, self.refresh)

    def _fetch(self):
        # Range covers the visible month plus the next week (for the "upcoming" block)
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

        status = "; ".join(errors) or f"обновлено в {datetime.now():%H:%M}"
        self.call(lambda: self._apply(tasks, overdue, events, status))

    def _apply(self, tasks, overdue, events, status):
        self.tasks, self.overdue, self.events = tasks, overdue, events
        self.set_status(status)
        self.render()

    def set_status(self, text):
        self.status_lbl.config(text=text)

    @property
    def can_check(self):
        return self.notion is None or self.notion.can_check

    def passes_filter(self, item):
        tag = self.prefs.get("tag_filter")
        if not tag:
            return True
        return any(name == tag for name, _ in item["tags"])

    def items_on(self, day):
        items = [x for x in self.tasks + self.events if x["start"].date() == day and self.passes_filter(x)]
        return sorted(items, key=lambda x: (x["done"], not x["has_time"], x["start"]))

    # ------------------------------------------------------------ actions
    def toggle_done(self, task):
        task["done"] = not task["done"]
        self.render()
        if not self.notion:
            return

        def work():
            try:
                self.notion.set_done(task["id"], task["done"])
            except Exception as e:
                task["done"] = not task["done"]
                self.call(lambda: (self.set_status(f"не удалось отметить: {e}"), self.render()))
        threading.Thread(target=work, daemon=True).start()

    def quick_add(self, event=None):
        text = self.entry.get().strip()
        if not text or text == PLACEHOLDER:
            return
        try:
            title, when = quick_add.parse(text)
        except ValueError as e:
            self.set_status(f"не понял: {e}")
            return
        self.entry.delete(0, "end")
        start = when if isinstance(when, datetime) else datetime.combine(when, datetime.min.time())
        label = f"{start:%d.%m %H:%M}" if isinstance(when, datetime) else f"{start:%d.%m}"

        if not self.notion:
            self.tasks.append({"id": f"demo-{text}", "title": title, "start": start,
                               "has_time": isinstance(when, datetime), "done": False,
                               "tags": [], "url": None, "source": "notion"})
            self.set_status(f"добавлено (демо): {title} — {label}")
            self.render()
            return

        def work():
            try:
                self.notion.create(title, when)
                self.call(lambda: (self.set_status(f"добавлено: {title} — {label}"), self.refresh()))
            except Exception as e:
                self.call(lambda: self.set_status(f"не удалось добавить: {e}"))
        threading.Thread(target=work, daemon=True).start()

    def open_task(self, task):
        url = task.get("url")
        if not url:
            return
        if self.cfg.get("open_in_app", True):
            url = url.replace("https://", "notion://", 1)  # open in the Notion desktop app
        webbrowser.open(url)

    def set_tag_filter(self, tag):
        self.prefs["tag_filter"] = tag
        self.save_prefs()
        self.render()

    def select_day(self, day):
        self.selected_day = day
        if day.replace(day=1) != self.view_month:
            self.view_month = day.replace(day=1)
            self.refresh()
        self.render()

    def shift_month(self, delta):
        y, m = divmod(self.view_month.month - 1 + delta, 12)
        self.view_month = date(self.view_month.year + y, m + 1, 1)
        self.render_calendar()
        self.refresh()

    def toggle_calendar(self):
        self.prefs["calendar_open"] = not self.prefs.get("calendar_open", True)
        self.save_prefs()
        self.render_calendar()

    def toggle_visible(self):
        if self.state() == "withdrawn":
            self.deiconify()
            self.lift()
        else:
            self.withdraw()

    def toggle_topmost(self):
        self.prefs["always_on_top"] = not self.prefs.get("always_on_top", False)
        self.attributes("-topmost", self.prefs["always_on_top"])
        self.save_prefs()
        self._update_pin()

    def _update_pin(self):
        on = self.prefs.get("always_on_top", False)
        self.pin_btn.config(fg=ACCENT if on else FAINT)
        self.ask_btn.config(fg=ACCENT if self.prefs.get("ask_open", False) else MUTED)

    def close(self):
        if self.tray or self.hotkey:  # keep running: bring back from the tray or with the hotkey
            self.withdraw()
        else:
            self.quit_app()

    def toggle_mini(self):
        self.prefs["mini"] = not self.prefs.get("mini", False)
        self.save_prefs()
        if self.prefs["mini"]:
            self.body.pack_forget()
        else:
            self.body.pack(fill="x")
        self._update_date_line(datetime.now())

    def _update_date_line(self, now):
        """Date under the weekday; in mini mode it shows the next task instead."""
        text = f"{now.day} {MONTHS_GEN[now.month - 1]} {now.year}"
        if self.prefs.get("mini", False):
            upcoming = [t for t in self.items_on(now.date()) if not t["done"] and t["has_time"] and t["start"] >= now]
            text = (f"Дальше: {upcoming[0]['start']:%H:%M} {shorten(upcoming[0]['title'], 30)}"
                    if upcoming else f"{text} · на сегодня всё")
        self.date_lbl.config(text=text)

    def quit_app(self):
        if self.tray:
            self.tray.stop()
        self.destroy()

    def save_prefs(self):
        STATE_PATH.write_text(json.dumps(self.prefs, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------------------ rendering
    def render(self):
        self.render_overdue()
        self.render_chips()
        self.render_list()
        self.render_upcoming()
        self.render_calendar()

    def render_overdue(self):
        clear(self.overdue_frame)
        items = [t for t in self.overdue if not t["done"] and self.passes_filter(t)]
        if not items:
            return
        tk.Label(self.overdue_frame, text=f"Просрочено · {len(items)}", font=self.f["small_b"],
                 fg=RED, bg=PAPER, anchor="w").pack(fill="x", pady=(10, 4))
        for t in items[:5]:
            self._task_row(self.overdue_frame, t, overdue=True)

    def render_chips(self):
        clear(self.chips_frame)
        tags = {}
        for t in self.tasks + self.overdue:
            for name, color in t["tags"]:
                tags.setdefault(name, color)
        if not tags:
            return
        current = self.prefs.get("tag_filter")
        chips = [("Все", None, "default")] + [(n, n, c) for n, c in sorted(tags.items())]

        row, used, max_w = None, 0, WIDTH - 34
        for text, value, color in chips:
            w = self.f["pill"].measure(text) + 18
            if row is None or used + w > max_w:  # wrap to a new line
                first = row is None
                row = tk.Frame(self.chips_frame, bg=PAPER)
                row.pack(fill="x", pady=(10 if first else 3, 0))
                used = 0
            selected = value == current
            bg, fg = NOTION_COLORS.get(color, NOTION_COLORS["default"]) if selected else (PAPER, MUTED)
            chip = tk.Label(row, text=text, font=self.f["pill"], bg=bg, fg=fg, padx=6, pady=1,
                            cursor="hand2", highlightthickness=1,
                            highlightbackground=bg if selected else BORDER)
            chip.pack(side="left", padx=(0, 4))
            chip.bind("<Button-1>", lambda e, v=value: self.set_tag_filter(v))
            used += w

    def render_list(self):
        clear(self.list_frame)
        d = self.selected_day
        self.list_title.config(
            text="Сегодня" if d == date.today() else f"{WD_SHORT[d.weekday()]}, {d.day} {MONTHS_GEN[d.month - 1]}")
        items = self.items_on(d)
        if not items:
            tk.Label(self.list_frame, text="Задач нет", font=self.f["task"], fg=MUTED, bg=PAPER,
                     anchor="w").pack(fill="x")
        for t in items:
            self._task_row(self.list_frame, t)

    def _task_row(self, parent, t, overdue=False):
        row = tk.Frame(parent, bg=PAPER)
        row.pack(fill="x", pady=2)
        is_event = t["source"] == "gcal"
        checkable = not is_event and self.can_check

        box = tk.Canvas(row, width=14, height=14, bg=PAPER, highlightthickness=0,
                        cursor="hand2" if checkable else "")
        box.pack(side="left", padx=(0, 8), anchor="n", pady=2)
        if is_event:
            box.create_rectangle(5, 1, 8, 13, fill=GCAL, outline="")
        elif t["done"]:
            box.create_rectangle(1, 1, 13, 13, fill=ACCENT, outline=ACCENT)
            box.create_line(4, 7, 6, 10, 10, 4, fill="white", width=2)
        elif checkable:
            box.create_rectangle(1, 1, 13, 13, outline=MUTED, width=1.5)
        else:
            box.create_oval(5, 5, 9, 9, fill=MUTED, outline="")
        if checkable:
            box.bind("<Button-1>", lambda e: self.toggle_done(t))

        missed = (not is_event and not t["done"] and t["has_time"]
                  and t["start"].date() == date.today() and t["start"] < datetime.now())
        if overdue:
            pill = t["start"].strftime("%d.%m %H:%M" if t["has_time"] else "%d.%m")
            bg, fg = RED_BG, RED
        elif missed:  # time already passed today
            pill = t["start"].strftime("%H:%M")
            bg, fg = RED_BG, RED
        else:
            pill = t["start"].strftime("%H:%M") if t["has_time"] else ""
            color = "purple" if is_event else (t["tags"][0][1] if t["tags"] else "blue")
            bg, fg = NOTION_COLORS.get(color, NOTION_COLORS["default"])
        if pill and not t["done"]:
            tk.Label(row, text=pill, font=self.f["pill"], bg=bg, fg=fg, padx=5).pack(side="right", anchor="n")

        title = tk.Label(row, text=t["title"], anchor="w", justify="left", wraplength=200, bg=PAPER,
                         font=self.f["task_done" if t["done"] else "task"],
                         fg=MUTED if t["done"] else TEXT, cursor="hand2" if t.get("url") else "")
        title.pack(side="left", fill="x", expand=True)
        if t.get("url"):
            title.bind("<Button-1>", lambda e: self.open_task(t))

    def render_upcoming(self):
        clear(self.upcoming_frame)
        today, shown = date.today(), 0
        for i in range(1, 8):
            d = today + timedelta(days=i)
            items = [x for x in self.items_on(d) if not x["done"]]
            if not items:
                continue
            what = items[0]["title"] if len(items) == 1 else f"{len(items)} {plural_tasks(len(items))}"
            lbl = tk.Label(self.upcoming_frame, text=shorten(f"{WD_SHORT[d.weekday()]} {d.day} — {what}", 46),
                           font=self.f["small"], fg=MUTED, bg=PAPER, anchor="w", cursor="hand2")
            lbl.pack(fill="x")
            lbl.bind("<Button-1>", lambda e, d=d: self.select_day(d))
            shown += 1
            if shown == 4:
                break
        if not shown:
            tk.Label(self.upcoming_frame, text="На неделе пусто", font=self.f["small"], fg=MUTED,
                     bg=PAPER, anchor="w").pack(fill="x")

    def render_calendar(self):
        clear(self.cal_frame)
        is_open = self.prefs.get("calendar_open", True)
        self.cal_toggle.config(text=("▾ " if is_open else "▸ ") + "Календарь")
        for w in (self.next_btn, self.month_lbl, self.prev_btn):
            w.pack_forget()
        if not is_open:
            return
        self.next_btn.pack(side="right")
        self.month_lbl.pack(side="right")
        self.prev_btn.pack(side="right")

        m, today = self.view_month, date.today()
        self.month_lbl.config(text=f"{MONTHS_NOM[m.month - 1]} {m.year}")
        for i, wd in enumerate(WD_SHORT):
            tk.Label(self.cal_frame, text=wd, font=self.f["pill"], fg=MUTED, bg=PAPER,
                     width=4).grid(row=0, column=i)
        busy = {x["start"].date() for x in self.tasks + self.events if self.passes_filter(x) and not x["done"]}
        for r, week in enumerate(calendar.Calendar().monthdatescalendar(m.year, m.month), 1):
            for c, d in enumerate(week):
                bg, fg, font = PAPER, TEXT if d.month == m.month else FAINT, self.f["small"]
                if d in busy:
                    bg = BUSY_BG
                if d == today:
                    fg, font = ACCENT, self.f["small_b"]
                if d == self.selected_day:
                    bg, fg = SELECT_BG, ACCENT
                lbl = tk.Label(self.cal_frame, text=d.day, width=4, bg=bg, fg=fg, font=font, cursor="hand2")
                lbl.grid(row=r, column=c, padx=1, pady=1)
                lbl.bind("<Button-1>", lambda e, d=d: self.select_day(d))


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp text on scaled displays
    except Exception:
        pass
    NotionWidget(load_json(CONFIG_PATH)).mainloop()


if __name__ == "__main__":
    main()
