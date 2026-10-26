@echo off
REM Build WiFi-IPLocator with Nuitka (onefile, PySide6 plugin, app icon)
REM Usage: build_nuitka.bat  (run from project root)
REM
REM NOTE: Nuitka on Python 3.13+ requires MSVC (Visual Studio Build Tools
REM       with C++ workload). The --mingw64 flag is NOT supported on 3.13+.
REM       If you have no MSVC, install "Visual Studio Build Tools" first:
REM       https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022
setlocal
cd /d "%~dp0"

python -m nuitka --version >nul 2>nul
if errorlevel 1 (
    echo [ERROR] nuitka not found. Install it first: pip install nuitka
    exit /b 1
)

python -m nuitka ^
    --standalone --onefile ^
    --enable-plugin=pyside6 ^
    --windows-console-mode=disable ^
    --windows-icon-from-ico=assets\icon.ico ^
    --include-data-dir=assets=assets ^
    --output-dir=build-nuitka ^
    --output-filename=WiFi-IPLocator.exe ^
    --assume-yes-for-downloads ^
    run.py

if errorlevel 1 (
    echo [ERROR] Build failed. See build_nuitka.log
    exit /b 1
)
echo [OK] Build finished: build-nuitka\WiFi-IPLocator.exe
endlocal
