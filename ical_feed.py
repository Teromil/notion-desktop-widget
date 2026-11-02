"""
Read events from iCal feeds (Google Calendar "secret address in iCal format").
Supports common recurring rules: DAILY/WEEKLY(+BYDAY)/MONTHLY/YEARLY, INTERVAL, COUNT, UNTIL, EXDATE.
"""
import urllib.request
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo  # needs the `tzdata` package on Windows
except ImportError:
    ZoneInfo = None

WEEKDAY_CODES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def fetch_events(urls, start: date, end: date):
    window = (datetime.combine(start, datetime.min.time()), datetime.combine(end, datetime.min.time()))
    events = []
    for url in urls:
        if url.startswith("webcal://"):
            url = "https://" + url[len("webcal://"):]
        with urllib.request.urlopen(url, timeout=20) as resp:
            text = resp.read().decode("utf-8", "replace")
        events += parse_ics(text, *window)
    return events


def parse_ics(text, start: datetime, end: datetime):
    raw_events = _read_vevents(text)

    # Moved/edited instances of a series come as separate VEVENTs with RECURRENCE-ID:
    # exclude those slots from the master series.
    masters = {e.get("uid"): e for e in raw_events if "rrule" in e}
    for e in raw_events:
        if "recurrence_id" in e and e.get("uid") in masters:
            masters[e["uid"]]["exdates"].append(e["recurrence_id"])

    events = []
    for e in raw_events:
        if "start" not in e or e.get("status") == "CANCELLED":
            continue
        exdates = {_to_local(x) for x in e["exdates"]}
        for occ in _occurrences(e, start, end):
            local = _to_local(occ)
            if start <= local < end and local not in exdates:
                events.append({
                    "id": f"{e.get('uid', '')}|{local.isoformat()}",
                    "title": e.get("title", "(без названия)"),
                    "start": local,
                    "has_time": e["has_time"],
                    "done": False,
                    "tags": [],
                    "url": None,
                    "source": "gcal",
                })
    return events


def _read_vevents(text):
    lines = []
    for raw in text.splitlines():  # unfold continuation lines
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)

    events, cur, depth = [], None, 0
    for line in lines:
        if line == "BEGIN:VEVENT":
            cur, depth = {"exdates": []}, 0
        elif line == "END:VEVENT":
            events.append(cur)
            cur = None
        elif cur is None:
            continue
        elif line.startswith("BEGIN:"):  # nested VALARM etc.
            depth += 1
        elif line.startswith("END:"):
            depth -= 1
        elif depth == 0:
            name, params, value = _parse_line(line)
            if name == "SUMMARY":
                cur["title"] = _unescape(value)
            elif name == "DTSTART":
                cur["start"], cur["has_time"] = _parse_dt(value, params)
            elif name == "RRULE":
                cur["rrule"] = dict(p.split("=", 1) for p in value.split(";") if "=" in p)
            elif name == "EXDATE":
                cur["exdates"] += [_parse_dt(v, params)[0] for v in value.split(",")]
            elif name == "RECURRENCE-ID":
                cur["recurrence_id"] = _parse_dt(value, params)[0]
            elif name == "UID":
                cur["uid"] = value
            elif name == "STATUS":
                cur["status"] = value.upper()
    return events


def _parse_line(line):
    head, _, value = line.partition(":")
    name, *params = head.split(";")
    return name.upper(), dict(p.split("=", 1) for p in params if "=" in p), value


def _parse_dt(value, params):
    """Return (datetime, has_time). All-day dates become midnight datetimes."""
    value = value.strip()
    if params.get("VALUE") == "DATE" or len(value) == 8:
        return datetime.strptime(value[:8], "%Y%m%d"), False
    dt = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        dt = dt.replace(tzinfo=timezone.utc)
    elif "TZID" in params and ZoneInfo:
        try:
            dt = dt.replace(tzinfo=ZoneInfo(params["TZID"].strip('"')))
        except Exception:
            pass  # unknown zone: treat as local time
    return dt, True


def _to_local(dt):
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt


def _unescape(s):
    return s.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _occurrences(ev, window_start, window_end):
    """Yield occurrence starts (in the event's own timezone) up to window_end."""
    s = ev["start"]
    rule = ev.get("rrule")
    if not rule:
        yield s
        return

    freq = rule.get("FREQ")
    interval = int(rule.get("INTERVAL", 1))
    count = int(rule["COUNT"]) if "COUNT" in rule else None
    until = _to_local(_parse_dt(rule["UNTIL"], {})[0]) if "UNTIL" in rule else None
    byday = [d[-2:] for d in rule.get("BYDAY", "").split(",") if d[-2:] in WEEKDAY_CODES]

    # Skip far-past periods of long-running series (only safe without COUNT)
    i = 0
    if count is None and freq in ("DAILY", "WEEKLY"):
        step_days = interval * (1 if freq == "DAILY" else 7)
        i = max(0, (window_start - _to_local(s)).days // step_days - 1)

    n = 0
    for i in range(i, i + 3000):
        if freq == "DAILY":
            candidates = [s + timedelta(days=i * interval)]
        elif freq == "WEEKLY":
            week = s + timedelta(weeks=i * interval)
            if byday:
                monday = week - timedelta(days=week.weekday())
                candidates = sorted(monday + timedelta(days=WEEKDAY_CODES.index(d)) for d in byday)
                candidates = [c for c in candidates if c >= s]
            else:
                candidates = [week]
        elif freq in ("MONTHLY", "YEARLY"):
            months = i * interval * (12 if freq == "YEARLY" else 1)
            y, m = divmod(s.month - 1 + months, 12)
            try:
                candidates = [s.replace(year=s.year + y, month=m + 1)]
            except ValueError:  # e.g. 31st in a short month
                candidates = []
        else:
            yield s
            return

        for c in candidates:
            local = _to_local(c)
            if (until and local > until) or local >= window_end:
                return
            n += 1
            if count and n > count:
                return
            yield c
