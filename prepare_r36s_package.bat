@echo off
REM Prepare R36S installation package - Windows version
REM This script creates a ready-to-copy folder structure for the R36S SD card

echo === Preparing R36S Viewer Package (Windows) ===
echo.

REM Check if executable exists
if not exist "build_r36s\r36s_viewer" (
    echo ERROR: r36s_viewer executable not found!
    echo Run build_for_r36s.bat first
    pause
    exit /b 1
)

REM Create package directory
set PACKAGE_DIR=r36s_viewer_package
if exist "%PACKAGE_DIR%" rmdir /s /q "%PACKAGE_DIR%"
mkdir "%PACKAGE_DIR%"

REM Copy the main executable
copy "build_r36s\r36s_viewer" "%PACKAGE_DIR%\"
echo ✓ Copied executable

REM Copy assets folder if it exists
if exist "assets" (
    xcopy "assets" "%PACKAGE_DIR%\assets\" /e /i /q
    echo ✓ Copied assets folder
) else (
    mkdir "%PACKAGE_DIR%\assets"
    echo ✓ Created empty assets folder
)

REM Create launch script for R36S
echo #!/bin/bash > "%PACKAGE_DIR%\launch_viewer.sh"
echo # R36S Viewer Launcher >> "%PACKAGE_DIR%\launch_viewer.sh"
echo. >> "%PACKAGE_DIR%\launch_viewer.sh"
echo # Get script directory >> "%PACKAGE_DIR%\launch_viewer.sh"
echo DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" >> "%PACKAGE_DIR%\launch_viewer.sh"
echo cd "$DIR" >> "%PACKAGE_DIR%\launch_viewer.sh"
echo. >> "%PACKAGE_DIR%\launch_viewer.sh"
echo # Set environment for SDL2 (if needed) >> "%PACKAGE_DIR%\launch_viewer.sh"
echo export SDL_VIDEODRIVER=fbcon >> "%PACKAGE_DIR%\launch_viewer.sh"
echo export SDL_FBDEV=/dev/fb0 >> "%PACKAGE_DIR%\launch_viewer.sh"
echo. >> "%PACKAGE_DIR%\launch_viewer.sh"
echo # Launch the viewer >> "%PACKAGE_DIR%\launch_viewer.sh"
echo ./r36s_viewer "$@" >> "%PACKAGE_DIR%\launch_viewer.sh"

echo ✓ Created launch script

REM Create desktop entry for the R36S menu system
echo [Desktop Entry] > "%PACKAGE_DIR%\r36s_viewer.desktop"
echo Name=Subtitle Viewer >> "%PACKAGE_DIR%\r36s_viewer.desktop"
echo Comment=View subtitles and images >> "%PACKAGE_DIR%\r36s_viewer.desktop"
echo Exec=/opt/r36s_viewer/launch_viewer.sh >> "%PACKAGE_DIR%\r36s_viewer.desktop"
echo Icon=/opt/r36s_viewer/icon.png >> "%PACKAGE_DIR%\r36s_viewer.desktop"
echo Terminal=false >> "%PACKAGE_DIR%\r36s_viewer.desktop"
echo Type=Application >> "%PACKAGE_DIR%\r36s_viewer.desktop"
echo Categories=Game; >> "%PACKAGE_DIR%\r36s_viewer.desktop"

echo ✓ Created desktop entry

REM Create installation instructions
echo === R36S Viewer Installation === > "%PACKAGE_DIR%\INSTALL.txt"
echo. >> "%PACKAGE_DIR%\INSTALL.txt"
echo 1. Copy this entire folder to your R36S SD card >> "%PACKAGE_DIR%\INSTALL.txt"
echo 2. Connect to R36S via SSH or use terminal >> "%PACKAGE_DIR%\INSTALL.txt"
echo 3. Run the install script: ./install_to_r36s.sh >> "%PACKAGE_DIR%\INSTALL.txt"
echo 4. The viewer will be available in the applications menu >> "%PACKAGE_DIR%\INSTALL.txt"
echo. >> "%PACKAGE_DIR%\INSTALL.txt"
echo Usage: >> "%PACKAGE_DIR%\INSTALL.txt"
echo - Run without arguments to see menu of available assets >> "%PACKAGE_DIR%\INSTALL.txt"
echo - Run with directory name: ./r36s_viewer chaves001 >> "%PACKAGE_DIR%\INSTALL.txt"
echo - Use game controller or keyboard for navigation >> "%PACKAGE_DIR%\INSTALL.txt"
echo. >> "%PACKAGE_DIR%\INSTALL.txt"
echo Controls: >> "%PACKAGE_DIR%\INSTALL.txt"
echo - A/X: Next image >> "%PACKAGE_DIR%\INSTALL.txt"
echo - B/Y: Previous image >> "%PACKAGE_DIR%\INSTALL.txt"
echo - Start: Toggle subtitle display >> "%PACKAGE_DIR%\INSTALL.txt"
echo - Select: Toggle fullscreen/windowed mode >> "%PACKAGE_DIR%\INSTALL.txt"
echo - L/R: Fast navigation >> "%PACKAGE_DIR%\INSTALL.txt"

echo ✓ Created installation instructions

REM Create installer script for R36S
echo #!/bin/bash > "%PACKAGE_DIR%\install_to_r36s.sh"
echo. >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo # R36S Viewer Installer >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo set -e >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo. >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo echo "=== Installing R36S Viewer ===" >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo. >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo # Target directory >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo TARGET_DIR="/opt/r36s_viewer" >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo. >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo # Check if running as root or with sudo >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo if [ "$EUID" -ne 0 ]; then >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo     echo "Please run with sudo: sudo ./install_to_r36s.sh" >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo     exit 1 >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo fi >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo. >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo # Create target directory >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo mkdir -p "$TARGET_DIR" >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo. >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo # Copy files >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo cp r36s_viewer "$TARGET_DIR/" >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo cp launch_viewer.sh "$TARGET_DIR/" >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo cp -r assets "$TARGET_DIR/" 2^>/dev/null ^|^| true >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo. >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo # Set permissions >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo chmod +x "$TARGET_DIR/r36s_viewer" >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo chmod +x "$TARGET_DIR/launch_viewer.sh" >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo. >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo # Install desktop entry (if desktop environment exists) >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo if [ -d "/usr/share/applications" ]; then >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo     cp r36s_viewer.desktop /usr/share/applications/ >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo     echo "✓ Desktop entry installed" >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo fi >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo. >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo # Create symlink for easy access >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo ln -sf "$TARGET_DIR/launch_viewer.sh" /usr/local/bin/r36s_viewer >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo. >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo echo "✓ Installation complete!" >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo echo "" >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo echo "Usage:" >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo echo "  r36s_viewer              # Show menu of available content" >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo echo "  r36s_viewer chaves001    # View specific episode" >> "%PACKAGE_DIR%\install_to_r36s.sh"
echo echo "  r36s_viewer /path/to/images  # View custom image folder" >> "%PACKAGE_DIR%\install_to_r36s.sh"

echo ✓ Created installer script

echo.
echo === Package ready! ===
echo Directory: %PACKAGE_DIR%
echo.
echo Next steps:
echo 1. Copy the '%PACKAGE_DIR%' folder to your R36S SD card
echo 2. On R36S, run: sudo ./%PACKAGE_DIR%/install_to_r36s.sh
echo 3. Launch with: r36s_viewer
echo.
pause
