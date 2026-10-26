@echo off
REM Build WiFi-IPLocator single-file exe with PyInstaller
REM Usage: build.bat  (run from project root)
setlocal
cd /d "%~dp0"

where pyinstaller >nul 2>nul
if errorlevel 1 (
    echo [ERROR] pyinstaller not found. Install it first: pip install pyinstaller
    exit /b 1
)

pyinstaller --noconfirm --clean --onefile --windowed ^
    --name WiFi-IPLocator ^
    --icon assets\icon.ico ^
    --add-data "assets;assets" ^
    run.py

if errorlevel 1 (
    echo [ERROR] Build failed
    exit /b 1
)
echo [OK] Build finished: dist\WiFi-IPLocator.exe
endlocal
