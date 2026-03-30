@echo off
REM Install Git hooks for automatic testing (Windows)
REM
REM Usage:
REM   scripts\install-hooks.bat

setlocal

echo.
echo Installing Git hooks...
echo.

REM Check if we're in a git repository
if not exist ".git" (
    echo ERROR: Not a git repository. Run this from inside the paranoid repo.
    exit /b 1
)

REM Create hooks directory if it doesn't exist
if not exist ".git\hooks" mkdir ".git\hooks"

REM Install pre-commit hook
if exist "scripts\git-hooks\pre-commit" (
    copy /Y "scripts\git-hooks\pre-commit" ".git\hooks\pre-commit" >nul
    echo ✓ Installed pre-commit hook (runs fast tests before commit^)
) else (
    echo WARNING: pre-commit hook not found
)

REM Install pre-push hook
if exist "scripts\git-hooks\pre-push" (
    copy /Y "scripts\git-hooks\pre-push" ".git\hooks\pre-push" >nul
    echo ✓ Installed pre-push hook (runs full tests before push^)
) else (
    echo WARNING: pre-push hook not found
)

echo.
echo Git hooks installed successfully!
echo.
echo Now when you:
echo   • git commit  -^> Fast tests run automatically
echo   • git push    -^> Full test suite runs automatically
echo.
echo To bypass hooks (use sparingly^):
echo   • git commit --no-verify
echo   • git push --no-verify
echo.

endlocal
