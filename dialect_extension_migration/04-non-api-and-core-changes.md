# Changes outside simple dialect grammar hooks

This document records changes that are not just grammar/keyword/tokenizer/matcher/transform callbacks, including the requested parse-result and AST categories. See [`fork-vs-upstream-c5481653bb.diff`](./fork-vs-upstream-c5481653bb.diff).

## Parse-result change: string escape decoding

Location: `src/include/duckdb/parser/peg/transformer/parse_result.hpp`, class `StringLiteralParseResult`.

The fork changes the shared `ToExpression()` path for escape strings:

- `\uXXXX` decodes a four-hex-digit UTF-16 unit.
- A high surrogate followed by `\uXXXX` containing a low surrogate combines into one Unicode code point.
- `\UXXXXXXXX` reads eight hex digits and emulates Spark/Java UTF-16 widening behavior, including wrapping arithmetic for out-of-range values.
- Unpaired surrogates and invalid/out-of-range code points become `?` where conversion fails.
- Invalid/incomplete Unicode escapes fall back to the literal escape letter behavior used by the implementation.
- `\%` and `\_` deliberately retain their backslash, which is needed for Spark LIKE's default backslash escape.
- Existing C-style escapes continue to be handled; the matcher makes ordinary strings take this ESCAPE_STRING path.

### API assessment

There is no direct `DialectExtension` hook on `StringLiteralParseResult::ToExpression`. Port options, in preference order:

1. Make the dialect's `StringLiteral` terminal return a dialect-owned parse result whose transform directly creates the string `ConstantExpression`.
2. Add an upstream dialect callback for string decoding or terminal-to-expression conversion.
3. Upstream the generally useful portions if DuckDB wants the same semantics globally.
4. Keep a core patch only as a temporary bridge; this fails the goal of eliminating the fork.

Do not globally change ordinary DuckDB string semantics merely to support the Spark dialect.

## Helper AST changes

These structures are **intermediate transformer values**, not new persistent parsed AST node kinds. They nevertheless matter because the generated transform value system must carry them.

| File/type | Change | Purpose | Fork-free alternative |
|---|---|---|---|
| `create_table_definition.hpp` | add `Value comment` | Carries table COMMENT until CreateTableInfo is built. | Extension-owned create-table intermediate, or construct final CreateStatement in one transform. |
| new `partition_field_entry.hpp` | expression + optional type | Distinguishes existing partition expression from typed partition column declaration. | Extension-owned value type. |
| `partition_sorted_options.hpp` | add `ColumnList partition_columns` | Carries typed partition columns to CREATE TABLE. | Extension-owned value or merge directly into final column list. |
| new `partition_spec_entry.hpp` | identifier + optional expression value | Represents static/dynamic INSERT/ANALYZE/DESCRIBE partition entries. | Extension-owned value type. |
| new `spark_tbl_properties_action.hpp` | unset flag + case-insensitive property map | Carries SET/UNSET TBLPROPERTIES. | Extension-owned value type. |
| `expression_chain.hpp` | blank-line removal | Formatting-only; no semantic change. | Ignore. |

### API assessment

`ParsedGrammar` transform callbacks return type-erased `TransformResultValue`, but the referenced API demo only demonstrates core AST output. Validate whether a loadable extension can instantiate `TypedTransformResult<T>` for extension-owned `T` and retrieve it through child transforms. If templates/RTTI/declarations make this impossible across the extension boundary, add an API for opaque extension values or restructure transforms so intermediate rules return core types.

## Persistent AST assessment

The net diff adds no new subclass or field to the long-lived core hierarchies:

- `SQLStatement`
- `QueryNode`
- `TableRef`
- `ParsedExpression`

Spark syntax is expressed with existing nodes such as `SelectNode`, `InsertStatement`, `SetVariableStatement`, `ResetVariableStatement`, `JoinRef`, `SubqueryRef`, `FunctionExpression`, `OperatorExpression`, `CastExpression`, `StarExpression`, and `ConstantExpression`.

This is favorable for `DialectExtension`: serialization, binding, planning, and execution do not need to understand Spark-specific AST classes. The DESCRIBE QUERY transform does serialize an existing `QueryNode`; test that this use is supported from the loadable extension.

## Transformer generator and type registry changes

Locations: `scripts/parser/generate_transformer.py`, `scripts/parser/grammar_types.yml`, generated transformer headers/sources.

The fork extends the global generator registry with:

