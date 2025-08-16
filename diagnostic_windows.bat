@echo off
REM Diagnostic script for R36S Windows installation
REM Run this to check your Windows environment

echo ============================================
echo    R36S Windows Environment Diagnostic    
echo ============================================
echo.

echo [1] Checking current directory...
echo Current directory: %CD%
echo.

echo [2] Checking for R36S batch files...
if exist "build_for_r36s.bat" (
    echo ✓ build_for_r36s.bat found
) else (
    echo ✗ build_for_r36s.bat NOT found
)

if exist "prepare_r36s_package.bat" (
    echo ✓ prepare_r36s_package.bat found
) else (
    echo ✗ prepare_r36s_package.bat NOT found
)

if exist "install_to_sd_card.bat" (
    echo ✓ install_to_sd_card.bat found
) else (
    echo ✗ install_to_sd_card.bat NOT found
)

if exist "build_and_install_r36s.bat" (
    echo ✓ build_and_install_r36s.bat found
) else (
    echo ✗ build_and_install_r36s.bat NOT found
)
echo.

echo [3] Checking WSL availability...
wsl --version >nul 2>&1
if %errorlevel% equ 0 (
    echo ✓ WSL is available
    echo WSL version:
    wsl --version | findstr /C:"WSL"
) else (
    echo ✗ WSL not found or not working
    echo   Install WSL2 from Microsoft Store
)
echo.

echo [4] Checking file contents...
if exist "build_for_r36s.bat" (
    echo First few lines of build_for_r36s.bat:
    type "build_for_r36s.bat" | more /E +1 | head -5
) else (
    echo Cannot check contents - file not found
)
echo.

echo [5] File listing...
echo All .bat files in current directory:
dir *.bat /B 2>nul
if %errorlevel% neq 0 echo No .bat files found
echo.

echo [6] System information...
echo Windows version: 
ver
echo.
echo Path: %PATH%
echo.

echo [7] Suggested actions...
echo.
if not exist "build_for_r36s.bat" (
    echo ⚠️  ISSUE: build_for_r36s.bat not found
    echo    1. Make sure you're in the correct directory
    echo    2. Copy all .bat files from the macOS project
    echo    3. Or download them again
    echo.
)

wsl --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ⚠️  ISSUE: WSL not available
    echo    1. Install WSL2: wsl --install
    echo    2. Restart computer
    echo    3. Install Ubuntu from Microsoft Store
    echo.
)

echo ============================================
echo    Diagnostic Complete
echo ============================================
echo.
echo If you see any ✗ above, those need to be fixed first.
echo.
pause
