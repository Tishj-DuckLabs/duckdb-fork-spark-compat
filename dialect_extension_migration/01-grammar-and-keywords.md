# Grammar and keyword changes

This document classifies the grammar-source changes in the refreshed fork. See the complete patch in [`fork-vs-upstream-c5481653bb.diff`](./fork-vs-upstream-c5481653bb.diff), especially `src/parser/peg/grammar/keywords/*` and `src/parser/peg/grammar/statements/*`.

For the target API, implement these in `DialectExtension::ApplyGrammarChanges(GrammarChangesInput &)`. Prefer narrow `AddRule` and `AddChoice` operations where possible. Use `ReplaceRule` only when precedence, ordering, or the shape of an existing rule truly changes. Attach the extension transform at the same time for every new rule that produces a semantic value.

## Keyword classes

The generated `src/parser/peg/keyword_map.cpp` mirrors these list changes; do not port that generated file manually.

| Class | Additions | Removals | Reason/use |
|---|---|---|---|
| column-name | `DIV`, `SUBSTR`, `TIMESTAMPDIFF` | — | Allows these expression keywords where the column-name grammar participates. |
| function-name/type-function | `ANY`, `ARRAY`, `BIGINT`, `BOOLEAN`, `CHAR`, `DECIMAL`, `DOUBLE`, `EXISTS`, `FLOAT`, `INT`, `SMALLINT`, `SOME`, `STRING`, `TIMESTAMP`, `TINYINT` | — | Spark permits aggregate names and type-like words as function identifiers. |
| reserved | `MINUS`, `SORT` | `ALL`, `ANY`, `SOME` | `MINUS` and `SORT BY` become syntax; `ALL`/`ANY`/`SOME` must remain usable as identifiers/function names. |
| type-name | `DOUBLE`, `STRING`, `TINYINT` | — | Spark type aliases in type-name contexts. |
| unreserved | `BINDING`, `COMPENSATION`, `EVOLUTION`, `EXTENDED`, `FORMATTED`, `MAX`, `RECURSION`, `TBLPROPERTIES`, `UNSET` | — | New view modes, describe/explain modes, recursion clause, and table properties. |

Migration note: keyword classification affects both parsing and whether a word is accepted as an identifier. Verify that the dialect-specific `PEGKeywordHelper` is built from the mutated grammar. If list-style keyword classes are not independently mutable through `ParsedGrammar`, the API needs a keyword-class operation or the dialect must provide `CreateKeywordHelper`.

## Top-level statement routing

Search for `Statement <-` in `common.gram`.

New choices, with ordering preserved because PEG choice order is semantic:

- `MultiInsertStatement` before ordinary `SelectStatement`/`InsertStatement`.
- `ReadSettingStatement` next to `SetStatement`.
- `DeclareStatement` and `DropVariableStatement`.
- `SparkAlterTblPropertiesStmt` before ordinary `AlterStatement`.

These are good `AddRule` plus ordered `AddChoice`/`PrependChoice` candidates. Pay special attention to rules whose prefixes overlap existing statements.

## Common types and partition syntax

Source: `statements/common.gram`.

| Syntax/rule | Grammar change | Porting intent |
|---|---|---|
| `ARRAY<T>` | Add `ArrayAngleBracketsType`; include it in `TypeVariations`. | Lower to DuckDB list type. |
| `MAP<K,V>` | Split `MapType` into parentheses and angle-bracket alternatives. | Both lower to DuckDB map type. |
| `STRUCT<name: type,...>` | Split `ColIdTypeList`; add colon-form entries and angle brackets. | Lower to DuckDB struct type. |
| nested `>>` closers | Add `AngleBrackets(D)` and terminal `CloseAngleBracket`. | Coupled to tokenizer/matcher changes in document 02. |
| interval unit | Remove `IntervalToInterval` from generic `Interval`. | Prevent range syntax from being consumed as a single-unit interval; range has a dedicated expression rule. |
| `PARTITION (col [= value],...)` | Add `PartitionSpec` and `PartitionSpecEntry`. | Shared by INSERT, ANALYZE, and DESCRIBE. |

