# Fork-free porting checklist

This checklist turns the inventory into an implementation sequence. It assumes DuckDB contains the `DialectExtension` API from [`78565bf41debaa0bcacd07f439159905ce229513`](https://github.com/Tishj/duckdb/commit/78565bf41debaa0bcacd07f439159905ce229513) or a compatible descendant.

Use [`fork-vs-upstream-c5481653bb.diff`](./fork-vs-upstream-c5481653bb.diff) as the behavioral reference, not as a patch to apply to current DuckDB.

## Phase 0: freeze behavior and establish tests

- [ ] Record the exact target DuckDB commit that contains `DialectExtension`; the API reference commit and the fork merge base are different histories.
- [ ] Build the refreshed fork at `bbe815157f35048effc44e69bdf0b10da33052a6` with the companion Spark extension and capture expected outputs/errors.
- [ ] Add extension-level sqllogictests for every row of the feature matrix below. The net fork diff contains no tests.
- [ ] Separate parser success tests from bind/execute tests; the latter require the companion `__spark_*` helpers.
- [ ] Establish differential tests: same Spark SQL against the fork and dialect extension, comparing parsed AST serialization where possible and query result/error otherwise.

## Phase 1: prove the dynamic-transform surface

Before porting the large grammar, build a small loadable dialect experiment that proves:

- [ ] `AddRule` plus a transform can produce each needed core category: expression, statement, query node, and table ref.
- [ ] `SetTransform`/`ReplaceRule` can traverse child `ParseResult` values using public APIs.
- [ ] Extension-owned intermediate types can be stored in and retrieved from `TransformResultValue`, or transforms can be designed without them.
- [ ] The extension can serialize an existing QueryNode for DESCRIBE QUERY.
- [ ] The extension can construct all existing AST node types used by the fork without private headers/symbols.
- [ ] Grammar choice insertion can target the required position; PEG alternatives with overlapping prefixes are order-sensitive.

Stop and add upstream APIs for any failed item before copying fork transformer code.

## Phase 2: lexical layer

- [ ] Implement/choose the dialect keyword helper after grammar mutation.
- [ ] Port keyword class changes.
- [ ] Implement nested block comments.
- [ ] Implement escaped-quote token boundaries.
- [ ] Implement `>`-run splitting.
- [ ] Implement run-aware keyword/operator matchers and the single close-angle terminal.
- [ ] Implement backtick identifiers with explicit tests for whitespace and escaped backticks.
- [ ] Implement string literal quote/continuation/hex behavior and dialect-specific escape decoding.
- [ ] Implement glued numeric suffix matching and strict validation.
- [ ] Confirm the stock DuckDB dialect is unchanged when `current_dialect` is not Spark.

Gate: nested types, all operator spellings, strings, backticks, and numeric postfixes parse identically before continuing.

## Phase 3: isolated grammar features

Port new rules that lower directly to existing AST and have limited overlap first:

- [ ] angle-bracket ARRAY/MAP/STRUCT types;
- [ ] CREATE/DROP DATABASE aliases;
- [ ] DECLARE/DROP VARIABLE;
- [ ] EXPLAIN modes;
- [ ] RLIKE, TIMESTAMPDIFF, SUBSTR, alternate EXTRACT/POSITION forms;
- [ ] prefix `!`, `DIV`, bitwise precedence;
- [ ] interval range and multi-unit forms;
- [ ] MINUS and SORT BY;
- [ ] LEFT SEMI/ANTI and unqualified joins;
- [ ] value-less/dotted SET and time-zone intervals.

Gate: each new rule has a direct grammar test, AST/lowering test, and at least one negative ambiguity test.

## Phase 4: statement rewrites

- [ ] CREATE TABLE USING/LOCATION/comments/typed partitions.
- [ ] CREATE VIEW columns/schema modes.
- [ ] ALTER TBLPROPERTIES.
- [ ] ANALYZE TABLE/partition/compute-statistics forms.
- [ ] DESCRIBE table/column/query/function routing.
- [ ] INSERT TABLE/static/dynamic partitions.
- [ ] Multi-insert.

Gate: verify ignored clauses really are intentional and documented. Compatibility syntax that silently discards state (`USING`, `LOCATION`, non-comment properties, schema modes, statistics scopes, recursion level) should have tests that make this visible.

## Phase 5: central expression and SELECT rewrites

- [ ] Function null treatment and ordered-set aggregates.
- [ ] Hidden higher-order-function lambdas.
- [ ] regexp replacement and calendar interval helper routing.
- [ ] Spark row/struct naming and star argument unpacking.
- [ ] LIKE ANY/ALL and default escape.
- [ ] automatic select output names and GROUP/ORDER references.
- [ ] grouping set/CUBE/ROLLUP changes and `grouping__id`.
- [ ] VALUES naming/alias behavior.
- [ ] generator rewrites for explode/posexplode/inline/json_tuple/stack.
- [ ] generator multi-column aliases and table-position stack.
- [ ] FROM-less zero-column star relations.
- [ ] correlated outer-qualified star expansion.

Gate: run binder/execution differential tests. These rewrites are the highest-risk portion because they replace or postprocess central transforms.

## Phase 6: remove fork infrastructure

- [ ] Remove parser namespace materialization and custom CMake object libraries.
- [ ] Remove fork-local global ParserCache and honor DuckDB's dialect-aware cache.
- [ ] Remove generated global grammar/transformer modifications.
- [ ] Resolve `split_part` independently (extension macro or upstream fix).
- [ ] Confirm the extension links against stock DuckDB headers/libraries.
- [ ] Confirm switching `current_dialect` repeatedly on multiple connections selects isolated cached grammars.
- [ ] Compare the remaining fork diff with its merge base; only unrelated metadata should remain before archiving the fork.

## Feature test matrix

### Keywords and identifiers

- [ ] `ALL`, `ANY`, `SOME` as identifiers and aggregate names.
- [ ] `MINUS`/`SORT` reserved behavior.
- [ ] every newly accepted type/function keyword in function and identifier positions.
- [ ] backtick identifiers with punctuation, whitespace, keywords, qualifiers, and invalid termination.

### Types and literals

- [ ] nested ARRAY/MAP/STRUCT angle types, including adjacent closing brackets.
- [ ] all numeric postfixes, upper/lower case, glued/separated, overflow and malformed values.
- [ ] ordinary/double/adjacent/hex strings and full escape matrix.
- [ ] incomplete DATE/TIMESTAMP typed literals.
- [ ] interval single-unit, multi-unit, year-month ranges, every day-time range, external/internal signs, fractions, overflow, and invalid fields.

### Expressions

- [ ] `!`, bitwise precedence, shifts, `DIV` with positive/negative/integer/decimal/zero operands.
- [ ] LIKE/ILIKE default and explicit ESCAPE; ANY/ALL/NOT combinations; RLIKE.
- [ ] TIMESTAMPDIFF, EXTRACT comma, POSITION comma/start, SUBSTR.
- [ ] ROW/STRUCT/parenthesized aliases and stars.
- [ ] named parameters whose names are reserved words.
- [ ] trailing and inner null treatment, duplicates, unsupported functions, windows.
- [ ] ordered-set aggregate validation and descending percentiles.
- [ ] higher-order functions with real lambdas and constant expressions in lambda slots.

### Statements

- [ ] DATABASE aliases.
- [ ] CREATE TABLE permutations of USING, LOCATION, partition/sort, comments, WITH, AS.
- [ ] typed and untyped partition fields; column comments.
- [ ] CREATE VIEW columns/comments/all schema modes.
- [ ] SET/UNSET TBLPROPERTIES with comment, other keys, IF EXISTS, case variants.
- [ ] ANALYZE TABLE and every compute-statistics scope.
- [ ] DECLARE initialization forms/missing value/type/OR REPLACE and DROP variants.
- [ ] all DESCRIBE and EXPLAIN modes.
- [ ] INSERT TABLE, column order modes, mixed static/dynamic partitions.
- [ ] multi-insert with CTEs, filters, grouping, multiple branches and aliases.
- [ ] dotted/value-less SET, raw config values, timezone interval forms.

### Queries and generators

- [ ] MINUS, bare/aliased VALUES, VALUES field aliases, output `colN` names.
- [ ] every qualified/unqualified/cross/lateral/semi/anti join combination.
- [ ] grouping modifiers, duplicate expressions, ordinals, auto-names, ORDER/SORT references.
- [ ] MAX RECURSION LEVEL acceptance.
- [ ] explode family on arrays/maps/null/empty/nested structs, aliased and unaliased.
- [ ] json_tuple with one/many keys and default `cN` columns.
- [ ] stack row counts, incomplete rows, NULL fill, invalid/nonconstant counts, SELECT and FROM positions.
- [ ] generator `AS (c1,...)`, wrong alias counts, duplicate aliases, invalid non-generator use.
- [ ] `(SELECT *)` with and without clauses in FROM.
- [ ] outer-qualified stars with local name shadowing, aliases, multiple FROM entries, lateral and non-lateral correlation.

## Known API/design questions to resolve

1. Can a dialect customize keyword **classes**, not just recognize words appearing in new grammar?
2. Can a custom tokenizer reuse the base loop while changing only three state behaviors?
3. Can a custom matcher factory delegate to the stock factory and replace protected terminal behavior without copying it?
4. Can terminal overrides return dialect-owned parse-result objects and decoding logic?
5. Are extension-owned intermediate transformer types safe across the loadable extension ABI?
6. Is there a post-transform hook for FunctionExpression/SelectNode, or must the dialect replace central upstream transforms?
7. Can transforms call reusable default transform functions for unchanged alternatives?
8. Can dynamic grammar rules express the equivalent of `AngleBrackets(D)` without changing the generator?
9. Are AST serialization APIs used by DESCRIBE QUERY public and version-stable enough for an extension?

Answer these explicitly in the port's design notes. A “no” does not necessarily block migration, but it identifies where a small upstream API improvement is preferable to duplicating the parser.

## Completion definition

The migration is complete when:

- stock DuckDB plus the Spark extension accepts the documented syntax after selecting the Spark dialect;
- the default DuckDB dialect's parser behavior is unchanged;
- companion helpers bind and execute the lowered AST;
- the differential suite covers the matrix above;
- no copied/namespaced DuckDB parser, parser cache override, generated core transformer edit, or shared parse-result edit remains.
