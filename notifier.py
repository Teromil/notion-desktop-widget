"""Native Windows toast notifications via PowerShell (no extra packages)."""
import base64
import subprocess
from xml.sax.saxutils import escape

# Notifications are shown under the PowerShell app identity, which exists on every Windows 10/11.
APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"


def toast(title, body):
    xml = (f"<toast><visual><binding template='ToastGeneric'>"
           f"<text>{escape(title)}</text><text>{escape(body)}</text>"
           f"</binding></visual><audio src='ms-winsoundevent:Notification.Reminder'/></toast>")
    script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml(@'
{xml}
'@)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{APP_ID}').Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                     creationflags=subprocess.CREATE_NO_WINDOW)
