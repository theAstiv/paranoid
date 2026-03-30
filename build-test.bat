@echo off
REM Windows wrapper for build test script

echo.
echo ========================================
echo   Paranoid Pre-Release Build Test
echo ========================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH
    exit /b 1
)

REM Check if build dependencies are installed
python -c "import build, twine, PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo Installing build dependencies...
    python -m pip install -e ".[build,dev]"
    if errorlevel 1 (
        echo ERROR: Failed to install dependencies
        exit /b 1
    )
)

REM Run the build test
python scripts\build_test.py
exit /b %errorlevel%