- new rule-to-C++ type assignments;
- custom override types such as partition entries and TBLPROPERTIES actions;
- manually excluded rules with hand-written transforms;
- the close-angle terminal override kind;
- recognition of `AngleBrackets(...)` as a parentheses-like grammar macro;
- many generated trampoline declarations and implementations.

It also contains a duplicated `packrat_memoized_rules` YAML key in the net file. YAML duplicate-key handling can silently replace one block; clean this up rather than carrying it into new work.

### API assessment

The purpose of `ParsedGrammar` is to avoid rebuilding DuckDB for dialect grammar changes. Therefore, a successful migration should not modify the core generator or global `grammar_types.yml`. Any new rule should carry its callback dynamically. If an extension cannot express parameterized grammar macros such as `AngleBrackets`, write the expanded rule (`'<' ... CloseAngleBracket`) or request a runtime grammar macro facility.

## Parser cache and parser object changes

Locations: `parser.hpp`, `parser.cpp`, `matcher.hpp`, `matcher.cpp`.

- `Parser` no longer owns a local cache or honors `options.parser_cache` for the fork parser.
- `Parser::GetCache()` always returns fork-local `ParserCache::GetDefault()`.
- `PEGMatcher::Get` also uses that process-wide cache.
- Forward declarations were moved outside the namespace block so the build-time namespace rewrite retains references to host types.

These changes keep the copied parser grammar separate from the host DuckDB grammar. They are infrastructure for coexistence, not Spark behavior.

### API assessment

Delete them in the final port. `DialectExtension::GetCompiledGrammar` already owns a dialect cache, and DuckDB's parser cache selects the grammar for the active dialect. Recreating a process-global cache would defeat per-connection dialect selection and could leak state between databases.

## Build-only parser namespace materialization

Locations:

- new `scripts/parser/materialize_fork_namespace.py`
- `src/parser/CMakeLists.txt`
- parser PEG/tokenizer/transformer CMake lists
- install rule in `src/CMakeLists.txt`

At configure time, the fork mirrors parser headers/sources into the build tree and rewrites the outer namespace from `duckdb` to `duckdb_fork`, while retaining selected host types. Custom CMake unity helpers compile the mirrored sources and install the rewritten headers over the canonical parser headers.

Purpose: link a complete fork parser beside the host parser without permanent namespace churn in tracked sources.

### API assessment

This entire mechanism should disappear when the Spark parser is a registered dialect. The extension should compile only its grammar mutation, terminal matchers/tokenizer as needed, transforms, and runtime functions. It must not ship or install a second copy of DuckDB's parser headers.

## Generated/inlined source changes

The full diff includes large generated artifacts:

- `inlined_grammar.gram` and `inlined_grammar.hpp`
- `keyword_map.cpp`
- `peg_transformer.hpp`
- `transform_generated.cpp`
- `transform_generated_trampoline.cpp`

These are useful for confirming the exact compiled fork state, but they are not independent requirements. Use the source `.gram`, keyword list, YAML, and hand-written transforms as the semantic source of truth.

## Non-parser core change

Location: `src/catalog/default/default_functions.cpp`.

The built-in `split_part` macro parameter was renamed:

```text
string  ->  str
```

The macro body was updated accordingly. This likely avoids a collision or Spark parsing ambiguity when `STRING` is accepted as a type/function keyword.

### API assessment

The dialect grammar API cannot change a built-in macro definition. Before retaining any core patch:

- reproduce the original failing Spark query;
- check whether the failure remains when parsing occurs through the new dialect and the macro is parsed/registered under the normal DuckDB dialect;
- if needed, register a compatibility macro in the extension or upstream the harmless parameter rename.

Record this as an explicit fork-elimination dependency, not a parser feature.

## Nonfunctional/project metadata

- `.gitignore` adds `metastore_db` and `spark-warehouse`.
- `README.md` is replaced with a two-line notice that the fork is only useful with its extension.

These changes do not belong in the DialectExtension port.

## Core changes that may be worth upstreaming independently

Some changes are broadly useful beyond Spark but should be considered separately from the dialect migration:

- nested block comments, if DuckDB wants them in its default tokenizer;
- protected/composable tokenizer hooks;
- reusable default transform helpers or post-transform hooks for function calls and completed SelectNodes;
- terminal parse-result/string-decoder customization;
- safe extension-owned intermediate transform values;
- a close-angle/type-token solution that does not require dialect-specific duplication of the tokenizer loop.

Keeping these as small upstream API improvements is preferable to maintaining a shadow parser in the extension.
