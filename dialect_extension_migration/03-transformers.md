# Transformer changes

The fork normally lowers Spark syntax into existing DuckDB parsed AST classes rather than introducing persistent Spark AST nodes. That makes a fork-free port feasible, but it still requires extension-owned transforms for both new grammar rules and altered existing rules.

See [`fork-vs-upstream-c5481653bb.diff`](./fork-vs-upstream-c5481653bb.diff), primarily the hand-written files under `src/parser/peg/transformer/`. The generated transformer files are consequences, not the implementation to copy.

At `DialectExtension` commit `78565bf`, use:

- `ParsedGrammar::AddRule(definition, transform)` for new rules;
- `ParsedGrammar::SetTransform(rule, transform)` when a grammar shape is unchanged but semantics differ;
- `ParsedGrammar::ReplaceRule(definition, transform)` when both change.

The transform callback returns `TransformResultValue`. Confirm that extension code can use `PEGTransformer::Transform<T>` and construct the intermediate result types listed in document 04. If not, that is an API gap.

## Common types and literals

Locations: `transform_common.cpp`, `transform_expression.cpp`.

### Angle-bracket nested types

- `MAP<K,V>` reuses the existing DuckDB map type expression.
- `ARRAY<T>` builds the DuckDB `list` type expression.
- `STRUCT<name: type,...>` builds named struct children.
- Parentheses forms remain supported.

The `CloseAngleBracket` matcher behavior is documented separately because the transform itself is ordinary type lowering.

### Spark numeric postfixes

Search `CastSparkNumberWithPostfix`.

- `L` → BIGINT
- `S` → SMALLINT
- `Y` → TINYINT
- `D` → DOUBLE
- `F` → FLOAT
- `BD` → DECIMAL, with width/scale inferred from the textual value

The number matcher supplies one concatenated number-plus-suffix string. Invalid casts surface as parser errors. Preserve the glued-token rule from document 02.

### Typed temporal literals

Search `TransformTypeLiteral`.

For DATE and TIMESTAMP typed strings, Spark's incomplete year and year-month forms are padded before the normal cast:

- `DATE '0015'` → value text `0015-01-01`
- a year-month form gains `-01`
- an optional leading sign is kept

### Spark strings

String escape semantics are partly in `StringLiteralParseResult::ToExpression`, not in these files. See document 04.

## Function and expression lowering

Location: `transform_expression.cpp`.

### Function calls

`TransformFunctionExpression` contains a large set of Spark-specific branches:

- `COUNT(*)` keeps row-count semantics; stars in other function argument lists become DuckDB UNPACK operators.
- `first(...) OVER` and `last(...) OVER` become `first_value` and `last_value`.
- Trailing or inner `IGNORE/RESPECT NULLS` is accepted once. For non-window `first`, `last`, and `any_value`, it becomes the boolean second argument expected by the compatibility aggregate. Other non-window functions reject null treatment.
- Spark ordered-set `percentile_cont`, `percentile_disc`, and `mode` with `WITHIN GROUP` map to DuckDB `quantile_cont`, `quantile_disc`, and `mode`; the ordering expression is moved into the function arguments. Descending percentile order negates the fraction. This works in aggregate and window forms with validation for DISTINCT/multiple ORDER BY clauses.
- Non-lambda expressions in higher-order lambda positions are wrapped in lambdas with hidden parameters, matching Spark binding behavior:
  - `transform`: argument 2, one hidden element parameter;
  - `aggregate`/`reduce`: merge argument has accumulator+element, optional finish argument has accumulator;
  - `transform_values`: key+value;
  - `zip_with`: left+right element;
  - `map_zip_with`: key+left+right value.
- Four-argument `regexp_replace` is renamed to extension helper `__spark_regexp_replace_position`.
- Struct/row arguments receive Spark field names: explicit alias, referenced column name, or `colN`; stars expand through UNPACK.

