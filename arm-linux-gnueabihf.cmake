# CMake Toolchain File for ARM Linux Cross-Compilation
# For R36S (ARM Cortex-A7) cross-compilation from x86_64

set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR arm)

# Cross-compilation tools
set(CMAKE_C_COMPILER arm-linux-gnueabihf-gcc)
set(CMAKE_CXX_COMPILER arm-linux-gnueabihf-g++)

# Target environment on the build host system
set(CMAKE_FIND_ROOT_PATH /usr/arm-linux-gnueabihf)

# Search for programs in the build host directories
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)

# For libraries and headers in the target directories
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)

# R36S specific flags (ARM Cortex-A7 with NEON)
set(CMAKE_C_FLAGS "-march=armv7-a -mfpu=neon-vfpv4 -mfloat-abi=hard")
set(CMAKE_CXX_FLAGS "-march=armv7-a -mfpu=neon-vfpv4 -mfloat-abi=hard")

# Force sysroot to avoid host system headers
set(CMAKE_SYSROOT /usr/arm-linux-gnueabihf)
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} --sysroot=/usr/arm-linux-gnueabihf")
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} --sysroot=/usr/arm-linux-gnueabihf")

# Disable pkg-config to avoid conflicts - we'll set paths manually
set(PKG_CONFIG_FOUND FALSE)

# Cache variables
set(CMAKE_C_COMPILER_WORKS TRUE)
set(CMAKE_CXX_COMPILER_WORKS TRUE)
