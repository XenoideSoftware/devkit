include_guard(GLOBAL)

include("${CMAKE_CURRENT_LIST_DIR}/XenoideWarnings.cmake")
include("${CMAKE_CURRENT_LIST_DIR}/XenoideInstrumentation.cmake")

add_library(xenoide_interface INTERFACE)
add_library(xenoide::interface ALIAS xenoide_interface)

target_compile_features(xenoide_interface INTERFACE cxx_std_17)

if(CMAKE_BUILD_TYPE STREQUAL "Debug")
    target_compile_definitions(xenoide_interface INTERFACE _DEBUG)
endif()

xenoide_enable_warnings(xenoide_interface)
xenoide_apply_instrumentation(xenoide_interface)
