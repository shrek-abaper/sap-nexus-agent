# Brainstorm Summary

- Change: declarative-intent-hardening
- Date: 2026-08-19

## Confirmed Technical Approach

- B1 named matcher kinds compiled to bounded regexes: `prefixed` (value after
  prefix token), `suffixed` (value before suffix token), `valueShape` (named
  shape from catalog-level `valueShapes`; bare scan carries alnum boundary
  guards as general semantics). Plant = prefixed matcher (在) + suffixed
  matcher (工厂), both with `valueShape: plantCode`, plus ONE justified regex
  for the bare-code fallback (digit guards) to keep exact equivalence.
  `regex` kind requires `justification`; validator prints total regex-matcher
  count as an observable metric (not a gate).
- B2 clarify `groupByBindingKind` strategy: missing fields grouped by binding
  source group, one prompt per group, copy generated from `intent.fieldNames`
  templates; `cases[]` exact-match override checked first. Round budget
  `maxRounds: 2` tracked per capabilityId, PERSISTED in ConversationReadState
  (durable, replayable); exhaustion degrades to `fallback` template.
- B3 new internal `BindingConfig` model (sources[] + elicitIfMissing); loader
  normalizes the deprecated `extraction:` alias into a single `userUtterance`
  source at the parse boundary. Resolution priority capabilityOutput >
  userUtterance > default implemented in resolver ordering; capabilityOutput
  branch raises NotImplemented, pinned by an xfail placeholder test.

## Key Trade-offs and Risks

- Plant bare-code fallback stays a justified regex: escape hatch has a real
  use case, regex count >0 is normal, exact behavior equivalence holds.
- Round state in durable read state adds a schema field but gives maxRounds a
  real runtime meaning across turns.
- BindingConfig + deprecated ExtractionConfig coexist during migration; the
  alias is removed in a follow-up once all declarations migrate.
- valueShape `^[A-Z0-9]{4}$` is looser than the legacy extraction regex
  `[A-Z]\d{3}|\d{4}` for letter-mixed codes; extraction and input validation
  become consistent; no existing eval case depends on the legacy strictness
  (verified by grep before implementation).

## Testing Strategy

- Plant equivalence hard gate: matcher_cases stays 23/23; parity-pinning tests
  in test_extraction_declarations.py updated to the new kind structures.
- B2: PR (6 required) missing 1 / 2 / 3+ fields — rounds <= maxRounds, one
  prompt carries all group fields; synthetic two-group fixture exercises the
  runtime budget branch and fallback degradation.
- B3: binding priority tests (capabilityOutput beats userUtterance, default
  fills last), alias warning emitted by validator, xfail placeholder for the
  NotImplemented capabilityOutput path.
- Full agent pytest, frontend verify, registry contract validation.

## Spec Patches

None — the delta spec scenarios cover all three items as written.
