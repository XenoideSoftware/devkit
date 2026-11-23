include_guard(GLOBAL)

# Apply the instrumentation selected by the `instrument` Conan option
# (transported as the XENOIDE_INSTRUMENT cache variable) to a first-party
# target. Third-party targets are never instrumented.
function(xenoide_apply_instrumentation target)
    _xenoide_scope(${target} _scope)

    if(NOT XENOIDE_INSTRUMENT OR XENOIDE_INSTRUMENT STREQUAL "none")
        return()
    endif()

    if(XENOIDE_INSTRUMENT STREQUAL "asan")
        if(MSVC)
            target_compile_options(${target} ${_scope} /fsanitize=address)
        else()
            target_compile_options(${target} ${_scope}
                -fsanitize=address,undefined
                -fno-omit-frame-pointer
                -fno-sanitize-recover=undefined)
            target_link_options(${target} ${_scope}
                -fsanitize=address,undefined
                -fno-omit-frame-pointer
                -fno-sanitize-recover=undefined)
        endif()
        target_compile_definitions(${target} ${_scope} XENOIDE_ASAN=1)

    elseif(XENOIDE_INSTRUMENT STREQUAL "tsan")
        target_compile_options(${target} ${_scope} -fsanitize=thread -fno-omit-frame-pointer)
        target_link_options(${target} ${_scope} -fsanitize=thread -fno-omit-frame-pointer)
        target_compile_definitions(${target} ${_scope} XENOIDE_TSAN=1)

    elseif(XENOIDE_INSTRUMENT STREQUAL "coverage")
        if(CMAKE_CXX_COMPILER_ID MATCHES "GNU")
            target_compile_options(${target} ${_scope} --coverage -O0 -g)
            target_link_options(${target} ${_scope} --coverage)
        elseif(CMAKE_CXX_COMPILER_ID MATCHES "Clang")
            target_compile_options(${target} ${_scope}
                -fprofile-instr-generate -fcoverage-mapping -O0 -g)
            target_link_options(${target} ${_scope} -fprofile-instr-generate)
        endif()
        target_compile_definitions(${target} ${_scope} XENOIDE_COVERAGE=1)

    elseif(XENOIDE_INSTRUMENT STREQUAL "mutation")
        if(NOT XENOIDE_MULL_PLUGIN)
            message(FATAL_ERROR
                "instrument=mutation requires XENOIDE_MULL_PLUGIN "
                "(mull-ir-frontend-<N>); run `mise run doctor`.")
        endif()
        target_compile_options(${target} ${_scope}
            "-fpass-plugin=${XENOIDE_MULL_PLUGIN}" -O0 -g -grecord-command-line)
        target_compile_definitions(${target} ${_scope} XENOIDE_MUTATION=1)
    endif()
endfunction()
