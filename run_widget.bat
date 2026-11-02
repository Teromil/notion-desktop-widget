@echo off
rem Запуск виджета без окна консоли (из своего окружения .venv)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0notion_widget.py"
