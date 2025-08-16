@echo off
REM Configuration file for Windows R36S installation
REM Edit the drive letters below to match your system

echo === R36S Windows Configuration ===
echo.

REM ========================================
REM CONFIGURE THESE DRIVE LETTERS FOR YOUR SYSTEM
REM ========================================

REM R36S-OS partition (usually D: or E:)
set R36S_OS_DRIVE=D:

REM EASYROMS partition (usually F: or G:)  
set EASYROMS_DRIVE=F:

REM ========================================
REM END CONFIGURATION
REM ========================================

echo Current configuration:
echo   R36S-OS partition: %R36S_OS_DRIVE%
echo   EASYROMS partition: %EASYROMS_DRIVE%
echo.

REM Check if drives exist
echo Checking drive availability...

if exist "%R36S_OS_DRIVE%\" (
    echo ✓ R36S-OS partition found at %R36S_OS_DRIVE%
) else (
    echo ✗ R36S-OS partition NOT found at %R36S_OS_DRIVE%
    echo   Please update R36S_OS_DRIVE in this file
)

if exist "%EASYROMS_DRIVE%\" (
    echo ✓ EASYROMS partition found at %EASYROMS_DRIVE%
) else (
    echo ✗ EASYROMS partition NOT found at %EASYROMS_DRIVE%
    echo   Please update EASYROMS_DRIVE in this file
    echo   (This is optional - viewer will work without it)
)

echo.
echo To change these settings:
echo 1. Edit this file (config_windows.bat)
echo 2. Update the drive letters at the top
echo 3. Save and run this script again to verify
echo.

REM Export variables for other scripts
echo set R36S_OS_DRIVE=%R36S_OS_DRIVE% > drive_config.bat
echo set EASYROMS_DRIVE=%EASYROMS_DRIVE% >> drive_config.bat

echo Configuration saved to drive_config.bat
echo.
pause