Because `TypeVariations`, `ColIdTypeList`, `MapType`, and `Interval` replace existing shapes, these are `ReplaceRule` operations rather than independent appended choices unless the cursor API can target the exact alternative safely.

## DDL and administration

### ALTER TABLE

Source: `statements/alter.gram`.

- `ALTER TABLE name SET TBLPROPERTIES (...)`.
- `ALTER TABLE name UNSET TBLPROPERTIES [IF EXISTS] (...)`.
- Property keys and values accept identifiers or strings; `=` is optional in a property pair.
- Only `comment` maps to a DuckDB concept. Other keys are accepted and ignored by the transformer.

### ANALYZE

Source: `statements/analyze.gram`.

- Optional Spark `TABLE` keyword.
- Optional `PartitionSpec`.
- Optional `COMPUTE STATISTICS` with `NOSCAN`, `FOR ALL COLUMNS`, or `FOR COLUMNS (...)`.
- Compute-statistics detail is parsed and ignored because DuckDB has no equivalent partition/column-statistics command in this path.

### CREATE/DROP DATABASE

Sources: `create_schema.gram`, `drop.gram`.

- `DATABASE` is accepted anywhere these rules accept `SCHEMA` and lowers to the existing schema AST.

### CREATE TABLE

Source: `create_table.gram`.

- `USING format [LOCATION 'path']` in CTAS and column-list forms; parsed but ignored.
- Table-level `COMMENT <identifier-or-string>`.
- `PARTITIONED BY` entries may be expressions or typed declarations (`name type`).
- Column definitions accept `COMMENT 'text'`.
- Spark clauses are ordered around existing identifier lists, partition/sort options, `WITH`, and `AS`; copy the resulting ordering exactly when replacing the rules.

### CREATE VIEW

Source: `create_view.gram`.

- View columns may have `COMMENT` clauses.
- `WITH SCHEMA BINDING`, `COMPENSATION`, `EVOLUTION`, or `TYPE EVOLUTION` is accepted.
- Column comments and schema modes are syntactic compatibility only; the current transformer ignores them.

### Variables

Source: new `declare.gram`.

- `DECLARE [OR REPLACE] [VARIABLE] name [type] [DEFAULT expr | = expr]`.
- `DROP [TEMPORARY|TEMP] VARIABLE [IF EXISTS] name`.
- These lower to existing DuckDB `SET VARIABLE` and `RESET VARIABLE` statements.

### DESCRIBE

Source: `describe.gram`.

- `DESCRIBE QUERY <query>`; the existing `DESCRIBE <query>` path is also reinterpreted.
- `DESCRIBE FUNCTION [EXTENDED] <name>`.
- `DESCRIBE [TABLE] [EXTENDED|FORMATTED] <table> [PARTITION (...)] [column.path]`.
- Choice ordering is important: `QUERY` and `FUNCTION` must be recognized before the generic table target, while existing `ALL TABLES` keeps priority.

### EXPLAIN

Source: `explain.gram`.

- Add `EXTENDED`, `CODEGEN`, `COST`, and `FORMATTED` modes.
- All modes lower to ordinary DuckDB EXPLAIN; the mode is ignored.

## Expression grammar

Source: `statements/expression.gram`.

### Functions, rows, and aliases

- Allow `IGNORE NULLS` / `RESPECT NULLS` after the closing function parenthesis as well as inside it.
- Parenthesized expression lists and VALUES rows use `RowExpressionArg`, which permits `expr AS field`.
- `ROW(...)` and `STRUCT(...)` share a rule; individual fields can use `AS name`.
- `SUBSTR(...)` aliases `SUBSTRING(...)`.
- `EXTRACT(field FROM source)` also accepts `EXTRACT(field, source)`.
- `POSITION(needle IN haystack)` also accepts comma separators and an optional third start argument.
- Add `TIMESTAMPDIFF(unit, start, end)`.
- Named function arguments use `ReservedIdentifier` instead of `TypeFuncName`, permitting names such as reserved `COLUMN`.

### Intervals

