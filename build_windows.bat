@echo off
setlocal enabledelayedexpansion

echo ===================================================
echo   Clinic Inventory Management - Windows Build Script
echo ===================================================

REM 1. Activate or create virtual environment
if not exist .venv (
    echo [*] Creating virtual environment (.venv)...
    python -m venv .venv || (echo [ERROR] Failed to create venv & exit /b 1)
)

call .venv\Scripts\activate || (echo [ERROR] Failed to activate venv & exit /b 1)

REM 2. Install / verify dependencies
echo [*] Installing dependencies from requirements.txt...
pip install -r requirements.txt || (echo [ERROR] Failed to install dependencies & exit /b 1)

REM 3. Run regression test suite
echo [*] Running automated test suite...
python -m pytest -q
if errorlevel 1 (
    echo [ERROR] Automated tests failed! Build aborted.
    exit /b 1
)
echo [OK] All automated tests passed.

REM 4. Build standalone Windows application with PyInstaller
echo [*] Building executable with PyInstaller...
pyinstaller --noconfirm --windowed --name ClinicInventory ^
  --add-data "clinic_inventory\assets;clinic_inventory\assets" run_app.py

if errorlevel 1 (
    echo [ERROR] PyInstaller build failed!
    exit /b 1
)

echo ===================================================
echo [SUCCESS] Build completed successfully!
echo Executable location: dist\ClinicInventory\ClinicInventory.exe
echo ===================================================
endlocal

