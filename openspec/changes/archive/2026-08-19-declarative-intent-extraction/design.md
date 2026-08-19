# Design: declarative-intent-extraction

## Context

The rule intent path is the last registry-blind part of the agent: recall,
LLM prompt building, and narration are already catalog-driven, while
capability triggering and slot filling live as hardcoded Python
(`intent.py` keyword sets and builders, `pr_intent.py`, sticky-continuation
dispatch in `llm_intent.py`). The registry already declares per-input
`semanticName`/`semanticType`/`pattern` for gateway-side validation, so
extraction knowledge currently exists in two places. See proposal.md for
motivation and the two delta specs for normative requirements.

Key constraints:

- All three existing capabilities are migrated to declaration-driven
  definitions in this change; the end state has no hardcoded extraction code.
  Strict parity applies only to the transition: decisions, parameters,
  clarification text, and ambiguity flags must be byte-identical across the
  switch so the baseline stays green and regressions are attributable.
  Post-migration, iterating a capability's extraction behavior is a
  registry-declaration edit, not a code change.
- Closed-set governance: extraction is deterministic agent-side metadata; the
  gateway must remain indifferent to it; LLM-rendered clarifications may only
  reference declared required inputs.
- The agent test baseline (1145 passed) and call-plan eval must stay green
  throughout the migration.

## Goals / Non-Goals

**Goals:**

- A declaration schema whose expressive power exactly covers today's
  hardcoded extraction behavior - no more, until a real capability needs more.
- One generic engine with zero capability branches, shared by single-turn and
  sticky-continuation paths.
- Registry-load-time validation making regex-as-data safe (compile check,
  backtracking guard, reference resolution).

**Non-Goals:**

- Generalizing frontend fact builders, recommendation rule sets, or the
  narrative input projection (separate changes).
- Embedding/vector recall, dynamic planner changes, OWL inference.
- Improving extraction behavior for the three existing capabilities (strict
  parity; known quirks such as lowercase-material handling stay as-is).
- Migrating the LLM intent path's payload schema - only its sticky fallback
  dispatch to rule extraction changes.

## Decisions

### D1: Declaration location - inline per-input `extraction` + capability `primaryKeywords` in capabilities.yaml; concept matchers in a separate registry/semantic-types.yaml

Inline per-input matchers keep slot-filling knowledge next to the input
definition (same file, same version, same snapshot). Concept-level matchers
(`Plant`, `MaterialNumber`, ...) move to a separate catalog because they are
shared across capabilities and belong to the ontology concept layer, matching
the reserved `semanticType` migration path toward OWL.
*Alternatives rejected*: a fully separate rule ontology (three-way version
coupling: rule version vs capability version vs snapshot); putting the
semantic-type catalog inside capabilities.yaml (mixes concept layer with
capability layer, file grows unbounded as capabilities increase).

### D2: Matcher model - three kinds only: `keyword`, `regex`, `semanticType`

`keyword` matches substring presence (trigger detection, vendor-by-keyword
style matching); `regex` is an inline pattern with capture group 1 as the
value; `semanticType` delegates to the catalog entry. Each input's extraction
is an ordered matcher list; the first matcher producing a value wins.
Cross-field exclusion is expressed as `excludes: [input-name, ...]` on the
matcher - tokens already claimed by an excluded field's match are skipped.
Priority ordering comes from declaration order within an input plus
field-level `priority` across inputs of the same capability (higher claims
tokens first), which reproduces today's plant-before-material ordering.
*Alternatives rejected*: a richer DSL (entity types, context windows) - YAGNI;
pure semanticType with no inline escape hatch - some matchers are
capability-specific (PO number vs material disambiguation) and would force
catalog pollution.

### D3: Value parsing stays code - a small fixed set of generic value resolvers

Declaration matchers produce raw string captures; normalization (date
parsing, quantity+unit splitting, uppercase normalization of material codes)
is done by a fixed set of generic resolvers selected by a `resolver` name on
the input declaration (`date`, `quantity`, `text`). Resolvers are
domain-independent utilities, not per-capability code, and their current
behavior is lifted verbatim from the existing extractors to guarantee parity.
*Alternative rejected*: encoding normalization in the DSL (format strings) -
duplicates resolver logic per field and cannot express quantity+unit
co-extraction.

### D4: Engine placement and migration seam - parallel engine behind the adapter, selected per capability

