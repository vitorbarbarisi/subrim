@echo off
REM Direct installation to R36S SD Card - Windows version
REM This script copies the viewer directly to the mounted SD card

echo === R36S Viewer SD Card Installation (Windows) ===
echo.

REM Load drive configuration
if exist "drive_config.bat" (
    call drive_config.bat
    echo Using saved configuration:
    echo   R36S-OS: %R36S_OS_DRIVE%
    echo   EASYROMS: %EASYROMS_DRIVE%
) else (
    REM Default drive letters for R36S SD card partitions
    set R36S_OS_DRIVE=D:
    set EASYROMS_DRIVE=F:
    echo Using default drive letters. Run config_windows.bat to customize.
)

REM Check if package exists
if not exist "r36s_viewer_package" (
    echo ERROR: Package not found! Run prepare_r36s_package.bat first
    pause
    exit /b 1
)

echo Looking for R36S SD card drives...

REM Check for R36S-OS partition
if not exist "%R36S_OS_DRIVE%\" (
    echo ERROR: R36S-OS partition not found at drive %R36S_OS_DRIVE%
    echo.
    echo Please:
    echo 1. Insert R36S SD card into Windows computer
    echo 2. Check drive letters in File Explorer
    echo 3. Update R36S_OS_DRIVE and EASYROMS_DRIVE variables in this script if needed
    echo.
    echo Current settings:
    echo   R36S-OS: %R36S_OS_DRIVE%
    echo   EASYROMS: %EASYROMS_DRIVE%
    pause
    exit /b 1
)

echo ✓ Found R36S-OS partition: %R36S_OS_DRIVE%

REM Check for EASYROMS partition
if not exist "%EASYROMS_DRIVE%\" (
    echo WARNING: EASYROMS partition not found at drive %EASYROMS_DRIVE%
    echo This is optional - viewer will work without it
    set EASYROMS_AVAILABLE=false
) else (
    echo ✓ Found EASYROMS partition: %EASYROMS_DRIVE%
    set EASYROMS_AVAILABLE=true
)

REM Create applications directory on R36S-OS
set APPS_DIR=%R36S_OS_DRIVE%\apps
set VIEWER_DIR=%APPS_DIR%\r36s_viewer

echo Creating application directory...
if not exist "%APPS_DIR%" mkdir "%APPS_DIR%"
if exist "%VIEWER_DIR%" rmdir /s /q "%VIEWER_DIR%"
mkdir "%VIEWER_DIR%"

REM Copy viewer files to R36S-OS
echo Copying viewer files...
xcopy "r36s_viewer_package\*" "%VIEWER_DIR%\" /e /i /q /y

if %errorlevel% neq 0 (
    echo ERROR: Failed to copy files to %VIEWER_DIR%
    pause
    exit /b 1
)

REM Copy assets to EASYROMS if available (better for large files)
if "%EASYROMS_AVAILABLE%"=="true" (
    echo Copying assets to EASYROMS for better performance...
    set ASSETS_DIR=%EASYROMS_DRIVE%\r36s_viewer_assets
    
    if exist "!ASSETS_DIR!" rmdir /s /q "!ASSETS_DIR!"
    
    if exist "assets" (
        xcopy "assets" "!ASSETS_DIR!\" /e /i /q /y
        echo ✓ Assets copied to EASYROMS
        
        REM Remove assets from R36S-OS (will be symlinked)
        if exist "%VIEWER_DIR%\assets" rmdir /s /q "%VIEWER_DIR%\assets"
        
        REM Update launch script to handle symlink
        echo #!/bin/bash > "%VIEWER_DIR%\launch_viewer.sh"
        echo # R36S Viewer Launcher with EASYROMS assets support >> "%VIEWER_DIR%\launch_viewer.sh"
        echo. >> "%VIEWER_DIR%\launch_viewer.sh"
        echo # Get script directory >> "%VIEWER_DIR%\launch_viewer.sh"
        echo DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" >> "%VIEWER_DIR%\launch_viewer.sh"
        echo cd "$DIR" >> "%VIEWER_DIR%\launch_viewer.sh"
        echo. >> "%VIEWER_DIR%\launch_viewer.sh"
        echo # Create symlink to assets on EASYROMS if not exists >> "%VIEWER_DIR%\launch_viewer.sh"
        echo if [ ! -L "assets" ] ^&^& [ -d "/storage/roms/r36s_viewer_assets" ]; then >> "%VIEWER_DIR%\launch_viewer.sh"
        echo     ln -sf /storage/roms/r36s_viewer_assets assets >> "%VIEWER_DIR%\launch_viewer.sh"
        echo fi >> "%VIEWER_DIR%\launch_viewer.sh"
        echo. >> "%VIEWER_DIR%\launch_viewer.sh"
        echo # Set environment for SDL2 (if needed) >> "%VIEWER_DIR%\launch_viewer.sh"
        echo export SDL_VIDEODRIVER=fbcon >> "%VIEWER_DIR%\launch_viewer.sh"
        echo export SDL_FBDEV=/dev/fb0 >> "%VIEWER_DIR%\launch_viewer.sh"
        echo. >> "%VIEWER_DIR%\launch_viewer.sh"
        echo # Launch the viewer >> "%VIEWER_DIR%\launch_viewer.sh"
        echo ./r36s_viewer "$@" >> "%VIEWER_DIR%\launch_viewer.sh"
    )
)