- `INTERVAL [sign] 'value' <start> TO <end>` becomes `IntervalRangeLiteral`.
- `INTERVAL value unit value unit ...` becomes `IntervalMultiUnitLiteral`.
- The range sign may appear outside the string and is folded into the literal by the transformer.
- The transformer distinguishes year-month from day-time interval ranges and performs Spark-compatible validation/conversion.

### Operators and precedence

- Prefix `!` aliases `NOT`.
- `RLIKE` is a LIKE variation.
- `LIKE ANY (...)` and `LIKE ALL (...)` are added, including `NOT` through the existing surrounding rule.
- Quantified comparisons use `AnyAllOp`, an operator list that excludes `->`, avoiding ambiguity with a lambda parameter named `all`.
- Spark bitwise precedence is represented as three tiers: shifts bind tighter than `&`, which binds tighter than `|`.
- `DIV` joins the multiplicative factors.
- The rest of the precedence levels are renumbered but otherwise structurally retained.

These changes modify left-recursive/chain-like expression shapes and must be treated as a coordinated replacement. Do not append isolated alternatives without checking PEG ordering and generated transform result types.

## INSERT and query grammar

### INSERT

Source: `insert.gram`.

- Optional `TABLE` after `INSERT INTO`.
- Optional `PartitionSpec` after the target.
- Spark multi-insert: `FROM source INSERT INTO ... SELECT ... [WHERE/GROUP BY/HAVING]` repeated for multiple branches.
- Multi-insert projections intentionally use AS-only aliasing so an unreserved `INSERT` is not swallowed as an implicit alias.

### Set operations and SELECT

Source: `select.gram`.

- `MINUS` aliases `EXCEPT`.
- Remove `SELECT ALL` from `DistinctClause` (plain SELECT already means all rows).
- `VALUES` accepts the standard parenthesized rows, bare expressions, and a trailing table alias.
- CTEs accept `MAX RECURSION LEVEL n`; the current transformer ignores the limit.
- Column alias lists use `ColLabelOrString`, broadening keyword acceptance.
- Select items accept parenthesized multi-column aliases: `generator(...) AS (c1,c2,...)`.

### Joins

- `CROSS JOIN` may carry an optional ON/USING qualifier.
- `JOIN LATERAL (subquery) [alias]`.
- Any join type may omit ON/USING through `UnqualifiedJoinClause`.
- `LEFT SEMI JOIN` and `LEFT ANTI JOIN` spellings.
- Unqualified joins use `InnerTableRef` so chained joins associate to the left like Spark.

### Grouping and ordering

- A group-by list may end in `WITH CUBE`, `WITH ROLLUP`, or trailing `GROUPING SETS (...)`.
- `SORT BY` is accepted alongside `ORDER BY`.
- `OrderByExpressions` tries an expression list before `ORDER BY ALL`, matching the fork's ambiguity resolution.

## SET and time zone

Source: `set.gram`.

- Value-less `SET key` is a read operation (`ReadSettingStatement`).
- Settings can be dotted (`spark.sql.shuffle.partitions`).
- `SET TIME ZONE` accepts both interval literals and interval range-as-type forms.
- These rules feed custom transformer behavior and `__spark_interval_timezone`.

## Generated consequences

The following are generated or schema-like consequences, not separate language features:

- `src/include/duckdb/parser/peg/inlined_grammar.gram`
- `src/include/duckdb/parser/peg/inlined_grammar.hpp`
- `src/parser/peg/keyword_map.cpp`
- `src/include/duckdb/parser/peg/transformer/peg_transformer.hpp`
- `src/parser/peg/transformer/transform_generated.cpp`
- `src/parser/peg/transformer/transform_generated_trampoline.cpp`
- additions to `scripts/parser/grammar_types.yml` for types, overrides, excluded/manual rules, packrat rules, and the `CloseAngleBracket` matcher override
- `scripts/parser/generate_transformer.py` recognition of `AngleBrackets` as a parentheses-like grammar macro and generation of the close-angle matcher override

In a `DialectExtension`, the extension should define transform callbacks directly when changing the grammar. It should not need to add fork rules to DuckDB's global `grammar_types.yml` if `ParsedGrammar` transform values can be extension-owned. Any case that still requires regenerating core transformer declarations is an API gap to record rather than silently reintroducing a fork.
