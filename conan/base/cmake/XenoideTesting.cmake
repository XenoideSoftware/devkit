include_guard(GLOBAL)

if(NOT XENOIDE_ENABLE_TESTING)
    return()
endif()

include(CTest)
enable_testing()
find_package(Catch2 3 CONFIG REQUIRED)
include(Catch)

function(xenoide_add_catch2_tests target)
    # Sanitizer runtimes honour these options whether the tests are launched
    # through `ctest` directly or through `mise run sanitize/test`, so plain
    # ctest behaves exactly like the task.
    set(_env "ASAN_OPTIONS=${XENOIDE_ASAN_OPTIONS}")
    set(_env "${_env};UBSAN_OPTIONS=${XENOIDE_UBSAN_OPTIONS}")
    set(_env "${_env};TSAN_OPTIONS=${XENOIDE_TSAN_OPTIONS}")
    if(XENOIDE_INSTRUMENT STREQUAL "coverage" AND CMAKE_CXX_COMPILER_ID MATCHES "Clang")
        set(_env "${_env};LLVM_PROFILE_FILE=${CMAKE_BINARY_DIR}/profiles/%p.profraw")
    endif()

    catch_discover_tests(${target}
        WORKING_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}"
        PROPERTIES ENVIRONMENT "${_env}"
    )
endfunction()
