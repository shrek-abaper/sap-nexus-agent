# Tasks: declarative-intent-extraction

## 1. Declaration Schema and Validation (zero behavior change)

- [x] 1.1 Define JSON Schema for capability extraction declarations (`primaryKeywords`, per-input `extraction` matchers with `keyword`/`regex`/`semanticType` kinds, `excludes`, `priority`, `resolver`, `clarifyPrompt` locale map) in `schemas/`
- [x] Define JSON Schema for the semantic-type extraction catalog `registry/semantic-types.yaml` (versioned root, semantic type id, matcher list, priority)
- [x] Create `registry/semantic-types.yaml` with entries lifted verbatim from current extractors (Plant, MaterialNumber, Quantity+unit, Date, vendor/purchasing-group as applicable)
- [x] Add extraction declaration + catalog validation to `scripts/validate-registry-contract.py`: regex compile check, backtracking-safety guard (length + nested-quantifier heuristic with bounded sample timeout), semanticType reference resolution, clarifyPrompt locale completeness for required inputs, duplicate catalog id rejection
- [x] Add extraction declarations to the three existing capabilities in `registry/capabilities.yaml` with strict-parity values (keywords, patterns, priorities, exclusions, clarifyPrompt text copied verbatim from current code strings)
- [x] Add a gateway test proving registry loading with extraction metadata leaves gateway behavior unchanged
- [x] Verify: `openspec list --json && openspec validate --all --strict`, registry contract validation, agent test baseline all green

## 2. Extraction Engine and Parity Harness

- [x] Load extraction declarations and the semantic-type catalog atomically in the agent registry loader; snapshot id covers both artifacts
- [x] 2.2 Implement generic value resolvers (`date`, `quantity`, `text`) lifted verbatim from current extractor logic
- [ ] 2.3 Implement the generic extraction engine: primary-keyword trigger scan, ordered matcher evaluation, token claiming with `excludes` and `priority`, MatchedIntent production - zero capability branches
- [ ] 2.4 Build the differential parity harness: committed utterance fixtures (single-intent, multi-intent, ambiguous, partial params, technical override, sticky follow-ups) asserting identical decisions/parameters/clarification text between legacy path and engine
- [ ] 2.5 Wire the per-capability seam in `parse_intent` and sticky continuation: declared capabilities dispatch to the engine, undeclared fall back to legacy (migration-only)

## 3. Per-Capability Migration (strict parity, single-turn + sticky together)

- [ ] 3.1 Migrate `MM.PR.CreateDraft` to the engine; parity harness + full agent suite green
- [ ] 3.2 Migrate `MM.Inventory.GetAvailability` to the engine (including sticky material-CLARIFY quirk preserved via declaration-scoped guard); parity harness + full agent suite green
- [ ] 3.3 Migrate `MM.PurchaseOrder.GetList` to the engine (exclusion-heavy PO number logic); parity harness + full agent suite green

## 4. Legacy Removal and CLARIFY Rendering

- [ ] 4.1 Render CLARIFY text from `clarifyPrompt` templates deterministically in rule mode (template rendering live for all migrated capabilities; parity includes clarification text)
- [ ] 4.2 Add optional LLM rephrase step for llm/hybrid modes: grounded to declared missing inputs, closed-set output check, template fallback on timeout/malformed/unavailable
- [ ] 4.3 Delete legacy branches in `intent.py`, remove `pr_intent.py`, remove the per-capability seam; engine is the only extraction path
- [ ] 4.4 Add a test-only fixture capability registered with declarations only (no code) proving rule-mode recognition, slot filling, and CLARIFY end to end

## 5. Closeout Verification

- [ ] 5.1 Full verification sweep: `git status --short`, agent test suite, call-plan eval (`PYTHONPATH=agent scripts/verify-agent-callplan-evidence.sh`), registry contract validation, frontend untouched check
- [ ] 5.2 Update README/docs references to the rule path architecture (declarative extraction, catalog location) and record parity baseline in the change's verification notes
