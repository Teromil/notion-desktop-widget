"""
Claude Code status line command.
Claude Code passes session data as JSON on stdin; `rate_limits` holds the 5-hour and weekly limit usage
(Pro/Max subscribers, after the first reply in a session). We save it for the widget and print a short line.
Configured in ~/.claude/settings.json -> "statusLine".
"""
import json
import os
import sys
import time
from pathlib import Path

OUT = Path(__file__).with_name("claude_limits.json")


def main():
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))  # tolerate a BOM from Windows shells
    except (json.JSONDecodeError, ValueError):
        return
    limits = data.get("rate_limits") or {}
    if limits:
        payload = {"rate_limits": limits, "saved_at": int(time.time())}
        tmp = OUT.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, OUT)  # atomic: the widget never reads a half-written file

    parts = []
    for key, label in (("five_hour", "5ч"), ("seven_day", "нед")):
        pct = (limits.get(key) or {}).get("used_percentage")
        if pct is not None:
            parts.append(f"{label} {round(pct)}%")
    model = (data.get("model") or {}).get("display_name", "")
    print(" · ".join([p for p in [model] + parts if p]))


if __name__ == "__main__":
    main()
