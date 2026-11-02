"""
Refresh Claude plan limits in the background: one tiny Haiku request through the terminal Claude Code
(`claude -p`), whose event stream includes a `rate_limit_event` with the 5-hour and weekly usage.
Costs a few tokens of the cheapest model per refresh; the session isn't saved to history.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

DEFAULT_EXE = Path(os.environ.get("USERPROFILE", "")) / ".local" / "bin" / "claude.exe"


def claude_exe():
    found = shutil.which("claude")
    if found:
        return found
    return str(DEFAULT_EXE) if DEFAULT_EXE.exists() else None


def claude_running():
    """True if the Claude desktop app or the terminal Claude Code is running (both are claude.exe)."""
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq claude.exe", "/NH"], capture_output=True,
                             text=True, errors="replace", timeout=15, creationflags=subprocess.CREATE_NO_WINDOW).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "claude.exe" in out.lower()


def fetch_limits(timeout=120):
    """Return {"five_hour": {...}, "seven_day": {...}} in the status line format, or None."""
    exe = claude_exe()
    if not exe:
        return None
    cmd = [exe, "-p", "Reply with just: ok", "--model", "haiku", "--max-turns", "1",
           "--output-format", "stream-json", "--verbose",
           "--no-session-persistence", "--strict-mcp-config"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, cwd=tempfile.gettempdir(), stdin=subprocess.DEVNULL,
                              creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in proc.stdout.splitlines():
        if '"rate_limit_event"' not in line:
            continue
        try:
            windows = json.loads(line)["rate_limit_info"].get("unifiedWindows") or {}
        except (json.JSONDecodeError, KeyError):
            continue
        limits = {}
        for key in ("five_hour", "seven_day"):
            w = windows.get(key)
            if w and w.get("utilization") is not None:
                limits[key] = {"used_percentage": w["utilization"] * 100, "resets_at": w.get("resetsAt")}
        return limits or None
    return None


def save_limits(path, limits):
    """Same file format the status line script writes."""
    payload = {"rate_limits": limits, "saved_at": int(time.time())}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)
