"""
Parse quick-add text like "созвон завтра 15:00" into (title, date | datetime).
Understands: сегодня / завтра / послезавтра, weekdays (пн, в среду...),
dates 12.11 or 12.11.2026, times 15:00 or "в 15".
"""
import re
from datetime import date, datetime, timedelta

RELATIVE = {"сегодня": 0, "завтра": 1, "послезавтра": 2}
WEEKDAYS = {
    "пн": 0, "понедельник": 0, "вт": 1, "вторник": 1, "ср": 2, "среда": 2, "среду": 2,
    "чт": 3, "четверг": 3, "пт": 4, "пятница": 4, "пятницу": 4,
    "сб": 5, "суббота": 5, "субботу": 5, "вс": 6, "воскресенье": 6,
}
W = r"(?<!\S)"  # word start
E = r"(?!\S)"   # word end


def parse(text, today=None):
    today = today or date.today()
    s = f" {text.strip()} "
    day, hour, minute = None, None, 0

    def take(pattern):
        nonlocal s
        m = re.search(pattern, s, re.IGNORECASE)
        if m:
            s = s[:m.start()] + " " + s[m.end():]
        return m

    if m := take(W + r"(?:в\s+)?(\d{1,2}):(\d{2})" + E):
        hour, minute = int(m[1]), int(m[2])

    if m := take(W + r"(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?" + E):
        year = int(m[3]) if m[3] else today.year
        year += 2000 if year < 100 else 0
        try:
            day = date(year, int(m[2]), int(m[1]))
        except ValueError:
            raise ValueError("непонятная дата") from None
        if not m[3] and day < today:
            day = day.replace(year=day.year + 1)
    elif m := take(W + "(" + "|".join(RELATIVE) + ")" + E):
        day = today + timedelta(days=RELATIVE[m[1].lower()])
    elif m := take(W + r"(?:во?\s+)?(" + "|".join(sorted(WEEKDAYS, key=len, reverse=True)) + ")" + E):
        day = today + timedelta(days=(WEEKDAYS[m[1].lower()] - today.weekday()) % 7)

    if hour is None and (m := take(W + r"в\s+(\d{1,2})" + E)):
        hour = int(m[1])

    title = re.sub(r"\s+", " ", s).strip()
    if not title:
        raise ValueError("нет названия задачи")
    day = day or today
    if hour is None:
        return title, day
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError("непонятное время")
    return title, datetime(day.year, day.month, day.day, hour, minute)
