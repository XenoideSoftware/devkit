include_guard(GLOBAL)

# Convenience umbrella: consumers include this single module after project().
include("${CMAKE_CURRENT_LIST_DIR}/XenoideInterface.cmake")
include("${CMAKE_CURRENT_LIST_DIR}/XenoideTesting.cmake")
include("${CMAKE_CURRENT_LIST_DIR}/XenoideBuildInfo.cmake")
