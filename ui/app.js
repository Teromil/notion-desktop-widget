"use strict";

const $ = (id) => document.getElementById(id);
const api = () => window.pywebview.api;

// Inline icons (stroke follows the text color)
const svg = (body, fill = false) =>
  `<svg viewBox="0 0 24 24" fill="${fill ? "currentColor" : "none"}" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;
const ICONS = {
  sparkle: svg('<path d="M12 3l1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4z"/><path d="M19 16l.6 1.7 1.7.6-1.7.6-.6 1.7-.6-1.7-1.7-.6 1.7-.6z"/>'),
  pin: svg('<path d="M12 17v5"/><path d="M9 10.8a2 2 0 0 1-1.1 1.8l-1.8.9A2 2 0 0 0 5 15.2V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.8a2 2 0 0 0-1.1-1.8l-1.8-.9a2 2 0 0 1-1.1-1.8V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/>'),
  refresh: svg('<path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/>'),
  minus: svg('<path d="M5 12h14"/>'),
  check: svg('<path d="M20 6 9 17l-5-5"/>'),
  plus: svg('<path d="M12 5v14M5 12h14"/>'),
  left: svg('<path d="m15 18-6-6 6-6"/>'),
  right: svg('<path d="m9 18 6-6-6-6"/>'),
  down: svg('<path d="m6 9 6 6 6-6"/>'),
  send: svg('<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>'),
  play: svg('<path d="M7 4v16l13-8z"/>', true),
  pause: svg('<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>', true),
  prev: svg('<path d="M19 20 9 12l10-8z"/><path d="M5 19V5"/>', true),
  next: svg('<path d="m5 4 10 8-10 8z"/><path d="M19 5v14"/>', true),
  volume: svg('<path d="M11 5 6 9H2v6h4l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/>'),
  music: svg('<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>'),
  claude: svg('<path d="M12 3v18M3 12h18M5.6 5.6l12.8 12.8M18.4 5.6 5.6 18.4"/>'),
  gear: svg('<path d="M12.2 2h-.4a2 2 0 0 0-2 2v.2a2 2 0 0 1-1 1.7l-.4.3a2 2 0 0 1-2 0l-.2-.1a2 2 0 0 0-2.7.7l-.2.4a2 2 0 0 0 .7 2.7l.2.1a2 2 0 0 1 1 1.7v.6a2 2 0 0 1-1 1.7l-.2.1a2 2 0 0 0-.7 2.7l.2.4a2 2 0 0 0 2.7.7l.2-.1a2 2 0 0 1 2 0l.4.3a2 2 0 0 1 1 1.7v.2a2 2 0 0 0 2 2h.4a2 2 0 0 0 2-2v-.2a2 2 0 0 1 1-1.7l.4-.3a2 2 0 0 1 2 0l.2.1a2 2 0 0 0 2.7-.7l.2-.4a2 2 0 0 0-.7-2.7l-.2-.1a2 2 0 0 1-1-1.7v-.6a2 2 0 0 1 1-1.7l.2-.1a2 2 0 0 0 .7-2.7l-.2-.4a2 2 0 0 0-2.7-.7l-.2.1a2 2 0 0 1-2 0l-.4-.3a2 2 0 0 1-1-1.7V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>'),
};

// Settings form: dotted keys map into config.json ("gemini.api_key" -> config.gemini.api_key)
const SETTINGS = [
  { group: "Notion", fields: [
    { key: "token", label: "Токен интеграции", type: "secret", hint: "ntn_…" },
    { key: "database_id", label: "База задач", hint: "Ссылка на базу или её ID" },
    { row: [{ key: "date_property", label: "Свойство даты" }, { key: "tag_property", label: "Свойство тегов" }] },
    { row: [{ key: "done_property", label: "Свойство статуса" }, { key: "done_value", label: "«Готово»" }] },
    { key: "todo_value", label: "Значение «не начато»" },
  ] },
  { group: "ИИ-помощник", fields: [
    { key: "ai_provider", label: "Кто отвечает", type: "select", options: [["gemini", "Gemini (бесплатно)"], ["claude", "Claude"]], def: "claude" },
    { key: "gemini.api_key", label: "Ключ Gemini", type: "secret", hint: "aistudio.google.com → Get API key" },
    { key: "gemini.model", label: "Модель Gemini", def: "gemini-flash-latest" },
    { key: "claude.api_key", label: "Ключ Claude", type: "secret", hint: "platform.claude.com → API keys" },
    { key: "claude.model", label: "Модель Claude", def: "claude-opus-5-5" },
  ] },
  { group: "Google Календарь", fields: [
    { key: "ical_urls", label: "Ссылки iCal, по одной в строке", type: "lines", hint: "Настройки календаря → Секретный адрес в формате iCal" },
  ] },
  { group: "Виджет", fields: [
    { type: "theme" },
    { row: [{ key: "hotkey", label: "Горячая клавиша", def: "ctrl+alt+n" }, { key: "notify_minutes", label: "Напомнить за, мин", type: "number", def: 10 }] },
    { key: "refresh_minutes", label: "Обновлять задачи каждые, мин", type: "number", def: 5 },
    { key: "stats", label: "Нагрузка ЦП / ГП / ОЗУ", type: "bool", def: true },
    { key: "claude_limits", label: "Лимиты Claude и кнопка Claude", type: "bool", def: true },
    { key: "claude_refresh_minutes", label: "Лимиты Claude: обновлять каждые, мин, пока Claude открыт (0 — выкл.)", type: "number", def: 60 },
    { key: "spotify", label: "Панель Spotify", type: "bool", def: true },
    { key: "open_in_app", label: "Открывать задачи в приложении Notion", type: "bool", def: true },
  ] },
];

const WEEKDAYS = ["Воскресенье", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"];
const WD = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
const MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];

const state = {
  settings: null,
  tasks: [], overdue: [], events: [],
  status: "",
  viewMonth: firstOfMonth(new Date()),
  selected: startOfDay(new Date()),
  spotify: null,
  cover: null,
  chatBusy: false, answerEl: null, answerText: "",
  volDragging: false,
  message: "", messageErr: false, messageTimer: null,
};

// ---------------------------------------------------------------- helpers
function startOfDay(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()); }
function firstOfMonth(d) { return new Date(d.getFullYear(), d.getMonth(), 1); }
function addDays(d, n) { return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n); }
function dayKey(d) { return d.getFullYear() * 10000 + (d.getMonth() + 1) * 100 + d.getDate(); }
function pad(n) { return String(n).padStart(2, "0"); }
function hhmm(d) { return `${pad(d.getHours())}:${pad(d.getMinutes())}`; }
function ddmm(d) { return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}`; }
function isoDate(d) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
function wdShort(d) { return WD[(d.getDay() + 6) % 7]; }
function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function pluralTasks(n) {
  if (n % 10 === 1 && n % 100 !== 11) return "задача";
  if (n % 10 >= 2 && n % 10 <= 4 && !(n % 100 >= 12 && n % 100 <= 14)) return "задачи";
  return "задач";
}
function prefs() { return state.settings ? state.settings.prefs : {}; }
function setPref(key, value) {
  prefs()[key] = value;
  api().save_pref(key, value);
}
function withDate(item) { item._d = new Date(item.start); return item; }

