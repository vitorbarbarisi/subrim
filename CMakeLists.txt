cmake_minimum_required(VERSION 3.16)
project(r36s_viewer C)

set(CMAKE_C_STANDARD 11)

find_package(PkgConfig REQUIRED)
pkg_check_modules(SDL2 REQUIRED sdl2)
pkg_check_modules(IMG REQUIRED SDL2_image)
pkg_check_modules(TTF REQUIRED SDL2_ttf)

add_executable(r36s_viewer
  r36s_viewer.c
)

target_include_directories(r36s_viewer PRIVATE
  ${SDL2_INCLUDE_DIRS} ${IMG_INCLUDE_DIRS} ${TTF_INCLUDE_DIRS}
)

target_link_libraries(r36s_viewer PRIVATE
  ${SDL2_LIBRARIES} ${IMG_LIBRARIES} ${TTF_LIBRARIES}
)


