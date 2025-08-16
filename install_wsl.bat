@echo off
REM WSL2 Installation script for R36S development
REM Must be run as Administrator

echo ============================================
echo    WSL2 Installation for R36S Development    
echo ============================================
echo.

REM Check if running as administrator
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: This script must be run as Administrator
    echo.
    echo Right-click on Command Prompt and select "Run as administrator"
    echo Then run this script again
    pause
    exit /b 1
)

echo ✓ Running as Administrator
echo.

echo [1/5] Enabling Windows Subsystem for Linux...
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
if %errorlevel% neq 0 (
    echo ERROR: Failed to enable WSL feature
    pause
    exit /b 1
)
echo ✓ WSL feature enabled

echo.
echo [2/5] Enabling Virtual Machine Platform...
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
if %errorlevel% neq 0 (
    echo ERROR: Failed to enable VM Platform
    pause
    exit /b 1
)
echo ✓ VM Platform enabled

echo.
echo [3/5] Setting WSL2 as default...
wsl --set-default-version 2
echo ✓ WSL2 set as default

echo.
echo [4/5] Downloading WSL kernel update...
REM Download the latest WSL2 kernel update
curl -L -o wsl_update_x64.msi https://wslstorestorage.blob.core.windows.net/wslblob/wsl_update_x64.msi
if exist wsl_update_x64.msi (
    echo ✓ Kernel update downloaded
    echo Installing kernel update...
    msiexec /i wsl_update_x64.msi /quiet
    echo ✓ Kernel update installed
    del wsl_update_x64.msi
) else (
    echo WARNING: Could not download kernel update automatically
    echo Please download manually from: https://aka.ms/wsl2kernel
)

echo.
echo [5/5] Installing Ubuntu distribution...
echo.
echo Opening Microsoft Store to install Ubuntu...
echo Please:
echo 1. Install "Ubuntu" from the Microsoft Store
echo 2. Launch Ubuntu after installation
echo 3. Create a username and password
echo 4. Run the setup script below

start ms-windows-store://pdp/?ProductId=9PDXGNCFSCZV

echo.
echo ============================================
echo    REBOOT REQUIRED
echo ============================================
echo.
echo The computer must be restarted to complete WSL installation.
echo.
echo After reboot:
echo 1. Launch Ubuntu from Start Menu
echo 2. Complete the Ubuntu setup (username/password)
echo 3. Run: setup_ubuntu_for_r36s.bat
echo.
choice /C YN /M "Restart computer now? (Y/N)"
if %errorlevel% equ 1 (
    echo Restarting computer...
    shutdown /r /t 10 /c "Restarting for WSL2 installation"
) else (
    echo Please restart manually and continue setup
)

echo.
pause