Because this replaces an existing, central transform, the port should avoid copying all upstream logic. A reusable upstream post-transform hook for function calls would materially reduce maintenance. Without one, the dialect must track the full default transform or factor Spark rewrites into rules that run before/after it.

### Parenthesized rows and structs

- A one-element parenthesis returns its child.
- Multiple unaliased children become `row(...)`.
- If any child has `AS`, the expression becomes `struct_pack(...)`.
- `ROW(...)` and `STRUCT(...)` become named `struct_pack` fields, with automatic Spark names.
- Star children are converted to UNPACK.

### Operators

- Prefix `!` produces the same NOT operator chain as `NOT`.
- `RLIKE` produces `regexp_matches(lhs, rhs)`.
- `LIKE`/`ILIKE` default to backslash as the escape character when no explicit ESCAPE is present.
- `LIKE ANY` becomes an OR of individual LIKE calls; `LIKE ALL` becomes AND. `NOT` negates the individual LIKE functions.
- Bitwise `|`, `&`, and shifts are lowered as operator function expressions according to the new precedence tiers.
- `DIV` becomes `CAST(TRUNC(lhs / rhs) AS BIGINT)`, truncating toward zero.
- Adding an expression created by the Spark interval constructors (`make_interval` or `make_ym_interval`) is rerouted to `__spark_add_calendar_interval` rather than ordinary `+`.

### Special functions

- `TIMESTAMPDIFF(unit,start,end)` → `datediff(unit,start,end)`.
- `EXTRACT(field,source)` and the FROM spelling both → `date_part`.
- `SUBSTR` and `SUBSTRING` → `substring`.
- `POSITION(needle,haystack,start)` → `locate(needle,haystack,start)`; two-argument/IN forms remain `position` with the expected argument order.

### Interval forms

Search `TransformIntervalRangeLiteral` and `TransformIntervalMultiUnitLiteral`.

Range strings:

- The optional sign outside the quotes is combined with an optional sign inside; two negative signs cancel.
- `YEAR TO MONTH` parses `[+|-]years-months`, validates months, and produces total months.
- Day-time ranges support start/end among DAY, HOUR, MINUTE, SECOND, validate field widths/ranges, parse fractional seconds, pad/truncate the fraction to nanoseconds and then convert to microseconds.
- Day-time results are normalized into DuckDB interval days plus sub-day microseconds.
- Invalid strings raise a parser error naming the expected Spark format.

Multi-unit intervals:

- Year/month units are accumulated in months and lowered through `to_months`.
- Week/day/hour/minute/second/millisecond/microsecond units are accumulated as BIGINT microseconds.
- Day-time totals split into `to_days(total // micros_per_day)` plus `to_microseconds(total % micros_per_day)` so overflow rolls up.
- Mixing year-month and day-time unit families is rejected/handled according to the current implementation; carry the exact validation into tests.

## DDL and administration transforms

### ALTER TBLPROPERTIES

Location: `transform_alter.cpp`.

- Properties are gathered case-insensitively into `SparkTblPropertiesAction`.
- A `comment` property becomes the existing `SetCommentInfo`/ALTER statement for a table.
- `UNSET ... ('comment')` clears the comment.
- If no `comment` key appears, the statement becomes a no-op `VacuumStatement` so parsing/execution succeeds while other Spark properties are discarded.

### ANALYZE

Location: `transform_analyze.cpp`.

- Optional `TABLE`, partition specification, and compute-statistics scope are ignored.
- The target is lowered to the existing analyze/vacuum representation.

### CREATE TABLE

Location: `transform_create_table.cpp`.

- `USING` and `LOCATION` are parsed but ignored.
- Table comment is retained in the helper `CreateTableDefinition.comment` and applied to create-table info.
- Column `COMMENT` becomes `ColumnDefinition::SetComment` rather than a constraint.
- Bare partition expressions remain partition keys.
- Typed partition fields append new columns to the table schema; their expression identifies the column and the optional type carries its declaration.

