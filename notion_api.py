"""Minimal Notion API client for the widget (standard library only)."""
import json
import urllib.error
import urllib.request
from datetime import date, datetime

API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionError(Exception):
    pass


class Notion:
    def __init__(self, cfg):
        self.token = cfg["token"]
        self.db = cfg["database_id"]
        self.date_prop = cfg.get("date_property", "Date")
        self.done_prop = cfg.get("done_property") or None
        self.done_value = cfg.get("done_value", "Done")
        self.todo_value = cfg.get("todo_value", "Not started")
        self.tag_prop = cfg.get("tag_property") or None
        self.extra_filter = cfg.get("extra_filter") or None
        self.schema = None
        self.title_prop = None

    def _req(self, method, path, body=None):
        req = urllib.request.Request(
            API + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            try:
                msg = json.load(e).get("message", "")
            except Exception:
                msg = ""
            raise NotionError(f"{e.code} {msg}") from None

    # --- schema
    def load_schema(self):
        if self.schema is not None:
            return
        props = self._req("GET", f"/databases/{self.db}")["properties"]
        schema = {name: p["type"] for name, p in props.items()}
        for name, key in ((self.date_prop, "date_property"), (self.done_prop, "done_property"),
                          (self.tag_prop, "tag_property")):
            if name and name not in schema:
                raise NotionError(f"в базе нет свойства «{name}» ({key}). Есть: {', '.join(schema)}")
        self.title_prop = next(n for n, t in schema.items() if t == "title")
        self.schema = schema

    @property
    def can_check(self):
        return bool(self.done_prop)

    # --- filters
    def _not_done_filter(self):
        kind = self.schema[self.done_prop]
        if kind == "checkbox":
            return {"property": self.done_prop, "checkbox": {"equals": False}}
        return {"property": self.done_prop, kind: {"does_not_equal": self.done_value}}

    def _query(self, conditions, limit=None):
        if self.extra_filter:
            conditions.append(self.extra_filter)
        body = {
            "filter": {"and": conditions},
            "sorts": [{"property": self.date_prop, "direction": "ascending"}],
            "page_size": min(limit or 100, 100),
        }
        tasks = []
        while True:
            data = self._req("POST", f"/databases/{self.db}/query", body)
            tasks += [t for t in map(self.parse_page, data["results"]) if t]
            if not data.get("has_more") or (limit and len(tasks) >= limit):
                return tasks
            body["start_cursor"] = data["next_cursor"]

    def query(self, start: date, end: date):
        """Tasks with a date in [start, end)."""
        self.load_schema()
        return self._query([
            {"property": self.date_prop, "date": {"on_or_after": start.isoformat()}},
            {"property": self.date_prop, "date": {"before": end.isoformat()}},
        ])

    def overdue(self):
        """Not-done tasks dated before today (needs done_property)."""
        self.load_schema()
        if not self.done_prop:
            return []
        return self._query([
            {"property": self.date_prop, "date": {"before": date.today().isoformat()}},
            self._not_done_filter(),
        ], limit=50)

    # --- parsing
    def parse_page(self, page):
        props = page["properties"]
        date_val = (props.get(self.date_prop) or {}).get("date")
        if not date_val or not date_val.get("start"):
            return None
        title = "".join(t["plain_text"] for t in props[self.title_prop]["title"])

        raw = date_val["start"]
        start = datetime.fromisoformat(raw)
        if start.tzinfo:
            start = start.astimezone().replace(tzinfo=None)  # to local time

        return {
            "id": page["id"],
            "title": title or "(без названия)",
            "start": start,
            "has_time": "T" in raw,
            "done": self._is_done(props),
            "tags": self._tags(props),
            "url": page.get("url"),
            "source": "notion",
        }

    def _is_done(self, props):
        if not self.done_prop:
            return False
        p = props.get(self.done_prop, {})
        kind = p.get("type")
        if kind == "checkbox":
            return p["checkbox"]
        return (p.get(kind) or {}).get("name") == self.done_value

    def _tags(self, props):
        if not self.tag_prop:
            return []
        p = props.get(self.tag_prop, {})
        kind = p.get("type")
        if kind == "multi_select":
            return [(o["name"], o["color"]) for o in p["multi_select"]]
        if kind in ("select", "status") and p.get(kind):
            return [(p[kind]["name"], p[kind]["color"])]
        return []

    # --- writes
    def set_done(self, page_id, done: bool):
        self.load_schema()
        kind = self.schema[self.done_prop]
        if kind == "checkbox":
            value = {"checkbox": done}
        else:
            value = {kind: {"name": self.done_value if done else self.todo_value}}
        self._req("PATCH", f"/pages/{page_id}", {"properties": {self.done_prop: value}})

    def create(self, title, when):
        """Create a task; `when` is a date (all-day) or a naive local datetime."""
        self.load_schema()
        start = when.astimezone().isoformat() if isinstance(when, datetime) else when.isoformat()
        page = self._req("POST", "/pages", {
            "parent": {"database_id": self.db},
            "properties": {
                self.title_prop: {"title": [{"text": {"content": title}}]},
                self.date_prop: {"date": {"start": start}},
            },
        })
        return self.parse_page(page)
