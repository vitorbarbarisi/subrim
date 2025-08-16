@echo off
REM Build script for R36S (ARM Linux) - Windows Native version
REM Uses Docker or precompiled binaries instead of WSL

echo === R36S Viewer Build (Windows Native) ===
echo.

REM Check if Docker is available as alternative to WSL
docker --version >nul 2>&1
if %errorlevel% equ 0 (
    echo ✓ Docker found - using Docker for cross-compilation
    goto :docker_build
) else (
    echo Docker not found - checking for precompiled option
    goto :precompiled_build
)

:docker_build
echo.
echo [DOCKER METHOD] Building with Docker...
echo ----------------------------------------

REM Create Dockerfile for ARM cross-compilation
echo FROM ubuntu:20.04 > Dockerfile.arm
echo ENV DEBIAN_FRONTEND=noninteractive >> Dockerfile.arm
echo RUN apt-get update ^&^& apt-get install -y \ >> Dockerfile.arm
echo     gcc-arm-linux-gnueabihf \ >> Dockerfile.arm
echo     g++-arm-linux-gnueabihf \ >> Dockerfile.arm
echo     cmake \ >> Dockerfile.arm
echo     build-essential \ >> Dockerfile.arm
echo     pkg-config \ >> Dockerfile.arm
echo     libsdl2-dev:armhf \ >> Dockerfile.arm
echo     libsdl2-image-dev:armhf \ >> Dockerfile.arm
echo     libsdl2-ttf-dev:armhf >> Dockerfile.arm
echo WORKDIR /src >> Dockerfile.arm
echo COPY . . >> Dockerfile.arm
echo RUN mkdir -p build_r36s ^&^& cd build_r36s ^&^& \ >> Dockerfile.arm
echo     cmake .. \ >> Dockerfile.arm
echo         -DCMAKE_SYSTEM_NAME=Linux \ >> Dockerfile.arm
echo         -DCMAKE_SYSTEM_PROCESSOR=arm \ >> Dockerfile.arm
echo         -DCMAKE_C_COMPILER=arm-linux-gnueabihf-gcc \ >> Dockerfile.arm
echo         -DCMAKE_CXX_COMPILER=arm-linux-gnueabihf-g++ \ >> Dockerfile.arm
echo         -DCMAKE_FIND_ROOT_PATH_MODE_PROGRAM=NEVER \ >> Dockerfile.arm
echo         -DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY \ >> Dockerfile.arm
echo         -DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY ^&^& \ >> Dockerfile.arm
echo     make -j4 >> Dockerfile.arm

echo Building Docker image...
docker build -f Dockerfile.arm -t r36s-builder .
if %errorlevel% neq 0 (
    echo ERROR: Docker build failed!
    goto :error_exit
)

echo Extracting compiled binary...
if exist build_r36s rmdir /s /q build_r36s
mkdir build_r36s

docker create --name r36s-extract r36s-builder
docker cp r36s-extract:/src/build_r36s/r36s_viewer build_r36s/r36s_viewer
docker rm r36s-extract

if exist "build_r36s\r36s_viewer" (
    echo ✓ Build successful with Docker!
    echo Executable: build_r36s\r36s_viewer
    goto :success_exit
) else (
    echo ERROR: Build failed - executable not found
    goto :error_exit
)

:precompiled_build
echo.
echo [PRECOMPILED METHOD] Using GitHub Actions or manual build
echo --------------------------------------------------------
echo.
echo WSL and Docker not available. You have these options:
echo.
echo 1. INSTALL WSL2 (Recommended):
echo    - Run as Administrator: wsl --install
echo    - Restart computer
echo    - Install Ubuntu from Microsoft Store
echo    - Run: wsl sudo apt-get install gcc-arm-linux-gnueabihf cmake
echo.
echo 2. INSTALL DOCKER:
echo    - Download Docker Desktop from docker.com
echo    - Install and restart
echo    - Run this script again
echo.
echo 3. USE GITHUB ACTIONS (Advanced):
echo    - Push your code to GitHub
echo    - Use GitHub Actions to build for ARM
echo    - Download the compiled binary
echo.
echo 4. BUILD ON LINUX/MAC:
echo    - Use a Linux VM or macOS
echo    - Run: ./build_for_r36s.sh
echo    - Copy the binary to Windows
echo.
echo 5. USE PRECOMPILED BINARY (If available):

REM Check if a precompiled binary is available
if exist "r36s_viewer_precompiled.exe" (
    echo    ✓ Found precompiled binary!
    if not exist build_r36s mkdir build_r36s
    copy "r36s_viewer_precompiled.exe" "build_r36s\r36s_viewer"
    echo    ✓ Copied to build_r36s\r36s_viewer
    goto :success_exit
) else (
    echo    ✗ No precompiled binary found
)

echo.
echo RECOMMENDED: Install WSL2 for easiest setup
echo Command: wsl --install
echo.
goto :error_exit

:success_exit
echo.
echo === Build Complete! ===
echo Binary location: build_r36s\r36s_viewer
echo Ready for packaging: prepare_r36s_package.bat
echo.
exit /b 0

:error_exit
echo.
echo === Build Failed ===
echo Please install WSL2 or Docker to continue
echo.
pause
exit /b 1
