@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\teradataevsui.ps1" restart %*
exit /b %ERRORLEVEL%
