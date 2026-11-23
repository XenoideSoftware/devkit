include_guard(GLOBAL)

# Select the propagation scope for a target: INTERFACE libraries only accept
# INTERFACE properties; concrete targets need PUBLIC so that their own
# compilation is affected too.
function(_xenoide_scope target out_var)
    get_target_property(_type ${target} TYPE)
    if(_type STREQUAL "INTERFACE_LIBRARY")
        set(${out_var} INTERFACE PARENT_SCOPE)
    else()
        set(${out_var} PUBLIC PARENT_SCOPE)
    endif()
endfunction()

function(xenoide_enable_warnings target)
    _xenoide_scope(${target} _scope)

    if(CMAKE_CXX_COMPILER_ID MATCHES "MSVC")
        target_compile_options(${target} ${_scope} /W4)
        if(XENOIDE_WERROR)
            target_compile_options(${target} ${_scope} /WX)
        endif()
    elseif(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(${target} ${_scope} -Wall -Wextra)
        if(XENOIDE_WERROR)
            target_compile_options(${target} ${_scope} -Werror)
        endif()
    endif()
endfunction()
