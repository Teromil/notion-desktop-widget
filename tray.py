"""System tray icon and Windows autostart. Tray needs `pystray` + `pillow`; without them it's skipped."""
import os
import sys
from pathlib import Path

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    pystray = None

STARTUP_FILE = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup\NotionWidget.cmd"
SCRIPT = Path(__file__).with_name("notion_widget.py")


def autostart_enabled():
    return STARTUP_FILE.exists()


def set_autostart(enabled):
    if enabled:
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        STARTUP_FILE.write_text(f'@start "" "{pythonw}" "{SCRIPT}"\n', encoding="utf-8")
    elif STARTUP_FILE.exists():
        STARTUP_FILE.unlink()


def _icon_image():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 4, 60, 60), 12, fill="white", outline="#37352f", width=4)
    d.line([(21, 46), (21, 18), (43, 46), (43, 18)], fill="#37352f", width=6)
    return img


def start(app):
    """Start the tray icon in its own thread. Menu actions are marshalled to the Tk thread via app.call."""
    if pystray is None:
        return None
    menu = pystray.Menu(
        pystray.MenuItem("Показать / скрыть", lambda: app.call(app.toggle_visible), default=True),
        pystray.MenuItem("Обновить", lambda: app.call(app.refresh)),
        pystray.MenuItem("Поверх всех окон", lambda: app.call(app.toggle_topmost),
                         checked=lambda item: app.prefs.get("always_on_top", False)),
        pystray.MenuItem("Автозапуск с Windows", lambda: set_autostart(not autostart_enabled()),
                         checked=lambda item: autostart_enabled()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выход", lambda: app.call(app.quit_app)),
    )
    icon = pystray.Icon("notion_widget", _icon_image(), "Notion виджет", menu)
    icon.run_detached()
    return icon