### CREATE VIEW

Location: `transform_create_view.cpp`.

- Spark view column names are preserved.
- Per-column comments and WITH SCHEMA mode are accepted but ignored.

### DECLARE/DROP VARIABLE

Location: new `transform_declare.cpp`.

- DECLARE → `SetVariableStatement` with `SetScope::VARIABLE`.
- Missing initializer becomes NULL.
- Declared type and OR REPLACE are ignored.
- DROP VARIABLE → `ResetVariableStatement`; TEMP/TEMPORARY and IF EXISTS are accepted without adding new AST types.

### DESCRIBE

Location: `transform_describe.cpp`.

The statements become `SelectNode` objects over companion-extension table functions:

| Spark form | Runtime table function |
|---|---|
| table | `spark_describe` |
| extended/formatted table | `spark_describe_extended` |
| column | `spark_describe_column` |
| extended/formatted column | `spark_describe_column_extended` |
| query | `spark_describe_query` |
| function | `spark_describe_function` |
| extended function | `spark_describe_function_extended` |

Table names are rendered as qualified strings. Column paths are passed as a VARCHAR list. Query DESCRIBE serializes the parsed `QueryNode` rather than relying on `ToString()`, so the runtime helper can rebind the exact AST. Confirm that serialization/deserialization remains stable and accessible to a loadable extension.

### EXPLAIN

Location: `transform_explain.cpp`.

Spark mode keywords all return a presence marker and otherwise have no effect; ordinary DuckDB EXPLAIN AST is used.

## INSERT transforms

Location: `transform_insert.cpp`.

### Partitioned insert

- The optional `TABLE` word is ignored.
- Dynamic partition entries (no value) currently throw `NotImplementedException`; only fully static partition specs are supported.
- Static partition values are appended as trailing projected columns by wrapping the insert source in a subquery and selecting `*` plus the constants.
- This assumes Spark partition column ordering at the target; preserve the current column-list/by-name behavior and test mixed static/dynamic specifications.

### Multi-insert

- Each branch is first built as an InsertStatement with a FROM-less SelectNode holding its projection/filter/grouping/having.
- The shared leading source is copied/grafted into every branch.
- The branches are returned as an existing `MultiStatement`, which the planner executes in order.
- WITH/CTE state is attached so each branch sees the same definitions.

## SELECT and table-reference transforms

Location: `transform_select.cpp`.

### Spark automatic names

- `SparkColumnName` renders names for unaliased expressions, including columns, constants, functions/operators, and nested expressions.
- GROUP BY and ORDER BY references are normalized (whitespace removed, lowercased) and replaced with copies of matching select expressions.
- Grouping-set/CUBE/ROLLUP expressions are aliased consistently, and ORDER BY references to those aliases are rewritten.
- Duplicate group expressions/grouping-set indices are remapped/deduplicated.
- `GROUP BY ()`/empty-star handling can force aggregate semantics where Spark expects one group.

These are whole-SelectNode postprocessing behaviors. A clean API would expose a dialect post-transform hook for a completed SelectNode. Otherwise the dialect must replace the central SimpleSelect/SelectNode transform.

### Generator select items

Top-level, undecorated calls are rewritten to existing DuckDB expressions and companion helpers:

| Spark generator | Rewrite/helper |
|---|---|
| `explode`, `_outer` | `__spark_explode_entries` / `__spark_explode_outer_entries`, then root `unnest(..., max_depth := 2)` |
| `posexplode`, `_outer` | corresponding `__spark_posexplode*_entries`, then struct-expanding unnest |
| `inline`, `_outer` | corresponding `__spark_inline*_entries`, then struct-expanding unnest |
| `json_tuple(json,k...)` | one `__spark_json_tuple_value(json,key)` per `cN` struct field, then unnest |
| `stack(n,e...)` | build row-major `struct_pack` rows, `list_value`/`list_resize`, then struct-expanding unnest |

