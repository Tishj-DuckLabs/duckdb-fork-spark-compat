# Tokenizer and matcher changes

This document separates lexical changes from terminal matcher changes. They are coupled in two places: angle-bracket type closers and numeric suffix adjacency. See [`fork-vs-upstream-c5481653bb.diff`](./fork-vs-upstream-c5481653bb.diff), searching for `base_tokenizer.cpp`, `matcher.cpp`, and the named helpers below.

## Tokenizer changes

### Nested block comments

Location: `BaseTokenizer::TokenizeInputInternal`, search `comment_depth`.

The fork tracks nesting depth after `/*`. Another `/*` increments the depth, and `*/` decrements it. The comment token ends only at depth zero.

Example behavior:

```sql
SELECT 1 /* outer /* inner */ still outer */;
```

API mapping: `DialectExtension::CreateTokenizer` can select a dialect tokenizer, but the changed loop is private base implementation. Unless the API version exposes a state hook for comments, a Spark tokenizer must duplicate/subclass a reusable tokenizer implementation or this behavior must move into upstream core as generally useful SQL lexing.

### Backslash-aware single-quoted strings

Location: `TokenizeState::STRING_LITERAL`.

On `\`, the tokenizer skips the following character so an escaped quote does not terminate the token. Actual escape interpretation happens later in `StringLiteralParseResult`.

Example: `'can\'t'` remains one string token.

API mapping: same limitation as nested comments. This is token-boundary behavior and cannot be implemented only in a string terminal matcher if the base tokenizer has already split the input incorrectly.

### Split `>`-led operator runs

Locations: `BaseTokenizer::PushOperatorToken`, calls from the operator state and `OnLastToken`.

The fork splits leading `>` characters into individual operator tokens while retaining a final `>=` as one token. Examples conceptually become:

| Source run | Tokens |
|---|---|
| `>>` | `>`, `>` |
| `>>>` | `>`, `>`, `>` |
| `>>=` | `>`, `>=` |

This lets nested Spark types such as `ARRAY<ARRAY<INT>>` consume one closer per type. The matcher then reassembles offset-contiguous tokens for expression operators, so `a >> b` still matches a shift.

API mapping: requires the custom tokenizer **and** the run-aware matchers below. Port both together; a partial port will either break nested type closers or change expression operators.

## Matcher changes

### Operator-run reassembly

Locations: `IsGluedOperatorToken`, `ContinuesOperatorRun`, `KeywordMatcher::MatchLiteralAgainstGluedOperatorRun`, and `OperatorMatcher::MatchOperator`.

- Adjacent operator tokens are considered part of one source operator only when their byte offsets are contiguous.
- Keyword matchers (which also represent literal operators in this PEG implementation) compare a grammar literal against the entire glued run.
- The generic operator matcher concatenates the maximal glued run and validates the combined text.
- The match must cover the entire run, preserving maximal-munch behavior.
- Lambda/JSON arrows retain their dedicated grammar roles.

API mapping: implement through a custom `MatcherFactory` or terminal overrides. The dialect factory must preserve all ordinary DuckDB matcher construction behavior while replacing keyword/operator behavior.

### Single close-angle matcher

Locations: `CloseAngleBracketMatcher`, `AddRuleOverride("CloseAngleBracket", ...)`.

This terminal deliberately consumes exactly one `>` token even when it is offset-contiguous with another. It is the inverse of operator reassembly and exists only for `AngleBrackets` type syntax.

API mapping: strong. Use `ParsedGrammar::AddTerminalRuleOverride("CloseAngleBracket", ...)` or the `terminal_rules` supplied to `CreateMatcherFactory`. It still depends on the tokenizer split.

### Backtick identifiers

Locations: `IdentifierMatcher::IsBacktickSequence`, `ConsumeBacktickSequence`, and equivalent reserved-identifier entry points.

The current refreshed branch does **not** tokenize a backtick identifier as one token. Instead, the identifier matchers:

- recognize an opening standalone backtick;
- scan forward to a closing backtick;
- concatenate all intervening token texts without separators;
- return an `IdentifierParseResult` containing the concatenated inner text.

This permits identifiers such as `` `a-b` `` even if the tokenizer split their contents.

Important fidelity questions for the port:

- Concatenating token text discards whitespace between tokens; verify expected Spark behavior for `` `a b` ``.
- The scan begins far enough ahead to require content between backticks; verify empty identifiers and escaped/doubled backticks.
- The matcher mutates the closing token's type in the non-parse-result path.

API mapping: use terminal overrides for `Identifier` and `ReservedIdentifier`, or a custom factory that returns backtick-aware identifier matchers. A future cleaner implementation could tokenize quoted identifiers as one token, but that would be a behavioral rewrite and needs tests.

### Spark string literals

Location: `StringLiteralMatcher`.

Matcher behavior added by the fork:

- ordinary double-quoted tokens are accepted as strings as well as single-quoted tokens;
- adjacent unprefixed string tokens concatenate (`'a' 'b'` becomes `ab`);
- odd-length hex literal payloads receive a leading zero (`X'A'` becomes `X'0A'`);
- ordinary strings are emitted as `SpecialStringCharacter::ESCAPE_STRING`, enabling C-style backslash processing instead of upstream standard-string behavior.

API mapping: terminal override is the right location for quote acceptance, concatenation, hex padding, and choosing a dialect parse-result representation. However, escaped quotes also require the tokenizer change, and Unicode/backslash interpretation currently lives in the core parse-result class (document 04).

Potential semantic collision: Spark uses double quotes according to configuration/context. The fork unconditionally accepts them as string literals in this terminal, while identifier matchers also recognize quoted forms. Preserve PEG choice ordering and add ambiguity tests.

### Numeric postfixes

Locations: `SparkCompatUtils::IsSparkPostfixToken`, `TokenIsGluedToPrevious`, `NumberLiteralMatcher`.

The matcher consumes these suffix tokens only when byte-offset contiguous with a preceding number:

- one-character: `L`, `S`, `Y`, `D`, `F`
- two-character: `BD`

Examples: `2Y` is one typed literal; `2 Y` remains a number followed by an alias/identifier. The number parse result concatenates the suffix for the transformer.

The fork also comments out the per-character rejection in `MatchNumberLiteral`. That broadens what the matcher may accept after its structural checks and should be treated as a risk, not copied blindly. Determine which Spark literals required this relaxation and replace it with explicit validation.

API mapping: strong through a `NumberLiteral` terminal override. The offset-contiguity check requires token offsets, which the matcher has.

### Parser cache changes in matcher.cpp

The same file redirects `PEGMatcher::Get(ClientContext&)` and `Get(DatabaseInstance&)` to a process-wide fork-local `ParserCache::GetDefault()`.

This is **not matcher semantics**. It supports compiling a second namespaced parser beside the host parser. A registered `DialectExtension` already has dialect-specific compiled-grammar caching, so this change should be removed during migration, not reimplemented.

## Suggested extension design

Keep the coupled lexical pieces in one extension-owned component:

1. A Spark tokenizer adds nested comments, escaped-quote boundaries, and `>` splitting.
2. A Spark matcher factory starts from the standard factory behavior and replaces identifier, string, number, operator, keyword-literal, and close-angle terminals.
3. A Spark keyword helper is built after grammar mutation so keyword classes match document 01.
4. String terminal output uses an extension-owned parse result or callback, avoiding a global change to `StringLiteralParseResult`.

If inheriting the stock tokenizer or matcher factory cannot reuse the default implementations, request narrow upstream hooks rather than copying hundreds of lines into the extension. The minimum useful hooks are:

- tokenizer callbacks for block-comment nesting, string escape boundary handling, and operator-token emission;
- protected/default terminal matcher constructors or composable overrides;
- a dialect-specific string-to-expression callback.

## Minimum lexical regression matrix

- nested block comments: valid nesting, unterminated outer/inner comments;
- escaped quotes and trailing backslashes;
- adjacent single and double strings, with/without whitespace;
- odd/even hex strings;
- `\u`, `\U`, surrogate pairs, invalid escapes, `\%`, and `\_`;
- backtick identifiers containing spaces, punctuation, keywords, doubled backticks, and empty content;
- every numeric suffix in both cases, glued and separated;
- `ARRAY<ARRAY<INT>>`, `MAP<STRING,ARRAY<INT>>`, casts followed immediately by `>`, `>>`, `>=`, and `>>=` operators;
- lambdas involving identifiers `all`, `any`, and `some` beside `->`.
