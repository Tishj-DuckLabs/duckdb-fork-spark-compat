fork_parser_generated_sources(
  FORK_PARSER_PEG_TOKENIZER_SOURCES peg/tokenizer/base_tokenizer.cpp
  peg/tokenizer/highlight_tokenizer.cpp peg/tokenizer/parser_tokenizer.cpp)
add_fork_parser_library(duckdb_fork_parser_peg_tokenizer OBJECT
                        ${FORK_PARSER_PEG_TOKENIZER_SOURCES})

set(ALL_OBJECT_FILES
    ${ALL_OBJECT_FILES} $<TARGET_OBJECTS:duckdb_fork_parser_peg_tokenizer>
    PARENT_SCOPE)
