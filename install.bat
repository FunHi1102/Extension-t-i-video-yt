@echo off
cd /d "%~dp0"
echo [1/3] Installing yt-dlp and bundled ffmpeg...
python -m pip install -U -r requirements.txt --quiet

echo [2/3] Registering silent auto-start on Windows login...
for /f "delims=" %%I in ('python -c "import sys, pathlib; print(pathlib.Path(sys.executable).with_name('pythonw.exe'))"') do set "PYTHONW=%%I"
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "YTQualityDownloaderBridge" /t REG_SZ /d "\"%PYTHONW%\" -B \"%~dp0server.py\"" /f >nul

echo [3/3] Starting background bridge now...
start "" "%PYTHONW%" -B "%~dp0server.py"

echo.
echo Done! Bridge is running silently in the background and will auto-start with Windows.
echo Load "%~dp0" in chrome://extensions/ and you are set forever.
pause