REM Create autostart entry (optional - for direct boot to viewer)
echo #!/bin/bash > "%VIEWER_DIR%\autostart.sh"
echo # Optional: Auto-start viewer on boot >> "%VIEWER_DIR%\autostart.sh"
echo # To enable: copy this file to /etc/autostart/ on R36S >> "%VIEWER_DIR%\autostart.sh"
echo. >> "%VIEWER_DIR%\autostart.sh"
echo # Wait for system to fully boot >> "%VIEWER_DIR%\autostart.sh"
echo sleep 5 >> "%VIEWER_DIR%\autostart.sh"
echo. >> "%VIEWER_DIR%\autostart.sh"
echo # Start viewer in fullscreen >> "%VIEWER_DIR%\autostart.sh"
echo /apps/r36s_viewer/launch_viewer.sh >> "%VIEWER_DIR%\autostart.sh"

REM Create uninstaller
echo #!/bin/bash > "%VIEWER_DIR%\uninstall.sh"
echo # Uninstaller for R36S Viewer >> "%VIEWER_DIR%\uninstall.sh"
echo. >> "%VIEWER_DIR%\uninstall.sh"
echo echo "Removing R36S Viewer..." >> "%VIEWER_DIR%\uninstall.sh"
echo. >> "%VIEWER_DIR%\uninstall.sh"
echo # Remove from R36S-OS >> "%VIEWER_DIR%\uninstall.sh"
echo rm -rf /apps/r36s_viewer >> "%VIEWER_DIR%\uninstall.sh"
echo. >> "%VIEWER_DIR%\uninstall.sh"
echo # Remove from EASYROMS >> "%VIEWER_DIR%\uninstall.sh"
echo rm -rf /storage/roms/r36s_viewer_assets >> "%VIEWER_DIR%\uninstall.sh"
echo. >> "%VIEWER_DIR%\uninstall.sh"
echo # Remove desktop entry >> "%VIEWER_DIR%\uninstall.sh"
echo rm -f /usr/share/applications/r36s_viewer.desktop >> "%VIEWER_DIR%\uninstall.sh"
echo. >> "%VIEWER_DIR%\uninstall.sh"
echo # Remove symlink >> "%VIEWER_DIR%\uninstall.sh"
echo rm -f /usr/local/bin/r36s_viewer >> "%VIEWER_DIR%\uninstall.sh"
echo. >> "%VIEWER_DIR%\uninstall.sh"
echo echo "R36S Viewer removed successfully" >> "%VIEWER_DIR%\uninstall.sh"

echo.
echo === Installation Complete! ===
echo.
echo Viewer installed to: %VIEWER_DIR%
if "%EASYROMS_AVAILABLE%"=="true" (
    echo Assets stored in: %EASYROMS_DRIVE%\r36s_viewer_assets
)
echo.
echo On your R36S console:
echo 1. Insert the SD card
echo 2. Navigate to: /apps/r36s_viewer/
echo 3. Run: sudo ./install_to_r36s.sh
echo 4. Or run directly: ./launch_viewer.sh
echo.
echo Controls:
echo - D-pad/Analog: Navigate
echo - A button: Next image
echo - B button: Previous image
echo - Start: Toggle subtitles
echo - Select: Menu/Exit
echo.
echo Usage examples:
echo - ./launch_viewer.sh                    # Show episode menu
echo - ./launch_viewer.sh chaves001          # View specific episode
echo - ./launch_viewer.sh --windowed         # Run in windowed mode
echo.
pause