A new module owns the engine; `parse_intent` and the sticky-continuation path
delegate per capability: capabilities whose declarations are marked with
extraction metadata use the engine; anything else falls back to the legacy
hardcoded path (temporary during migration only). This allows per-capability
migration with parity tests comparing both paths on the same utterance sets.
The migration order is PR first (smallest, most self-contained), then
inventory, then PO (most entangled exclusion logic). When all three are
migrated, the legacy branches and `pr_intent.py` are deleted in the same
change - no long-lived dual paths.
*Alternative rejected*: big-bang switch - a single cutover makes parity
failures hard to attribute to a capability.

### D5: CLARIFY rendering - template-first, LLM rephrase as a grounded post-step

`clarifyPrompt` entries are templates with `{field}`/`{example}` placeholders,
rendered deterministically for rule mode. In llm/hybrid modes an optional
rephrase step sends the rendered template plus the declared field list and
requires the model to return a question that mentions only declared missing
inputs; output failing a check against that closed set falls back to the
template. The fallback guarantees the LLM path degrades exactly to rule-path
behavior when the model is unavailable - preserving the hybrid fallback
contract.
*Alternative rejected*: LLM-first clarification - breaks the rule fallback
contract and makes clarification nondeterministic in eval.

### D6: Validation - extend the existing contract validator and JSON Schemas, not a new gate

Extraction declaration validation (compile, backtracking guard via a
length + nested-quantifier heuristic with a bounded sample-input timeout,
semanticType reference resolution, clarifyPrompt locale completeness) is added
to `scripts/validate-registry-contract.py` and mirrored in `schemas/` JSON
Schema for editor/CI feedback. The gateway Java loader continues to ignore
unknown agent-side fields (verified by a gateway test that loads a registry
with extraction metadata).
*Alternative rejected*: runtime-only validation in the agent - moves failure
discovery from CI to conversation time.

### D7: Strict-parity guard - a differential parity harness as a first-class test

Before migrating each capability, freeze its legacy behavior as a table of
utterance -> expected decision/parameters fixtures generated from the current
tests plus an adversarial set (ambiguous, multi-intent, partial params,
override injection, sticky follow-ups). The parity harness runs the same
utterances through legacy and engine paths and asserts identity. The fixture
table is committed, so regressions are attributable per capability.

## Risks / Trade-offs

- [Regex as data enables catastrophic backtracking on adversarial input] ->
  load-time backtracking guard + per-utterance extraction timeout budget in
  the engine (utterance length is bounded by the chat input limit).
- [Declaration order/priority semantics are subtle; exclusion behavior may
  drift silently] -> D7 parity harness pins exact behavior; priority and
  exclusion semantics are documented in the catalog schema and covered by
  validator unit tests.
- [clarifyPrompt templates must reproduce current Chinese clarification text
  byte-for-byte] -> templates are populated from the current `_clarification`
  strings verbatim; parity fixtures include clarification text.
- [Migration touches a 779-line llm_intent.py with entangled sticky logic] ->
  sticky dispatch is isolated behind the same per-capability seam (D4);
  sticky parity fixtures cover overlay merge, new-turn switch, and the
  inventory-specific CLARIFY quirk (kept as a declaration-scoped guard during
  parity, removed only in a follow-up change).
- [Catalog and capabilities can drift across snapshots in cached loads] ->
  atomic load pairing (spec requirement) with snapshot id covering both
  artifacts.

## Migration Plan

1. Add schemas + validator rules + catalog file with entries lifted verbatim
   from current extractors; registry gains declarations (engine not yet
   used) - CI green, zero behavior change.
2. Add engine + parity harness; migrate `MM.PR.CreateDraft`; legacy path
   still handles the other two.
3. Migrate `MM.Inventory.GetAvailability`, then `MM.PurchaseOrder.GetList`
   (single-turn and sticky together per capability).
4. Delete legacy branches and `pr_intent.py`; remove the per-capability seam
   (engine becomes the only path).
5. CLARIFY template rendering is live from step 2 (parity requires it);
   optional LLM rephrase hook lands in step 4.
6. Rollback: each step is a standalone commit; reverting a step restores the
   previous engine/legacy mix. Final state has no legacy path - rollback
   after step 4 means reverting to the step-3 commit.

## Open Questions

- Whether the `excludes` token-claim model needs substring vs full-token
  matching semantics distinction for edge cases beyond today's behavior -
  deferrable; strict parity defines the initial semantics, extension can be
  additive.
- Whether gateway should long-term validate (not just ignore) extraction
  declarations for defense-in-depth - deferrable, does not affect this
  change's contracts.
