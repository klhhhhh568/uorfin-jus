cmake_minimum_required(VERSION 3.10)
project(UorfinCore)
set(CMAKE_CXX_STANDARD 17)

find_package(Python3 REQUIRED COMPONENTS Development)

add_executable(uorfin_core uorfin_core.cpp)
target_include_directories(uorfin_core PRIVATE ${Python3_INCLUDE_DIRS})
target_link_libraries(uorfin_core pthread dl ${Python3_LIBRARIES})