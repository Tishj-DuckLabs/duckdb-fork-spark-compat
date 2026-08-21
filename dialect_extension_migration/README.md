# Spark compatibility parser migration packet

This directory inventories the **net changes in the refreshed `duckdb-fork-spark-compat` branch** that need to be understood when moving Spark SQL compatibility onto DuckDB's `DialectExtension` API.

The comparison is intentionally a merge-base diff, not a comparison with a moving upstream branch:

- repository: [`duckdb/duckdb-fork-spark-compat`](https://github.com/duckdb/duckdb-fork-spark-compat)
- fork tip: `bbe815157f35048effc44e69bdf0b10da33052a6` (`main`, 2026-08-19)
- upstream merge base: `c5481653bb6edc5b24b6dc94d3dcdeeb567034b3` (2026-07-09)
- range: `c5481653bb6edc5b24b6dc94d3dcdeeb567034b3..bbe815157f35048effc44e69bdf0b10da33052a6`
- range size: 164 commits including merges; 64 changed paths; 7,433 insertions and 1,129 deletions
- target API reference: [`DialectExtension` commit `78565bf41debaa0bcacd07f439159905ce229513`](https://github.com/Tishj/duckdb/commit/78565bf41debaa0bcacd07f439159905ce229513)

The complete, no-color, full-index, binary-capable net diff is in [`fork-vs-upstream-c5481653bb.diff`](./fork-vs-upstream-c5481653bb.diff). All source references in these documents are paths and searchable rule/function names in that artifact. Generated grammar and transformer files are included in the diff for completeness, but should be regenerated rather than ported by hand.

Diff artifact verification: 793,809 bytes, 14,089 lines, 64 `diff --git` sections, SHA-256 `cd886320b6c14d2aa4ac232d81738f38cea4fc0f3dca1f10919d6ff948256c42`.

It was generated with:

```sh
git diff --full-index --binary --no-color \
  c5481653bb6edc5b24b6dc94d3dcdeeb567034b3..bbe815157f35048effc44e69bdf0b10da33052a6
```

## Documents

- [`01-grammar-and-keywords.md`](./01-grammar-and-keywords.md) — grammar rules, keyword-class changes, and the expected `ApplyGrammarChanges` mapping.
- [`02-tokenizer-and-matcher.md`](./02-tokenizer-and-matcher.md) — lexical behavior and terminal matcher changes, including API fit and coupling.
- [`03-transformers.md`](./03-transformers.md) — semantic lowering from Spark syntax into existing DuckDB AST nodes and helper functions.
- [`04-non-api-and-core-changes.md`](./04-non-api-and-core-changes.md) — parse-result, helper-AST, generator, cache, namespace/build, and unrelated core changes that are not merely grammar patches.
- [`05-porting-checklist.md`](./05-porting-checklist.md) — proposed dependency order, unresolved API gaps, and a test matrix for a fork-free implementation.

## Classification summary

| Category | What changed | `DialectExtension` fit at `78565bf` |
|---|---|---|
| Grammar rules | Spark DDL/DML statements, type syntax, expressions, joins, grouping, values, settings | Strong. Use `AddRule`, `AddChoice`/`PrependChoice`, `RemoveChoice`, or `ReplaceRule`. |
| Keywords | Five keyword classes changed | Strong. Grammar-derived keyword maps should follow the modified `ParsedGrammar`; verify class changes through the dialect keyword helper. |
| Tokenizer | Nested comments, backslash-aware strings, `>`-run splitting | Partial. `CreateTokenizer` exists, but the fork edits the base tokenization loop; a dialect tokenizer may need to duplicate that loop unless the base class exposes suitable hooks. |
| Matchers | Backticks, Spark strings, numeric suffixes, operator reassembly, single `>` closer | Strong to partial. `CreateMatcherFactory` and terminal overrides cover the behavior, but several changes replace built-in terminal behavior and share assumptions with the tokenizer. |
| Transformers | New rule transforms plus replacements of many existing transforms | Supported in principle through `AddRule(..., transform)` and `SetTransform`; porting requires extension-owned transform functions and access to every required AST/helper type. |
| Parse result | Spark escape decoding was inserted into `StringLiteralParseResult::ToExpression` | Not covered directly. Prefer a dialect-specific string terminal/parse-result or request an API hook; otherwise core changes remain. |
| Helper AST | New intermediate structs and fields used only between matching and transformation | Not an API feature, but these can live in the extension if transform result plumbing accepts extension-owned value types. Otherwise they expose a transformer API gap. |
| Core AST | No persistent `SQLStatement`, `QueryNode`, `TableRef`, or `ParsedExpression` subclass was added | Good news: most semantics lower to existing DuckDB AST types. |
| Parser/build isolation | Entire parser is materialized into `duckdb_fork`; fork-local global parser cache | Fork infrastructure, not functionality. Delete rather than port once the dialect can coexist with the host parser. |
| Non-parser core | `split_part` macro parameter renamed from `string` to `str` | Outside the dialect API. Determine whether the extension still needs this compatibility fix. |

## What the API provides

At the referenced API commit, a dialect can:

- mutate a `ParsedGrammar` in `ApplyGrammarChanges`;
- add or replace rules and their transform callbacks;
- attach terminal matcher overrides;
- supply a custom `MatcherFactory`, `Tokenizer`, and `PEGKeywordHelper`;
- select the dialect per connection through `current_dialect` and cache its compiled grammar.

The important constraint is that grammar extensibility and semantic extensibility are separate. Adding a Spark alternative to an existing rule is straightforward; changing the meaning of an existing alternative still requires replacing that rule's transform. The extension must reproduce the upstream behavior for untouched alternatives or delegate to reusable upstream helpers. This is especially relevant to `FunctionExpression`, `SelectNode`, `InsertStatement`, `CreateTableStmt`, `SetStatement`, and expression-precedence rules.

## Reading the full diff

Useful searches in [`fork-vs-upstream-c5481653bb.diff`](./fork-vs-upstream-c5481653bb.diff):

```text
diff --git a/src/parser/peg/grammar/       grammar source changes
diff --git a/src/parser/peg/tokenizer/     tokenizer changes
diff --git a/src/parser/peg/matcher.cpp    matcher changes
diff --git a/src/parser/peg/transformer/   transformer source and generated output
diff --git a/src/include/duckdb/parser/peg/ast/  helper AST changes
StringLiteralParseResult                   parse-result escape changes
materialize_fork_namespace                 fork-only parser isolation
```

The inlined grammar, `peg_transformer.hpp`, `transform_generated.cpp`, `transform_generated_trampoline.cpp`, and generated CMake lists contain mechanical consequences of source grammar/type changes. The authoritative inputs are the `grammar/statements/*.gram` files, keyword lists, `scripts/parser/grammar_types.yml`, hand-written transformer files, tokenizer, and matcher.

## Scope caveats

- This is a **net-diff inventory**. Changes added and later reverted within the 164-commit range are intentionally absent.
- The comparison contains no changed test files. The fork's behavior is therefore documented from implementation and commit intent; the port should add extension-level regression tests before removing fork code.
- Runtime helpers named `__spark_*` and `spark_describe*` are expected to be registered by the companion extension. Their implementations are outside this repository diff, but their parser-side contracts are listed in the transformer document.
- Metadata changes (`README.md`, `.gitignore`) are preserved in the full diff but do not belong in the parser port.
