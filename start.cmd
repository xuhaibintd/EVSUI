@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\teradataevsui.ps1" start %*
exit /b %ERRORLEVEL%