Only bare calls with expected arity and without schema qualification, alias, DISTINCT, FILTER, ordering, or named arguments are rewritten. Aliased scalar explode forms are left to extension macros where appropriate.

`generator(...) AS (c1,c2,...)` uses each entries helper, `list_transform`, positional `struct_extract_at`, deduplicated struct field names, and root `unnest(max_depth := 2)`.

`stack` in table-function position is rewritten as a subquery around the same generator expression; table and column aliases carry over. The row count must be a positive integral constant. Missing final cells become NULL, and `list_resize` supplies all-NULL rows when the requested count exceeds materialized rows.

### VALUES

- Bare VALUES and VALUES-with-alias become ordinary `SelectStatement`/expression-list structures.
- Output columns are assigned Spark names `col1`, `col2`, ... rather than DuckDB's defaults.
- Inline `AS` aliases inside a VALUES row are cleared because Spark still derives the column names from position.

### Joins

- Unqualified joins receive a literal TRUE condition, preserving Cartesian semantics for any join type.
- `JOIN LATERAL` becomes an inner join with TRUE; correlation is left for the binder.
- `LEFT SEMI`/`LEFT ANTI` map to existing `JoinType::SEMI`/`ANTI`.
- A qualified CROSS JOIN is converted to an ordinary inner join when it has an ON/USING qualifier.

### Correlated stars and FROM-less star subqueries

The refreshed branch contains three related compatibility rewrites:

- A `(SELECT *)` with no FROM and no cardinality-changing clauses represents Spark's one-row/zero-column relation. When used in a FROM list, it is an identity cross product and is dropped.
- A qualified star in a subquery that names an **outer** relation is replaced by `unnest(ColumnRef(relation))`, because DuckDB's local star binding cannot expand outer bindings but a column reference can resolve them.
- The same outer-qualified-star rewrite runs for lateral and ordinary subquery references. It first collects names supplied by the subquery's own FROM clause and only rewrites a plain qualified star whose relation is absent. Ambiguous unnamed refs suppress the rewrite.
- Stars with more qualification levels also lower through an unnest-style expression because `StarExpression` carries only one relation name.

These rewrites rely on existing AST but occur before binding. They need focused correlation tests because name visibility and alias hiding are subtle.

### Grouping and ordering

- `WITH CUBE`, `WITH ROLLUP`, and trailing GROUPING SETS are expanded into DuckDB `GroupByNode` grouping sets.
- Ordinals are resolved against the select list before set expansion.
- `grouping__id` is constructed with DuckDB's grouping operator and the Spark alias.
- `SORT BY` uses the same parsed order modifier as ORDER BY.
- CTE `MAX RECURSION LEVEL` is accepted and ignored.

## SET transforms

Location: `transform_set.cpp`.

- Value-less `SET key` → `SELECT current_setting('key')`.
- Dotted identifiers are joined into one setting name.
- Arbitrary raw Spark configuration values that do not parse as ordinary expressions are retained through the fork's manual set parsing path; inspect `TransformSetAssignment` when porting.
- `SET TIME ZONE INTERVAL ...` wraps an interval expression in companion helper `__spark_interval_timezone`.

## Companion extension contracts

The parser port alone is insufficient. The following names appear in lowered AST and must be registered by the Spark compatibility extension with matching signatures/semantics:

- `__spark_add_calendar_interval`
- `__spark_regexp_replace_position`
- `__spark_interval_timezone`
- `__spark_explode_entries`, `__spark_explode_outer_entries`
- `__spark_posexplode_entries`, `__spark_posexplode_outer_entries`
- `__spark_inline_entries`, `__spark_inline_outer_entries`
- `__spark_json_tuple_value`
- all `spark_describe*` table functions listed above
- scalar compatibility macros/functions used by existing aliased generator paths

Build parser tests with the extension loaded; otherwise successful parsing may still fail during binding.
