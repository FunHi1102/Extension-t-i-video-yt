@echo off
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "YTQualityDownloaderBridge" /f >nul 2>&1
taskkill /F /IM pythonw.exe >nul 2>&1
echo Removed YTQualityDownloaderBridge from Windows startup.
pause
