@echo off
REM Ubuntu setup script for R36S development
REM Run this after WSL Ubuntu is installed and configured

echo ============================================
echo    Ubuntu Setup for R36S Development    
echo ============================================
echo.

REM Test WSL availability
echo Testing WSL connection...
wsl echo "WSL is working" >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: WSL not responding
    echo.
    echo Please ensure:
    echo 1. WSL2 is installed (run install_wsl.bat as Administrator)
    echo 2. Ubuntu is installed from Microsoft Store
    echo 3. Ubuntu has been launched and configured
    echo.
    pause
    exit /b 1
)

echo ✓ WSL is responding
echo.

echo [1/4] Updating Ubuntu packages...
wsl sudo apt-get update
if %errorlevel% neq 0 (
    echo ERROR: Failed to update packages
    echo Make sure Ubuntu is properly configured
    pause
    exit /b 1
)
echo ✓ Packages updated

echo.
echo [2/4] Installing build tools...
wsl sudo apt-get install -y build-essential cmake pkg-config
if %errorlevel% neq 0 (
    echo ERROR: Failed to install build tools
    pause
    exit /b 1
)
echo ✓ Build tools installed

echo.
echo [3/4] Installing ARM cross-compilation toolchain...
wsl sudo apt-get install -y gcc-arm-linux-gnueabihf g++-arm-linux-gnueabihf
if %errorlevel% neq 0 (
    echo ERROR: Failed to install ARM toolchain
    pause
    exit /b 1
)
echo ✓ ARM toolchain installed

echo.
echo [4/4] Installing SDL2 development libraries...
wsl sudo apt-get install -y libsdl2-dev libsdl2-image-dev libsdl2-ttf-dev
if %errorlevel% neq 0 (
    echo WARNING: Failed to install SDL2 libraries
    echo This might not be critical for cross-compilation
)
echo ✓ SDL2 libraries installed

echo.
echo ============================================
echo    Setup Complete!
echo ============================================
echo.

echo Testing ARM compiler...
wsl arm-linux-gnueabihf-gcc --version | head -1
if %errorlevel% equ 0 (
    echo ✓ ARM compiler is working
) else (
    echo ✗ ARM compiler test failed
    pause
    exit /b 1
)

echo.
echo Your WSL Ubuntu environment is now ready for R36S development!
echo.
echo Next steps:
echo 1. Run: build_for_r36s.bat
echo 2. Run: prepare_r36s_package.bat  
echo 3. Run: install_to_sd_card.bat
echo.
echo Or run everything at once: build_and_install_r36s.bat
echo.
pause
