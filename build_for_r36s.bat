@echo off
REM Build script for R36S (ARM Linux) - Windows version
REM Requires WSL2 with cross-compilation toolchain or Docker

echo === Building R36S Viewer for ARM Linux (Windows) ===
echo.

REM Check if WSL is available
wsl --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: WSL not found! This script requires WSL2 with Ubuntu/Debian
    echo.
    echo Install WSL2 first:
    echo 1. Enable WSL: dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
    echo 2. Enable VM Platform: dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
    echo 3. Install Ubuntu from Microsoft Store
    echo 4. Install toolchain in WSL: sudo apt-get install gcc-arm-linux-gnueabihf g++-arm-linux-gnueabihf cmake
    pause
    exit /b 1
)

echo Checking WSL ARM toolchain...
wsl bash -c "command -v arm-linux-gnueabihf-gcc" >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: ARM cross-compilation toolchain not found in WSL!
    echo.
    echo Install in WSL with:
    echo wsl sudo apt-get update
    echo wsl sudo apt-get install gcc-arm-linux-gnueabihf g++-arm-linux-gnueabihf cmake build-essential
    echo.
    echo Installing now...
    wsl sudo apt-get update
    wsl sudo apt-get install -y gcc-arm-linux-gnueabihf g++-arm-linux-gnueabihf cmake build-essential
    if %errorlevel% neq 0 (
        echo Installation failed! Please install manually.
        pause
        exit /b 1
    )
)

echo ✓ WSL and ARM toolchain found

REM Create build directory
if exist build_r36s rmdir /s /q build_r36s
mkdir build_r36s
cd build_r36s

echo Configuring with CMake...
wsl cmake .. -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_SYSTEM_PROCESSOR=arm -DCMAKE_C_COMPILER=arm-linux-gnueabihf-gcc -DCMAKE_CXX_COMPILER=arm-linux-gnueabihf-g++ -DCMAKE_FIND_ROOT_PATH_MODE_PROGRAM=NEVER -DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY -DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY

if %errorlevel% neq 0 (
    echo ERROR: CMake configuration failed!
    cd ..
    pause
    exit /b 1
)

echo Building...
wsl make -j4

if %errorlevel% neq 0 (
    echo ERROR: Build failed!
    cd ..
    pause
    exit /b 1
)

echo.
echo === Build complete! ===
echo Executable: build_r36s\r36s_viewer
echo.

cd ..

REM Check if executable was created
if exist "build_r36s\r36s_viewer" (
    echo ✓ Build successful - ready for packaging
) else (
    echo ✗ Build failed - executable not found
    exit /b 1
)

pause
