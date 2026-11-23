# CMake guidelines

Shared CMake modules ship inside the `xenoide-base` Conan python_requires and
are put on `CMAKE_MODULE_PATH` by the generated toolchain. Consumers do:

```cmake
cmake_minimum_required (VERSION 3.25)
project (myapp VERSION ${XENOIDE_BUILD_VERSION} LANGUAGES CXX)
include(XenoideConfig)
```

`XenoideConfig` provides `xenoide::interface`, `xenoide_add_catch2_tests`,
`xenoide_add_build_info`, `xenoide_enable_warnings` and
`xenoide_apply_instrumentation`.

## Folder and target structure

- One target per folder; the target name matches the folder.
- Engine targets keep their existing names (`xe-core`, `libxe-*-test`); the
  shared interface is `xenoide::interface` (replaces `xe::interface`).

## Executable

```cmake
find_package(Dependency CONFIG REQUIRED)
set(target "executable-name")
add_executable(${target} src/main.cpp)
target_link_libraries(${target} PRIVATE Dependency::Dependency xenoide::interface)
```

## Static library

```cmake
set(target "libprefix-name")
add_library(${target} ${sources})
add_library(prefix::library-name ALIAS ${target})
target_include_directories(${target} PUBLIC "src")
target_link_libraries(${target} PUBLIC library::component)
target_link_libraries(${target} PRIVATE xenoide::interface)
```

## Catch2 tests

```cmake
set(target "prefix-library-name-test")
add_executable(${target} ${sources})
target_link_libraries(${target} PRIVATE
    Catch2::Catch2WithMain
    prefix::library-name
    xenoide::interface)
xenoide_add_catch2_tests(${target})
```

Do **not** call `find_package(Catch2)` or `include(Catch)` yourself; the shared
module does it and attaches the sanitizer environment to every discovered test.

## Instrumentation and warnings

Link first-party targets to `xenoide::interface`. Never instrument a
third-party target. `XENOIDE_WERROR` is driven by the `werror` Conan option.

## Style checker

CMake files are validated by the `cmake-checker` tool package through the
devkit tools environment; run `mise run cmake-check`.
