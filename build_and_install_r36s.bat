@echo off
REM Complete R36S Viewer build and installation script for Windows
REM This script runs all steps in sequence

echo ============================================
echo    R36S Viewer - Complete Windows Setup    
echo ============================================
echo.

REM Step 1: Build the viewer
echo [1/3] Building R36S Viewer...
echo ----------------------------------------
call build_for_r36s.bat
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Build failed! Cannot continue.
    pause
    exit /b 1
)

echo.
echo ✓ Build completed successfully!
echo.

REM Step 2: Prepare the package
echo [2/3] Preparing installation package...
echo ----------------------------------------
call prepare_r36s_package.bat
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Package preparation failed!
    pause
    exit /b 1
)

echo.
echo ✓ Package prepared successfully!
echo.

REM Step 3: Install to SD card
echo [3/3] Installing to R36S SD Card...
echo ----------------------------------------
echo Please ensure your R36S SD card is connected to your computer.
echo.
pause

call install_to_sd_card.bat
if %errorlevel% neq 0 (
    echo.
    echo ERROR: SD card installation failed!
    pause
    exit /b 1
)

echo.
echo ============================================
echo    🎉 INSTALLATION COMPLETE! 🎉
echo ============================================
echo.
echo Your R36S Viewer is now ready to use!
echo.
echo Final steps on your R36S console:
echo.
echo 1. Insert the SD card into your R36S
echo 2. Power on the console
echo 3. Connect via SSH or use terminal
echo 4. Navigate to: /apps/r36s_viewer/
echo 5. Run: sudo ./install_to_r36s.sh
echo.
echo Then launch with: r36s_viewer
echo.
echo 📁 Package contents:
echo    - Executable: r36s_viewer
echo    - Assets: Your subtitle episodes
echo    - Scripts: Launcher and installer
echo.
echo 🎮 Controls:
echo    - A: Next image
echo    - B: Previous image  
echo    - Start: Toggle subtitles
echo    - Select: Menu/Exit
echo.
echo Enjoy your subtitle viewer on R36S! 🎬
echo.
pause
