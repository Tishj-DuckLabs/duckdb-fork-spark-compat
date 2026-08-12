add_subdirectory(tokenizer)
add_subdirectory(transformer)

fork_parser_generated_sources(
  FORK_PARSER_PEG_SOURCES
  peg/autocomplete_core.cpp
  peg/keyword_helper.cpp
  peg/keyword_map.cpp
  peg/matcher.cpp
  peg/parser_packrat.cpp
  peg/peg_parser.cpp
  peg/sql_formatter.cpp)
add_library_unity(duckdb_fork_parser_peg OBJECT ${FORK_PARSER_PEG_SOURCES})
set(ALL_OBJECT_FILES
    ${ALL_OBJECT_FILES} $<TARGET_OBJECTS:duckdb_fork_parser_peg>
    PARENT_SCOPE)
