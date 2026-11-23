include_guard(GLOBAL)

if(NOT XENOIDE_ENABLE_TESTING)
    return()
endif()

include(CTest)
enable_testing()
find_package(Catch2 3 CONFIG REQUIRED)
include(Catch)

#! Write a launcher that exports the per-config test environment and execs the
#! real test binary.
#!
#! `catch_discover_tests(PROPERTIES ENVIRONMENT "<semicolon list>")` cannot
#! transport a multi-variable environment: Catch2 re-parses the property list
#! with `cmake_parse_arguments`, which splits every `;` into a new argument, so
#! all variables but the first become bogus property names. A launcher keeps
#! the environment intact no matter how the tests are discovered (C2).
function(_xenoide_write_test_launcher target out_var)
    set(_env
        "ASAN_OPTIONS=${XENOIDE_ASAN_OPTIONS}"
        "UBSAN_OPTIONS=${XENOIDE_UBSAN_OPTIONS}"
        "TSAN_OPTIONS=${XENOIDE_TSAN_OPTIONS}")
    if(XENOIDE_INSTRUMENT STREQUAL "coverage" AND CMAKE_CXX_COMPILER_ID MATCHES "Clang")
        list(APPEND _env "LLVM_PROFILE_FILE=${CMAKE_BINARY_DIR}/profiles/%p.profraw")
    endif()

    if(WIN32)
        set(launcher "${CMAKE_CURRENT_BINARY_DIR}/xenoide-test-env-${target}.cmd")
        set(content "@echo off\r\n")
        foreach(entry IN LISTS _env)
            set(content "${content}set \"${entry}\"\r\n")
        endforeach()
        string(APPEND content "%*\r\n")
        file(WRITE "${launcher}" "${content}")
        set(${out_var} "cmd;/c;${launcher}" PARENT_SCOPE)
        return()
    endif()

    set(launcher "${CMAKE_CURRENT_BINARY_DIR}/xenoide-test-env-${target}.sh")
    file(WRITE "${launcher}" "#!/bin/sh\n")
    foreach(entry IN LISTS _env)
        string(FIND "${entry}" "=" _position)
        string(SUBSTRING "${entry}" 0 ${_position} _name)
        math(EXPR _value_start "${_position} + 1")
        string(SUBSTRING "${entry}" ${_value_start} -1 _value)
        file(APPEND "${launcher}" "export ${_name}='${_value}'\n")
    endforeach()
    file(APPEND "${launcher}" "exec \"$@\"\n")
    file(CHMOD "${launcher}" PERMISSIONS
        OWNER_READ OWNER_WRITE OWNER_EXECUTE
        GROUP_READ GROUP_EXECUTE
        WORLD_READ WORLD_EXECUTE)
    set(${out_var} "${launcher}" PARENT_SCOPE)
endfunction()

function(xenoide_add_catch2_tests target)
    # Sanitizer runtimes honour these options whether the tests are launched
    # through `ctest` directly or through `mise run sanitize/test`, so plain
    # ctest behaves exactly like the task.
    get_target_property(_emulator ${target} CROSSCOMPILING_EMULATOR)
    if(NOT _emulator)
        _xenoide_write_test_launcher(${target} _launcher)
        set_property(TARGET ${target} PROPERTY CROSSCOMPILING_EMULATOR "${_launcher}")
    else()
        message(WARNING
            "Xenoide: ${target} already has CROSSCOMPILING_EMULATOR; "
            "sanitizer/coverage test environment will not be applied")
    endif()

    # Catch2 already appends SKIP_RETURN_CODE 4 to every discovered test.
    catch_discover_tests(${target}
        WORKING_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}"
    )
endfunction()
