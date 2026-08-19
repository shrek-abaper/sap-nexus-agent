# Brainstorm Summary

- Change: declarative-intent-extraction
- Date: 2026-08-18

## Confirmed Technical Approach

(macro decisions confirmed in open phase - see openspec/changes/declarative-intent-extraction/design.md D1-D7)

- Declarations: capability-level primaryKeywords + per-input extraction matchers inline in capabilities.yaml; shared concept matchers in registry/semantic-types.yaml
- Matcher kinds: keyword / regex / semanticType only
- Value normalization stays code (generic resolvers: date, quantity, text)
- Per-capability migration seam, order PR -> Inventory -> PO, single-turn + sticky together
- CLARIFY: deterministic template in rule mode; optional grounded LLM rephrase in llm/hybrid with template fallback
- Strict transition parity; end state = all three capabilities declaration-driven, legacy code deleted

## Deep-design findings from code reading (2026-08-18, CONFIRMED by user)

1. Ambiguity detection requires primary vs weak keyword distinction
   (intent.py _detect_keyword_ambiguity: matched>=2 and primary==0 -> SHOW_OPTIONS
   ambiguity). Declaration schema needs `weakKeywords` (participate in ambiguity
   counting only, never trigger). => Spec Patch candidate.
2. PR has cross-field conditional dependency: cost_center extracted only when
   acct_assgn_cat == "K" (keyword-to-constant mapping via 间采/账号分配), and
   cost_center conditionally appended to missing. DSL needs matcher `value`
   (constant mapping) and `when` (field condition) attributes - not new kinds.
   => Spec Patch candidate (conditional extraction scenario).
3. `excludes` semantics are VALUE-based (extracted value must not equal excluded
   fields' values), not span/token claiming. Simplifies engine vs open-phase D2
   wording. => Spec Patch candidate (correct ambiguous description).
4. Inventory clarification is a fixed missing-combination map (3 exact strings);
   PR is a join-list with per-field display names. clarifyPrompt needs
   `cases` (exact missing-set -> text) + `fallback` (join template + fieldNames).
5. Inventory plant extraction = ordered primary pattern + bare-code fallback
   (lookaround-guarded); material = token scan with value filters (len>4,
   value not in excluded, not BAPI_ prefix, uppercase compare). Catalog entry
   schema needs ordered matcher list + value filters vocabulary.
6. PR plant pattern differs from inventory plant (工厂-prefixed only) - same
   semanticType, capability-level override; already supported by D1 design.
7. PO primary keyword is a regex with lookarounds (PO boundary) -
   primaryKeywords entries must be treated as regex (plain strings compatible).

## Key Trade-offs and Risks

- [Risk] regex-as-data backtracking -> load-time guard + bounded sample timeout
- [Risk] parity drift on subtle semantics (value-exclusion, conditional missing)
  -> committed fixture tables per capability; differential harness
- [Risk] clarify text byte-parity (3-case inventory map, PR join format)
  -> cases/fallback template structure reproduces both exactly

## Testing Strategy

- Differential parity harness: legacy vs engine on committed fixture tables
  (utterance -> decision/parameters/clarification), kept as permanent
  regression tests after legacy deletion (assert against frozen tables)
- Validator unit tests: compile failure, backtracking guard, dangling
  semanticType ref, locale incompleteness, duplicate catalog id
- Gateway indifference test: registry with extraction metadata loads unchanged
- Fixture capability (declarations only, no code) end-to-end rule-mode test
- Full agent suite + call-plan eval green at every step

## Spec Patches

(CONFIRMED by user 2026-08-18; S1-S6 proposal accepted as presented)
- declarative-intent-extraction spec: add weakKeywords to trigger/ambiguity
  requirement; add conditional extraction (when/value/requiredWhen) scenario;
  correct exclusion semantics description to value-based; clarifyPrompt
  cases/fallback rendering scenarios
- registry-ontology-contract delta: validator requirement additions for
  weakKeywords/when/value structure validation
