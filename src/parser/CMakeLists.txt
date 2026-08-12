# The tracked parser sources retain DuckDB's upstream namespace. Materialize a
# build-only mirror for the fork so namespace churn does not affect Git merges.
if(NOT Python3_EXECUTABLE)
  find_package(
    Python3
    COMPONENTS Interpreter
    REQUIRED)
endif()

set(FORK_PARSER_SOURCE_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../..")
set(FORK_PARSER_NAMESPACE_MIRROR "${CMAKE_CURRENT_BINARY_DIR}/fork_namespace")
set(FORK_PARSER_NAMESPACE_SCRIPT
    "${FORK_PARSER_SOURCE_ROOT}/scripts/parser/materialize_fork_namespace.py")

file(GLOB_RECURSE FORK_PARSER_NAMESPACE_INPUTS CONFIGURE_DEPENDS
     "${CMAKE_CURRENT_SOURCE_DIR}/../include/duckdb/parser/*"
     "${CMAKE_CURRENT_SOURCE_DIR}/peg/*.cpp")
list(APPEND FORK_PARSER_NAMESPACE_INPUTS
     "${CMAKE_CURRENT_SOURCE_DIR}/parser.cpp" "${FORK_PARSER_NAMESPACE_SCRIPT}")
set_property(
  DIRECTORY
  APPEND
  PROPERTY CMAKE_CONFIGURE_DEPENDS ${FORK_PARSER_NAMESPACE_INPUTS})

execute_process(
  COMMAND
    "${Python3_EXECUTABLE}" "${FORK_PARSER_NAMESPACE_SCRIPT}" --source-root
    "${FORK_PARSER_SOURCE_ROOT}" --output-root "${FORK_PARSER_NAMESPACE_MIRROR}"
  RESULT_VARIABLE FORK_PARSER_NAMESPACE_RESULT
  OUTPUT_VARIABLE FORK_PARSER_NAMESPACE_OUTPUT
  ERROR_VARIABLE FORK_PARSER_NAMESPACE_ERROR)
if(NOT FORK_PARSER_NAMESPACE_RESULT EQUAL 0)
  message(
    FATAL_ERROR
      "Failed to materialize the fork parser namespace:\n${FORK_PARSER_NAMESPACE_ERROR}"
  )
endif()
message(STATUS "${FORK_PARSER_NAMESPACE_OUTPUT}")

# The unity-build helper expects source paths relative to the current source
# directory. Translate mirror paths at each call site so unity and non-unity
# builds consume the same generated files.
function(fork_parser_generated_sources OUTPUT_VARIABLE)
  set(GENERATED_SOURCES)
  foreach(SOURCE_FILE ${ARGN})
    file(RELATIVE_PATH GENERATED_SOURCE "${CMAKE_CURRENT_SOURCE_DIR}"
         "${FORK_PARSER_NAMESPACE_MIRROR}/src/parser/${SOURCE_FILE}")
    list(APPEND GENERATED_SOURCES "${GENERATED_SOURCE}")
  endforeach()
  set(${OUTPUT_VARIABLE}
      ${GENERATED_SOURCES}
      PARENT_SCOPE)
endfunction()

# Expose this tree's parser headers to the fork TUs; all non-parser includes
# continue to resolve to the host DuckDB source tree.
include_directories(BEFORE "${FORK_PARSER_NAMESPACE_MIRROR}/include")
set(FORK_PARSER_NAMESPACE_INCLUDE_DIR
    "${FORK_PARSER_NAMESPACE_MIRROR}/include"
    PARENT_SCOPE)

# Start from a clean object list: only fork objects may flow to the parent
# scope.
set(ALL_OBJECT_FILES)

add_subdirectory(peg)

fork_parser_generated_sources(FORK_PARSER_SOURCES parser.cpp)
add_library_unity(duckdb_fork_parser OBJECT ${FORK_PARSER_SOURCES})
set(ALL_OBJECT_FILES
    ${ALL_OBJECT_FILES} $<TARGET_OBJECTS:duckdb_fork_parser>
    PARENT_SCOPE)
