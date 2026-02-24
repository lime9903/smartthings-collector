@echo off
echo ================================================
echo  SmartThings Collector - Build Start
echo ================================================
echo.

python --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed.
    echo         Please install from https://www.python.org
    pause
    exit /b 1
)

echo [1/3] Installing libraries...
pip install aiohttp matplotlib pyinstaller --quiet
echo       Done.
echo.

echo [2/3] Building exe... (1~3 min)
pyinstaller ^
  --onefile ^
  --noconsole ^
  --name "SmartThingsCollector" ^
  --add-data "smartthings_collector.py;." ^
  --add-data "smartthings_dashboard.py;." ^
  --add-data "smartthings_auth.py;." ^
  --add-data "config.json;." ^
  --hidden-import aiohttp ^
  --hidden-import asyncio ^
  --hidden-import matplotlib ^
  --hidden-import matplotlib.backends.backend_tkagg ^
  --hidden-import tkinter ^
  launcher.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. Check the error messages above.
    pause
    exit /b 1
)

echo       Done.
echo.
echo [3/3] Build complete!
echo.
echo  Output: dist\SmartThingsCollector.exe
echo.
echo  Next step:
echo   1. Install Inno Setup: https://jrsoftware.org/isdl.php
echo   2. Open installer.iss with Inno Setup
echo   3. Press F9 to compile
echo   4. SmartThingsCollector_Setup.exe will be created
echo.
echo ================================================
pause