function passes(item) {
  const tag = prefs().tag_filter;
  return !tag || item.tags.some(([name]) => name === tag);
}
function itemsOn(day) {
  const k = dayKey(day);
  return [...state.tasks, ...state.events]
    .filter((x) => dayKey(x._d) === k && passes(x))
    .sort((a, b) => (a.done - b.done) || ((!a.has_time) - (!b.has_time)) || (a._d - b._d));
}

function flash(text, isError = false) {
  state.message = text;
  state.messageErr = isError;
  clearTimeout(state.messageTimer);
  state.messageTimer = setTimeout(() => { state.message = ""; renderStatus(); }, 5000);
  renderStatus();
}

// ---------------------------------------------------------------- rendering
function render() {
  renderSubline();
  renderOverdue();
  renderChips();
  renderList();
  renderUpcoming();
  renderCalendar();
  renderStatus();
  layout();
}

// ---------------------------------------------------------------- size-dependent layout
// When the window is smaller than the content, these blocks are hidden in this order (least important first).
// The task list itself always stays and scrolls.
const FIT_ORDER = ["player", "calendar-sec", "upcoming", "stats", "claude-row", "chips", "overdue", "quick-wrap"];
const WIDE_FROM = 560, NARROW_BELOW = 300;

function manualSize() {
  return !!prefs().size && !prefs().mini && $("settings").hidden;
}

function layout() {
  const root = $("root");
  root.classList.toggle("wide", window.innerWidth >= WIDE_FROM);
  root.classList.toggle("narrow", window.innerWidth < NARROW_BELOW);
  for (const id of FIT_ORDER) $(id).classList.remove("fit-hidden");
  root.classList.remove("fixed");
  document.documentElement.classList.remove("fixed");
  if (!manualSize()) return;  // auto size: the window grows to fit everything

  // Measure the natural layout with the list cut to a few rows, hide blocks until it fits
  root.classList.add("measuring");
  for (const id of FIT_ORDER) {
    if (root.offsetHeight <= window.innerHeight) break;
    $(id).classList.add("fit-hidden");
  }
  root.classList.remove("measuring");
  root.classList.add("fixed");
  document.documentElement.classList.add("fixed");
}

