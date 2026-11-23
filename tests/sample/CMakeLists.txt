cmake_minimum_required (VERSION 3.25)
project (xenoide_sample LANGUAGES CXX)

include(XenoideConfig)

find_package(fmt CONFIG REQUIRED)

add_library (sample src/sample.cpp)
target_include_directories (sample PUBLIC src)
target_link_libraries (sample PRIVATE xenoide::interface fmt::fmt)

xenoide_add_build_info (sample PREFIX SAMPLE)

add_executable (sample-cli src/main.cpp)
target_link_libraries (sample-cli PRIVATE sample xenoide::interface)

if (XENOIDE_ENABLE_TESTING)
    add_executable (sample-test test/sample-test.cpp)
    target_link_libraries (sample-test PRIVATE sample Catch2::Catch2WithMain xenoide::interface)
    xenoide_add_catch2_tests (sample-test)
endif ()
