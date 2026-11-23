include_guard(GLOBAL)

# Generate a header with the version and commit of the application, so a
# user-facing binary can report exactly which commit it came from.
#
#   xenoide_add_build_info(<target> PREFIX <P>)
#
# defines <P>_BUILD_VERSION and <P>_BUILD_COMMIT. There is deliberately no
# timestamp: the commit carries its own date.
function(xenoide_add_build_info target)
    cmake_parse_arguments(ARG "" "PREFIX" "" ${ARGN})
    if(NOT ARG_PREFIX)
        set(ARG_PREFIX "XE")
    endif()

    set(_dir "${CMAKE_BINARY_DIR}/generated/xenoide-build-info")
    file(MAKE_DIRECTORY "${_dir}")

    set(_version "${${ARG_PREFIX}_BUILD_VERSION}")
    set(_commit "${${ARG_PREFIX}_BUILD_COMMIT}")
    if(NOT _version)
        set(_version "${XENOIDE_BUILD_VERSION}")
    endif()
    if(NOT _commit)
        set(_commit "${XENOIDE_BUILD_COMMIT}")
    endif()

    file(WRITE "${_dir}/xenoide_build_info.h"
"#pragma once
#define ${ARG_PREFIX}_BUILD_VERSION \"${_version}\"
#define ${ARG_PREFIX}_BUILD_COMMIT \"${_commit}\"
")

    target_include_directories(${target} PRIVATE "${_dir}")
endfunction()
