# Tasks: declarative-intent-hardening

## 1. B1 — Matcher kind whitelist

- [x] 1.1 Extend `schemas/semantic-type-catalog.schema.json`: matcher kind enum gains `prefixed`, `suffixed`, `valueShape`; catalog-level `valueShapes` section; `regex` kind requires non-empty `justification`. Extend the loader model (`registry_loader.py`) to parse the new kinds and valueShapes.
- [x] 1.2 Implement named-kind compilation in `agent/sap_nexus_agent/extraction/_matching.py`: `prefixed` (value after prefix token), `suffixed` (value before suffix token), `valueShape` (reference to `valueShapes` entry), keeping capture-group semantics identical to the regex path.
- [x] 1.3 Add `valueShapes.plantCode: '^[A-Z0-9]{4}$'` to `registry/semantic-types.yaml`; rewrite the Plant prefixed/suffixed matcher with `prefixed: [在]` + `suffixed: [工厂]` + `valueShape: plantCode`; keep the bare-code fallback as a regex matcher with a `justification` (guarded bare scan cannot be expressed by named kinds).
- [ ] 1.4 `scripts/validate-registry-contract.py`: reject regex matchers without justification; print the total regex-matcher count across the semantic-type catalog and capability-level matchers as an observable metric.
- [ ] 1.5 Add `pattern: '^[A-Z0-9]{4}$'` to `MM.PR.CreateDraft.plant` after grepping all eval cases to confirm none depends on the previously loose validation. Verify equivalence: matcher_cases 23/23 and full agent pytest stay green.

## 2. B2 — Clarify de-enumeration

- [ ] 2.1 Extend `schemas/capability.schema.json` clarifyPrompt: `strategy` (enum: `groupByBindingKind`) and `maxRounds` (default 2); `cases` becomes optional override documented as such.
- [ ] 2.2 Restructure `MM.PR.CreateDraft` clarifyPrompt to `strategy: groupByBindingKind` + `maxRounds: 2` (no hand-written case enumeration); keep `MM.Inventory.GetAvailability` cases as the override mechanism.
- [ ] 2.3 Implement strategy rendering in `agent/sap_nexus_agent/extraction/clarify.py`: group missing fields by binding source group, render one prompt per group from `intent.fieldNames` templates, exact missing-set `cases` override checked first, fallback on budget exhaustion.
- [ ] 2.4 Add clarify-round budget tracking to the turn state (single-shot today); budget exhaustion degrades to the declared `fallback` template.
- [ ] 2.5 Tests: PR (6 required fields) covering missing 1 / 2 / 3+ fields — assert clarify rounds never exceed `maxRounds` and one prompt carries all missing fields of a group. Existing clarify tests must stay green (cases override path).

## 3. B3 — Extraction generalized to binding

- [ ] 3.1 Extend `schemas/extraction-declaration.schema.json`: `binding.sources[]` with kinds `userUtterance`, `capabilityOutput` (factType + field), `default` (value); keep `extraction` as a deprecated alias shape; validator emits a warning per `extraction:` usage with migration guidance.
- [ ] 3.2 Loader normalization: `extraction:` parses into a single-`userUtterance`-source binding; engine resolves sources in priority `capabilityOutput > userUtterance > default`.
- [ ] 3.3 Implement the `capabilityOutput` branch as NotImplemented with a clear error; add an xfail test pinning the future landing point (fails with not-implemented reason until the branch exists).
- [ ] 3.4 Tests: binding priority ordering (capabilityOutput beats userUtterance; default fills only when nothing else does), alias warning emitted by validator, xfail placeholder test.

## 4. Closeout

- [ ] 4.1 Full verification: `validate-registry-contract.py` passes and prints the regex count; pytest green (incl. new xfail placeholder); matcher_cases 23/23; frontend verify unaffected; `openspec validate --all --strict` green.
- [ ] 4.2 Verify the declarative-intent-extraction spec delta scenarios map 1:1 to the new tests; commit per-item commit series with test names and root causes in messages.