function renderClock() {
  const now = new Date();
  $("day").textContent = WEEKDAYS[now.getDay()];
  $("clock").textContent = hhmm(now);
}

function renderSubline() {
  const now = new Date();
  const date = `${now.getDate()} ${MONTHS_GEN[now.getMonth()]} ${now.getFullYear()}`;
  if (!prefs().mini) {
    $("subline").textContent = date;
    return;
  }
  const next = itemsOn(now).find((t) => !t.done && t.has_time && t._d >= now);
  $("subline").innerHTML = next
    ? `Дальше: <b>${hhmm(next._d)}</b> ${esc(next.title)}`
    : `${date} · на сегодня всё`;
}

const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
function applyTheme() {
  const pref = prefs().theme || "auto";
  const dark = pref === "dark" || (pref === "auto" && darkQuery.matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

function renderStats(s) {
  const rows = [
    ["st-cpu", s.cpu, "Процессор"],
    ["st-gpu", s.gpu, "Видеокарта (самая загруженная)"],
    ["st-ram", s.ram, `Память: ${s.ram_used} из ${s.ram_total} ГБ`],
  ];
  for (const [id, value, title] of rows) {
    const el = $(id);
    el.title = title;
    el.querySelector("b").textContent = value == null ? "–" : `${value}%`;
    el.querySelector("i").style.width = `${value || 0}%`;
    el.classList.toggle("warn", value >= 70 && value < 90);
    el.classList.toggle("hot", value >= 90);
  }
}

function ageText(savedAt) {
  if (state.claudeBusy) return "обновляю…";
  if (!savedAt) return "";
  const min = Math.round((Date.now() / 1000 - savedAt) / 60);
  const when = min < 1 ? "только что" : min < 60 ? `${min} мин назад`
    : min < 24 * 60 ? `${Math.floor(min / 60)} ч назад` : `${Math.floor(min / 1440)} дн назад`;
  return `обновлено ${when}`;
}

function renderClaude(limits = state.claude) {
  state.claude = limits;
  const box = $("claude-limits");
  box.title = "Нажми, чтобы обновить";
  if (!limits || (!limits.five_hour && !limits.seven_day)) {
    box.innerHTML = `<span class="claude-empty">${state.claudeBusy ? "Получаю лимиты…" : "Нажми, чтобы получить лимиты Claude"}</span>`;
    return;
  }
  const now = new Date();
  const resetText = (ts) => {
    if (!ts) return "сброшен";
    const d = new Date(ts * 1000);
    return dayKey(d) === dayKey(now) ? `сброс в ${hhmm(d)}` : `сброс ${wdShort(d).toLowerCase()} ${hhmm(d)}`;
  };
  const item = (label, w) => {
    if (!w) return "";
    const left = Math.max(0, 100 - w.pct);
    return `<div class="lim${w.pct >= 85 ? " hot" : ""}" title="Использовано ${w.pct}%">`
      + `<div class="stat-top"><span>${label}</span><b>осталось ${left}%</b></div>`
      + `<div class="stat-bar"><i style="width:${w.pct}%"></i></div>`
      + `<div class="lim-reset">${resetText(w.resets_at)}</div></div>`;
  };
  box.innerHTML = item("5 ч", limits.five_hour) + item("Неделя", limits.seven_day)
    + `<div class="lim-age">${ageText(limits.saved_at)}</div>`;
}

function renderButtons() {
  applyTheme();
  $("stats").hidden = !state.settings.stats;
  $("claude-row").hidden = !state.settings.claude_limits;
  $("btn-pin").classList.toggle("on", !!prefs().always_on_top);
  $("btn-ask").classList.toggle("on", !!prefs().ask_open);
  $("ask").hidden = !prefs().ask_open;
  $("ask-title").innerHTML = `${ICONS.sparkle}Спросить ${esc(state.settings.ai_name)}`;
  document.getElementById("root").classList.toggle("mini", !!prefs().mini);
  const hk = state.settings.hotkey;
  $("btn-hide").title = hk ? `Скрыть (${hk.replace(/\b\w/g, (c) => c.toUpperCase())})` : "Скрыть";
  layout();
}

function taskRow(t, overdue = false) {
  const isEvent = t.source === "gcal";
  const checkable = !isEvent && state.settings.can_check;
  const lead = isEvent
    ? '<span class="gcal-bar"></span>'
    : checkable
      ? `<button class="check" data-action="check" data-id="${esc(t.id)}">${ICONS.check}</button>`
      : '<span class="check static"></span>';

  const now = new Date();
  let pill = "", red = false;
  if (overdue) {
    pill = t.has_time ? `${ddmm(t._d)} ${hhmm(t._d)}` : ddmm(t._d);
    red = true;
  } else if (t.has_time) {
    pill = hhmm(t._d);
    red = !isEvent && !t.done && dayKey(t._d) === dayKey(now) && t._d < now;  // time already passed
  }
  const color = isEvent ? "purple" : (t.tags[0] ? t.tags[0][1] : "blue");
  const title = t.url
    ? `<span class="task-title link" data-action="open" data-url="${esc(t.url)}">${esc(t.title)}</span>`
    : `<span class="task-title">${esc(t.title)}</span>`;
  return `<li class="task${t.done ? " done" : ""}">${lead}${title}`
    + (pill ? `<span class="pill c-${esc(color)}${red ? " red" : ""}">${pill}</span>` : "")
    + "</li>";
}

function renderOverdue() {
  const items = state.overdue.filter((t) => !t.done && passes(t));
  $("overdue").innerHTML = items.length
    ? `<div class="section-title red">Просрочено · ${items.length}</div><ul class="tasks">${items.slice(0, 5).map((t) => taskRow(t, true)).join("")}</ul>`
    : "";
  $("overdue").hidden = !items.length;
}

function renderChips() {
  const tags = new Map();
  for (const t of [...state.tasks, ...state.overdue]) for (const [name, color] of t.tags) if (!tags.has(name)) tags.set(name, color);
  if (!tags.size) { $("chips").innerHTML = ""; return; }
  const current = prefs().tag_filter || null;
  const chip = (label, value, color) =>
    `<button class="chip c-${esc(color)}${value === current ? " on" : ""}" data-action="chip" data-value="${esc(value || "")}">${esc(label)}</button>`;
  $("chips").innerHTML = chip("Все", null, "default")
    + [...tags].sort((a, b) => a[0].localeCompare(b[0], "ru")).map(([n, c]) => chip(n, n, c)).join("");
}

function renderList() {
  const d = state.selected;
  const isToday = dayKey(d) === dayKey(new Date());
  $("list-title").textContent = isToday ? "Сегодня" : `${wdShort(d)}, ${d.getDate()} ${MONTHS_GEN[d.getMonth()]}`;
  const items = itemsOn(d);
  $("list").innerHTML = items.length ? items.map((t) => taskRow(t)).join("") : '<li class="empty">Задач нет</li>';
}

function renderUpcoming() {
  const today = startOfDay(new Date());
  const rows = [];
  for (let i = 1; i <= 7 && rows.length < 4; i++) {
    const d = addDays(today, i);
    const items = itemsOn(d).filter((x) => !x.done);
    if (!items.length) continue;
    const what = items.length === 1 ? items[0].title : `${items.length} ${pluralTasks(items.length)}`;
    rows.push(`<div class="up-row" data-action="day" data-date="${isoDate(d)}"><span class="up-day">${wdShort(d)} ${d.getDate()}</span><span class="up-what">${esc(what)}</span></div>`);
  }
  $("upcoming").innerHTML = rows.length ? rows.join("") : '<div class="up-row">На неделе пусто</div>';
}

function renderCalendar() {
  const open = prefs().calendar_open !== false;
  $("cal-chevron").innerHTML = ICONS.down;
  document.querySelector(".section-toggle").classList.toggle("closed", !open);
  $("cal-nav").hidden = !open;
  $("cal").hidden = !open;
  if (!open) return;

  const m = state.viewMonth;
  $("month").textContent = `${MONTHS[m.getMonth()]} ${m.getFullYear()}`;
  const busy = new Set([...state.tasks, ...state.events].filter((x) => !x.done && passes(x)).map((x) => dayKey(x._d)));
  const offset = (m.getDay() + 6) % 7;
  const daysInMonth = new Date(m.getFullYear(), m.getMonth() + 1, 0).getDate();
  const cells = Math.ceil((offset + daysInMonth) / 7) * 7;
  const todayK = dayKey(new Date()), selK = dayKey(state.selected);

  let html = WD.map((w) => `<div class="cal-wd">${w}</div>`).join("");
  for (let i = 0; i < cells; i++) {
    const d = addDays(m, i - offset);
    const k = dayKey(d);
    const cls = ["cal-day",
      d.getMonth() !== m.getMonth() && "other",
      k === todayK && "today",
      k === selK && "selected",
      busy.has(k) && "busy"].filter(Boolean).join(" ");
    html += `<button class="${cls}" data-action="day" data-date="${isoDate(d)}">${d.getDate()}</button>`;
  }
  $("cal").innerHTML = html;
}

function renderStatus() {
  const el = $("status");
  const text = state.message || state.status;
  const isError = state.message ? state.messageErr : (!!state.status && !state.status.startsWith("демо"));
  el.textContent = text;
  el.classList.toggle("err", isError);
}

function renderSpotify() {
  const p = $("player");
  p.hidden = !state.settings.spotify;
  if (p.hidden) return;
  const st = state.spotify;
  const running = st && st.running;
  $("player-title").textContent = running ? (st.title || st.track || "Spotify") : "Spotify не запущен";
  $("player-artist").textContent = running ? (st.artist || "") : "нажми, чтобы открыть";
  p.classList.toggle("paused", !running || !st.playing);

  const art = running && state.cover && state.cover.track === st.track ? state.cover.url : null;
  $("cover").style.backgroundImage = art ? `url("${art}")` : "";
  $("cover").classList.toggle("has-art", !!art);
  $("sp-play").innerHTML = running && st.playing ? ICONS.pause : ICONS.play;

  const hasVolume = state.settings.spotify_volume && running && st.volume != null;
  $("volume").hidden = $("vol-icon").hidden = !hasVolume;
  if (hasVolume && !state.volDragging) setVolumeUI(st.volume);
  renderProgress();

  // The state arrives every 2 s (position changes); re-layout only when the player's height can change
  const shape = `${running}|${!$("sp-progress").hidden}|${hasVolume}|${!!art}`;
  if (shape !== state.playerShape && !p.classList.contains("fit-hidden")) layout();
  state.playerShape = shape;
}

function fmtTime(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${pad(s % 60)}`;
}

function currentPosition() {
  const st = state.spotify;
  let pos = st.position;
  if (st.playing) pos += (Date.now() - st._received) / 1000;  // advance between updates from Python
  return Math.min(pos, st.duration);
}

function renderProgress() {
  const st = state.spotify;
  const show = !!(st && st.running && st.can_seek);
  $("sp-progress").hidden = !show;
  if (!show || state.seekDragging) return;
  const pos = currentPosition();
  const r = $("seek");
  r.max = Math.max(1, Math.round(st.duration));
  r.value = Math.round(pos);
  r.style.setProperty("--fill", `${(pos / st.duration) * 100}%`);
  $("sp-pos").textContent = fmtTime(pos);
  $("sp-dur").textContent = fmtTime(st.duration);
}

function setVolumeUI(v) {
  const r = $("volume");
  r.value = v;
  r.style.setProperty("--fill", `${v}%`);
}

// ---------------------------------------------------------------- actions
function toggleDone(id) {
  const items = [...state.tasks, ...state.overdue].filter((t) => t.id === id);
  if (!items.length) return;
  const done = !items[0].done;
  items.forEach((t) => { t.done = done; });
  render();
  api().toggle_done(id, done).then((res) => {
    if (res.ok) return;
    items.forEach((t) => { t.done = !done; });
    render();
    flash(res.error, true);
  });
}

function selectDay(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  state.selected = new Date(y, m - 1, d);
  const month = firstOfMonth(state.selected);
  if (month.getTime() !== state.viewMonth.getTime()) {
    state.viewMonth = month;
    api().set_month(isoDate(month));
  }
  render();
}

function shiftMonth(delta) {
  state.viewMonth = new Date(state.viewMonth.getFullYear(), state.viewMonth.getMonth() + delta, 1);
  renderCalendar();
  api().set_month(isoDate(state.viewMonth));
}

function md(src) {
  // Minimal, safe Markdown: **bold**, *italic*, `code`, bullet and numbered lists
  const inline = (s) => s
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<i>$2</i>");
  let html = "", list = null;
  const close = () => { const s = list ? `</${list}>` : ""; list = null; return s; };
  for (const line of esc(src).split("\n")) {
    let m;
    if ((m = line.match(/^\s*[-*•]\s+(.*)/))) {
      if (list !== "ul") html += close() + "<ul>", list = "ul";
      html += `<li>${inline(m[1])}</li>`;
    } else if ((m = line.match(/^\s*\d+[.)]\s+(.*)/))) {
      if (list !== "ol") html += close() + "<ol>", list = "ol";
      html += `<li>${inline(m[1])}</li>`;
    } else {
      html += close();
      if (line.trim()) html += `<div>${inline(line.replace(/^#+\s*/, ""))}</div>`;
    }
  }
  return html + close();
}

function sendQuestion() {
  const ta = $("ask-text");
  const q = ta.value.trim();
  if (!q || state.chatBusy) return;
  ta.value = "";
  autosize(ta);
  const log = $("ask-log");
  log.insertAdjacentHTML("beforeend", `<div class="msg-q">${esc(q)}</div>`);
  const a = document.createElement("div");
  a.className = "msg-a typing";
  log.appendChild(a);
  log.scrollTop = log.scrollHeight;
  Object.assign(state, { answerEl: a, answerText: "", chatBusy: true });
  $("ask-send").disabled = true;
  api().ask(q).then((res) => { if (!res.ok) finishAnswer(res.error); });
}

function onChat(d) {
  const a = state.answerEl;
  if (!a) return;
  if (d.chunk) {
    state.answerText += d.chunk;
    a.innerHTML = md(state.answerText);
    const log = $("ask-log");
    log.scrollTop = log.scrollHeight;
  }
  if (d.done) finishAnswer();
  if (d.error) finishAnswer(d.error);
}

function finishAnswer(error) {
  const a = state.answerEl;
  if (!a) return;
  a.classList.remove("typing");
  if (error) {
    if (state.answerText) a.insertAdjacentHTML("beforeend", `<div class="err">${esc(error)}</div>`);
    else { a.classList.add("err"); a.textContent = error; }
  }
  Object.assign(state, { answerEl: null, chatBusy: false });
  $("ask-send").disabled = false;
}

function autosize(ta) {
  ta.style.height = "auto";
  ta.style.height = `${ta.scrollHeight}px`;
}

// ---------------------------------------------------------------- settings
function getPath(obj, dotted) {
  return dotted.split(".").reduce((o, k) => (o && typeof o === "object" ? o[k] : undefined), obj);
}

function fieldHtml(f, cfg, saved) {
  let value = getPath(cfg, f.key);
  if (value === undefined || value === null) value = f.def ?? "";
  const label = `<span>${esc(f.label)}</span>`;
  const hint = f.hint && f.type !== "secret" ? `<small>${esc(f.hint)}</small>` : "";
  const data = `data-key="${esc(f.key)}" data-type="${f.type || "text"}"`;
  switch (f.type) {
    case "secret": {
      const ph = saved[f.key] ? "сохранён — оставь пустым, чтобы не менять" : f.hint;
      return `<label class="field">${label}<input type="password" ${data} placeholder="${esc(ph)}"></label>`;
    }
    case "select":
      return `<label class="field">${label}<select ${data}>${f.options.map(([v, t]) =>
        `<option value="${esc(v)}"${v === value ? " selected" : ""}>${esc(t)}</option>`).join("")}</select></label>`;
    case "lines":
      return `<label class="field">${label}<textarea ${data} rows="2">${esc((value || []).join("\n"))}</textarea>${hint}</label>`;
    case "bool":
      return `<label class="toggle"><span>${esc(f.label)}</span><input type="checkbox" ${data}${value ? " checked" : ""}><i></i></label>`;
    case "number":
      return `<label class="field">${label}<input type="number" min="0" ${data} value="${esc(value)}"></label>`;
    default:
      return `<label class="field">${label}<input type="text" ${data} value="${esc(value)}" placeholder="${esc(f.hint || "")}"></label>`;
  }
}

function themeHtml() {
  const current = prefs().theme || "auto";
  const opts = [["auto", "Как в Windows"], ["light", "Светлая"], ["dark", "Тёмная"]];
  return '<div class="field"><span>Тема</span><div class="seg">'
    + opts.map(([v, t]) => `<button type="button" data-action="theme" data-value="${v}" class="${v === current ? "on" : ""}">${t}</button>`).join("")
    + "</div></div>";
}

async function openSettings() {
  const { config, secrets_saved: saved } = await api().get_config();
  $("settings-form").innerHTML = SETTINGS.map((g) =>
    `<div class="set-group"><div class="set-group-title">${esc(g.group)}</div>`
    + g.fields.map((f) => f.type === "theme" ? themeHtml()
      : f.row ? `<div class="field-row">${f.row.map((x) => fieldHtml(x, config, saved)).join("")}</div>`
      : fieldHtml(f, config, saved)).join("")
    + "</div>").join("");
  $("settings-error").textContent = "";
  $("settings").hidden = false;
  $("root").classList.add("settings-open");
  layout();  // the settings panel always uses auto height; the chosen size comes back on close
}

function closeSettings() {
  $("settings").hidden = true;
  $("root").classList.remove("settings-open");
  if (prefs().size) api().restore_size();
  layout();
}

function saveSettings() {
  const values = {};
  for (const el of $("settings-form").querySelectorAll("[data-key]")) {
    const type = el.dataset.type;
    values[el.dataset.key] = type === "bool" ? el.checked
      : type === "number" ? Number(el.value)
      : type === "lines" ? el.value.split("\n").map((s) => s.trim()).filter(Boolean)
      : el.value;
  }
  $("settings-error").textContent = "";
  api().save_config(values).then((res) => {
    if (!res.ok) { $("settings-error").textContent = res.error; return; }
    $("settings-error").textContent = "";
    document.querySelector(".settings-actions .primary").textContent = "Перезапуск…";
  });
}

const actions = {
  "toggle-ask": () => {
    setPref("ask_open", !prefs().ask_open);
    renderButtons();
    if (prefs().ask_open) $("ask-text").focus();
  },
  "toggle-pin": () => api().toggle_topmost().then((on) => { prefs().always_on_top = on; renderButtons(); }),
  refresh: (el) => {
    el.classList.remove("spin");
    void el.offsetWidth;  // restart the animation
    el.classList.add("spin");
    api().refresh();
  },
  hide: () => api().hide(),
  "new-chat": () => { $("ask-log").innerHTML = ""; api().new_chat(); finishAnswer(); },
  send: sendQuestion,
  check: (el) => toggleDone(el.dataset.id),
  open: (el) => api().open_url(el.dataset.url),
  chip: (el) => { setPref("tag_filter", el.dataset.value || null); render(); },
  day: (el) => el.dataset.date && selectDay(el.dataset.date),
  "toggle-cal": () => { setPref("calendar_open", prefs().calendar_open === false); renderCalendar(); layout(); },
  "prev-month": () => shiftMonth(-1),
  "next-month": () => shiftMonth(1),
  "spotify-open": () => api().spotify_open(),
  "sp-previous": () => api().spotify("previous"),
  "sp-play_pause": () => api().spotify("play_pause"),
  "sp-next": () => api().spotify("next"),
  "open-claude": () => api().open_claude(),
  "refresh-claude": () => { if (!state.claudeBusy) api().refresh_claude(); },
  "open-settings": openSettings,
  "close-settings": closeSettings,
  "save-settings": saveSettings,
  theme: (el) => {
    setPref("theme", el.dataset.value);  // applies right away, no restart
    applyTheme();
    for (const b of el.parentNode.children) b.classList.toggle("on", b === el);
  },
};

// ---------------------------------------------------------------- events from Python
window.app = {
  on(event, data) {
    if (!state.settings && event !== "settings") return;  // init() hasn't returned yet; it brings fresh state
    if (event === "data") applySnapshot(data);
    else if (event === "settings") { state.settings = data; renderButtons(); }
    else if (event === "spotify") { state.spotify = withReceived(data); renderSpotify(); }
    else if (event === "cover") { state.cover = data; renderSpotify(); }
    else if (event === "stats") renderStats(data);
    else if (event === "claude") { renderClaude(data); layout(); }
    else if (event === "claude_busy") { state.claudeBusy = data; renderClaude(); }
    else if (event === "chat") onChat(data);
  },
};

function withReceived(st) {
  if (st) st._received = Date.now();
  return st;
}

function applySnapshot(d) {
  state.tasks = d.tasks.map(withDate);
  state.overdue = d.overdue.map(withDate);
  state.events = d.events.map(withDate);
  state.status = d.status;
  render();
}

// ---------------------------------------------------------------- setup
function setupIcons() {
  const set = (id, icon) => { $(id).innerHTML = ICONS[icon]; };
  set("btn-ask", "sparkle"); set("btn-pin", "pin"); set("btn-refresh", "refresh"); set("btn-hide", "minus");
  set("btn-settings", "gear"); set("claude-btn", "claude");
  set("btn-prev", "left"); set("btn-next", "right"); set("ask-send", "send"); set("quick-icon", "plus");
  set("sp-prev", "prev"); set("sp-next", "next"); set("vol-icon", "volume"); set("player-icon", "music");
}

function setupEvents() {
  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-action]");
    if (el && actions[el.dataset.action]) actions[el.dataset.action](el);
  });
  // Drag the window by the header. Done by hand (Python moves the window to follow the cursor)
  // instead of Windows' drag loop, which swallows the second click of a double click.
  const head = $("head");
  let drag = null, moveQueued = false;
  head.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || e.target.closest("button")) return;
    drag = { x: e.screenX, y: e.screenY, moving: false };
    head.setPointerCapture(e.pointerId);
    api().drag_start();
  });
  head.addEventListener("pointermove", (e) => {
    if (!drag) return;
    if (!drag.moving && Math.hypot(e.screenX - drag.x, e.screenY - drag.y) < 4) return;  // still a click
    drag.moving = true;
    if (moveQueued) return;
    moveQueued = true;
    requestAnimationFrame(() => { moveQueued = false; api().drag_move(); });
  });
  const endDrag = () => {
    if (drag && drag.moving) api().drag_move();  // land exactly where the cursor was released
    drag = null;
  };
  head.addEventListener("pointerup", endDrag);
  head.addEventListener("pointercancel", endDrag);

  // Double click on the header toggles mini mode
  head.addEventListener("dblclick", (e) => {
    if (e.target.closest("button")) return;
    setPref("mini", !prefs().mini);
    if (!prefs().mini && prefs().size) api().restore_size();  // back from mini: the size the user chose
    renderButtons();
    renderSubline();
  });

  // Resize grip (bottom-right corner): Python follows the cursor; double click = back to auto size
  const grip = $("grip");
  let resizing = false, resizeQueued = false;
  grip.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    resizing = true;
    // Manual size from the first pixel, so auto-fit doesn't pull the height back while dragging
    if (!prefs().size) prefs().size = [window.innerWidth, window.innerHeight];
    grip.setPointerCapture(e.pointerId);
    api().resize_start();
  });
  grip.addEventListener("pointermove", () => {
    if (!resizing || resizeQueued) return;
    resizeQueued = true;
    requestAnimationFrame(() => { resizeQueued = false; api().resize_move(); });
  });
  const endResize = () => {
    if (!resizing) return;
    resizing = false;
    api().resize_move().then(() => api().resize_end());
    prefs().size = [window.innerWidth, window.innerHeight];  // Python saves the exact size
    layout();
  };
  grip.addEventListener("pointerup", endResize);
  grip.addEventListener("pointercancel", endResize);
  grip.addEventListener("dblclick", () => {
    prefs().size = null;
    api().reset_size();
    layout();
  });

  let layoutQueued = false;
  window.addEventListener("resize", () => {
    if (layoutQueued) return;
    layoutQueued = true;
    requestAnimationFrame(() => { layoutQueued = false; layout(); });
  });

  $("settings-form").addEventListener("submit", (e) => e.preventDefault());
  darkQuery.addEventListener("change", () => state.settings && applyTheme());

  const quick = $("quick");
  quick.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || !quick.value.trim()) return;
    quick.disabled = true;
    api().quick_add(quick.value.trim()).then((res) => {
      quick.disabled = false;
      if (res.ok) { quick.value = ""; flash(res.message); } else flash(res.error, true);
      quick.focus();
    });
  });

  const ta = $("ask-text");
  ta.addEventListener("input", () => autosize(ta));
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendQuestion(); }
  });

  // Seek bar: the label follows the drag; Spotify jumps on release
  const seek = $("seek");
  seek.addEventListener("pointerdown", () => { state.seekDragging = true; });
  seek.addEventListener("input", () => {
    $("sp-pos").textContent = fmtTime(seek.value);
    seek.style.setProperty("--fill", `${(seek.value / seek.max) * 100}%`);
  });
  seek.addEventListener("change", () => {
    const st = state.spotify;
    if (st) { st.position = Number(seek.value); st._received = Date.now(); }
    state.seekDragging = false;
    api().spotify_seek(Number(seek.value));
  });
  setInterval(() => { if (state.spotify && state.settings) renderProgress(); }, 500);

  const vol = $("volume");
  let lastSent = 0;
  vol.addEventListener("pointerdown", () => { state.volDragging = true; });
  vol.addEventListener("pointerup", () => { state.volDragging = false; api().set_volume(vol.value); });
  vol.addEventListener("input", () => {
    setVolumeUI(vol.value);
    if (Date.now() - lastSent > 80) { lastSent = Date.now(); api().set_volume(vol.value); }
  });

  // Auto size: fit the window height to the content (a size chosen with the grip is kept as is)
  let lastHeight = 0;
  new ResizeObserver(() => {
    if (!window.pywebview || !state.settings || manualSize()) return;
    const h = Math.ceil(document.getElementById("root").getBoundingClientRect().height * devicePixelRatio);
    if (h !== lastHeight) { lastHeight = h; api().resize(h); }
  }).observe(document.getElementById("root"));

  // Clock; every minute recolour passed tasks; at midnight move "today" and reload
  let lastMinute = -1, lastDay = dayKey(new Date());
  setInterval(() => {
    const now = new Date();
    renderClock();
    if (now.getMinutes() === lastMinute) return;
    lastMinute = now.getMinutes();
    if (dayKey(now) !== lastDay) {
      if (dayKey(state.selected) === lastDay) state.selected = startOfDay(now);
      lastDay = dayKey(now);
      api().refresh();
    }
    renderList();
    renderSubline();
    if (state.settings) renderClaude();  // keeps "обновлено N мин назад" current
  }, 1000);
}

window.addEventListener("pywebviewready", async () => {
  const init = await api().init();
  state.settings = init.settings;
  state.spotify = withReceived(init.spotify);
  state.cover = init.cover;
  renderClaude(init.claude);
  renderButtons();
  applySnapshot(init.data);
  renderSpotify();
});

setupIcons();
setupEvents();
renderClock();
