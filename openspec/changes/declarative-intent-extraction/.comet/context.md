# Comet Design Handoff

- Change: declarative-intent-extraction
- Phase: design
- Mode: compact
- Context hash: d2310029b57deb3ec78ddaa19c8713f0a1473ef41d89241ce169544377a6270c

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/declarative-intent-extraction/proposal.md

- Source: openspec/changes/declarative-intent-extraction/proposal.md
- Lines: 1-85
- SHA256: b4b3b1eb6607931f6a8a65bc143b274a9c468859cbb53160fbc2260efc716fe2

[TRUNCATED]

```md
# Proposal: declarative-intent-extraction

## Why

The rule-based intent path hardcodes per-capability keyword sets and regex
extractors in Python (`agent/sap_nexus_agent/intent.py`, `pr_intent.py`, and the
sticky-continuation branches in `llm_intent.py`). Every newly registered
capability currently requires new hand-written code before it is visible in
`--intent-mode rule`, which defeats the project's "capability as boundary -
registration, not code" principle and diverges from the already
declaration-driven recall, LLM prompt, and narrator paths.

## What Changes

- Extend the capability registry declaration with intent-extraction metadata:
  `primaryKeywords` (capability trigger), per-input `extraction` matchers
  (keyword/regex/semanticType reference), and per-input `clarifyPrompt`
  (locale-keyed CLARIFY text).
- Add a shared semantic-type extraction catalog (`registry/semantic-types.yaml`)
  defining concept-level matchers (`Plant`, `MaterialNumber`, `Quantity`,
  `Date`, ...) that capabilities reference by `semanticType`, so field-level
  extraction knowledge is defined once and reused.
- Add a generic declaration-driven extraction engine in the agent that replaces
  the hardcoded keyword-scan branches, per-capability builders
  (`_build_inventory_result`, `_build_purchase_order_result`,
  `parse_pr_create_intent`), and the sticky-continuation
  `_extract_params_for`/`_PRIMARY_KEYWORD_SETS` dispatch. The engine has no
  capability-specific branches.
- Make CLARIFY prompts declaration-driven: deterministic template rendering
  from `clarifyPrompt` in rule mode; optional LLM rendering grounded to the
  declared prompt in llm/hybrid modes (LLM may only ask about declared required
  inputs, never invent fields).
- Extend registry contract validation (Python + JSON Schema) to validate
  extraction declarations: regex compile check, backtracking-safety guard,
  `semanticType` reference resolution against the catalog, `clarifyPrompt`
  locale completeness for required inputs.
- Strict behavior parity: all three existing capabilities
  (`MM.Inventory.GetAvailability`, `MM.PurchaseOrder.GetList`,
  `MM.PR.CreateDraft`) are migrated to declaration-driven definitions in this
  change - after migration their extraction behavior is defined solely by
  registry declarations, and the legacy hardcoded path is fully removed.
  Parity constrains only the migration transition: extraction and decision
  results MUST remain identical before and after the switch (no opportunistic
  fixes); `pr_intent.py` is removed and `intent.py` loses its hardcoded
  keyword sets and extractors.

## Capabilities

### New Capabilities

- `declarative-intent-extraction`: declaration-driven intent extraction -
  registry extraction declarations, shared semantic-type extraction catalog,
  generic extraction engine, and declaration-driven CLARIFY rendering, such
  that a capability registered with extraction declarations is fully usable in
  rule mode without agent code changes.

### Modified Capabilities

- `registry-ontology-contract`: the registry contract validator gains
  requirements for extraction declaration validation (matcher schema,
  `semanticType` catalog reference resolution, regex compile/backtracking
  guards, `clarifyPrompt` locale completeness) and for the new
  `registry/semantic-types.yaml` catalog contract.

## Impact

- **Registry**: `registry/capabilities.yaml` (three existing capabilities gain
  extraction declarations with strict-parity values),
  new `registry/semantic-types.yaml`.
- **Schemas/validator**: `schemas/` JSON Schema for extraction declarations and
  the semantic-type catalog; `scripts/validate-registry-contract.py` rules.
- **Agent**: `agent/sap_nexus_agent/` - `intent.py` (hardcoded branches ->
  engine dispatch), `pr_intent.py` (removed), `llm_intent.py`
  (sticky-continuation extraction -> engine dispatch; CLARIFY LLM rendering
  hook), `registry_loader.py` (load extraction declarations + catalog),
  new extraction engine module.
- **Gateway**: no runtime behavior change; extraction declarations are
  agent-side metadata the gateway loader may ignore or pass through.
- **Tests/evals**: existing agent tests (1145 passed baseline) and call-plan
  eval must stay green unchanged; new tests cover the engine, validator

```

Full source: openspec/changes/declarative-intent-extraction/proposal.md

## openspec/changes/declarative-intent-extraction/design.md

- Source: openspec/changes/declarative-intent-extraction/design.md
- Lines: 1-186
- SHA256: 08a49fd7211cbae5ce10a29491715f59348f6ba8e017f2b0124e66ea8cf936b3

[TRUNCATED]

```md
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

```

Full source: openspec/changes/declarative-intent-extraction/design.md

## openspec/changes/declarative-intent-extraction/tasks.md

- Source: openspec/changes/declarative-intent-extraction/tasks.md
- Lines: 1-37
- SHA256: 4128f7c7fc2d21e63d5354039685e73f39b6c019e1b5e24f9700ebc12af24afb

```md
# Tasks: declarative-intent-extraction

## 1. Declaration Schema and Validation (zero behavior change)

- [ ] 1.1 Define JSON Schema for capability extraction declarations (`primaryKeywords`, per-input `extraction` matchers with `keyword`/`regex`/`semanticType` kinds, `excludes`, `priority`, `resolver`, `clarifyPrompt` locale map) in `schemas/`
- [ ] 1.2 Define JSON Schema for the semantic-type extraction catalog `registry/semantic-types.yaml` (versioned root, semantic type id, matcher list, priority)
- [ ] 1.3 Create `registry/semantic-types.yaml` with entries lifted verbatim from current extractors (Plant, MaterialNumber, Quantity+unit, Date, vendor/purchasing-group as applicable)
- [ ] 1.4 Add extraction declaration + catalog validation to `scripts/validate-registry-contract.py`: regex compile check, backtracking-safety guard (length + nested-quantifier heuristic with bounded sample timeout), semanticType reference resolution, clarifyPrompt locale completeness for required inputs, duplicate catalog id rejection
- [ ] 1.5 Add extraction declarations to the three existing capabilities in `registry/capabilities.yaml` with strict-parity values (keywords, patterns, priorities, exclusions, clarifyPrompt text copied verbatim from current code strings)
- [ ] 1.6 Add a gateway test proving registry loading with extraction metadata leaves gateway behavior unchanged
- [ ] 1.7 Verify: `openspec list --json && openspec validate --all --strict`, registry contract validation, agent test baseline all green

## 2. Extraction Engine and Parity Harness

- [ ] 2.1 Load extraction declarations and the semantic-type catalog atomically in the agent registry loader; snapshot id covers both artifacts
- [ ] 2.2 Implement generic value resolvers (`date`, `quantity`, `text`) lifted verbatim from current extractor logic
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

```

## openspec/changes/declarative-intent-extraction/specs/declarative-intent-extraction/spec.md

- Source: openspec/changes/declarative-intent-extraction/specs/declarative-intent-extraction/spec.md
- Lines: 1-172
- SHA256: 5d362258b9ccb3afc70eda64531a51999566a018f504ff6eb44e855aedac772f

[TRUNCATED]

```md
# declarative-intent-extraction Specification (delta)

## Purpose

Declarative, registry-driven intent extraction for the rule-based agent path:
capability declarations and a shared semantic-type extraction catalog replace
hand-coded per-capability keyword sets and regex extractors, so a newly
registered capability becomes usable in rule mode without agent code changes.

## ADDED Requirements

### Requirement: Declaration-driven single-turn intent extraction

The rule-based intent path SHALL detect capabilities and extract slot
parameters exclusively from registry declarations: capability-level
`primaryKeywords` for trigger detection, optional `weakKeywords` that
participate in ambiguity counting only (never trigger), and per-input
`extraction` matchers (keyword, regex, or semantic-type reference) for slot
filling. The extraction engine SHALL contain no capability-specific branches:
adding a capability with valid extraction declarations SHALL make it
recognizable and slot-fillable in rule mode without code changes.
Ambiguity SHALL be flagged when two or more capabilities weakly or primarily
match while no capability has a primary keyword hit. Technical-override
rejection (RFC name / OData override detection) SHALL take priority over
declaration-driven matching, unchanged from the legacy behavior.

#### Scenario: Declared capability recognized without code change

- **WHEN** a capability with `primaryKeywords` and input extraction
  declarations is registered in the registry and a user utterance contains one
  of its primary keywords
- **THEN** the rule path surfaces that capability as a matched intent with
  parameters extracted per its declarations
- **AND** no agent source file needed modification to enable it

#### Scenario: Undeclared keyword does not trigger

- **WHEN** a capability has no extraction declarations and a user utterance
  matches nothing else
- **THEN** the rule path produces no matched intent for that capability

#### Scenario: Weak keyword alone does not trigger but counts toward ambiguity

- **WHEN** an utterance contains only weak keywords of two capabilities and no
  capability's primary keyword
- **THEN** neither capability is triggered as a matched intent
- **AND** the turn is flagged as keyword-ambiguous (option-showing behavior)

#### Scenario: Technical override still rejected first

- **WHEN** an utterance contains an RFC name or OData override while also
  containing a declared primary keyword
- **THEN** the rule path rejects on technical override and produces no matched
  intents

### Requirement: Shared semantic-type extraction catalog

The system SHALL provide a semantic-type extraction catalog
(`registry/semantic-types.yaml`) defining concept-level matchers keyed by
semantic type (e.g. `Plant`, `MaterialNumber`, `Quantity`, `Date`). Input
extraction declarations SHALL be able to reference a catalog entry by
`semanticType` instead of inlining a matcher, so the same concept-level
extraction knowledge is defined once and reused across capabilities.
Capability-level matchers SHALL be able to override or supplement the catalog
entry. Matchers SHALL support an ordering priority across a capability's
inputs. Cross-field exclusion SHALL be value-based: a field's extracted value
SHALL be rejected when it equals an extracted value of a field listed in its
`excludes` declaration.

#### Scenario: Two capabilities share one concept matcher

- **WHEN** two capabilities declare inputs whose extraction references the same
  semantic type in the catalog
- **THEN** both extract that field using the single catalog matcher definition

#### Scenario: Exclusion prevents value reuse

- **WHEN** a document-number matcher for one input declares exclusion of fields
  already extracted (e.g. vendor and plant) and the candidate value equals one
  of those fields' extracted values

```

Full source: openspec/changes/declarative-intent-extraction/specs/declarative-intent-extraction/spec.md

## openspec/changes/declarative-intent-extraction/specs/registry-ontology-contract/spec.md

- Source: openspec/changes/declarative-intent-extraction/specs/registry-ontology-contract/spec.md
- Lines: 1-83
- SHA256: ee2ad5c0a8510684ac08eaccdb020b3c3e9a68b6ee1d9e89df1ac2d452737155

[TRUNCATED]

```md
# registry-ontology-contract Specification (delta)

## ADDED Requirements

### Requirement: Extraction declaration validation in registry contract

The registry contract validator SHALL validate intent-extraction declarations
on every active capability: matcher kind SHALL be one of the supported kinds;
keyword matchers with a constant `value` mapping and conditional
`when`/`requiredWhen` structures SHALL reference declared input fields with a
well-formed equality condition; `excludes` entries SHALL resolve to declared
input names of the same capability; `weakKeywords` SHALL be disjoint from
`primaryKeywords`; inline regex matchers SHALL compile successfully; regex
patterns SHALL be rejected when they exceed the backtracking-safety guard
(pattern length and nested-quantifier limits); every `semanticType` extraction
reference SHALL resolve to a published entry in the semantic-type extraction
catalog; and every required or conditionally required input SHALL carry a
`clarifyPrompt` covering the supported locales with well-formed
`cases`/`fallback` structure. A capability with malformed extraction
declarations SHALL fail validation before any runtime intent path can use it.

#### Scenario: Invalid regex rejected at load time

- **WHEN** a capability declares an input extraction matcher with a regex that
  does not compile or exceeds the backtracking-safety limits
- **THEN** registry contract validation fails with the offending capability and
  input identified

#### Scenario: Dangling semantic-type reference rejected

- **WHEN** an input extraction declaration references a `semanticType` that is
  not published in the semantic-type extraction catalog
- **THEN** registry contract validation fails before runtime use

#### Scenario: Missing clarify locale rejected

- **WHEN** a required input's `clarifyPrompt` omits a supported locale
- **THEN** registry contract validation fails for that capability

#### Scenario: Malformed condition or overlapping keyword tier rejected

- **WHEN** a `when`/`requiredWhen` condition references an undeclared input,
  an `excludes` entry does not resolve to a declared input name, or a keyword
  appears in both `primaryKeywords` and `weakKeywords`
- **THEN** registry contract validation fails with the offending capability
  and declaration identified

#### Scenario: Valid declarations pass

- **WHEN** all active capabilities carry well-formed extraction declarations
  that resolve against the catalog and cover required-input locales
- **THEN** registry contract validation succeeds

### Requirement: Semantic-type extraction catalog contract

The system SHALL treat `registry/semantic-types.yaml` as a versioned registry
artifact: each entry SHALL declare a semantic type identifier used as an
extraction reference key, at least one matcher, and an extraction priority;
entries SHALL be validated for regex compile/backtracking safety and duplicate
identifier rejection. The catalog SHALL be loaded atomically with the
capability registry so a snapshot always pairs capabilities with a consistent
catalog version, and gateway runtime behavior SHALL be unaffected by catalog
content (extraction metadata is agent-side).

#### Scenario: Duplicate catalog identifier rejected

- **WHEN** the catalog declares two entries with the same semantic type
  identifier
- **THEN** catalog validation fails

#### Scenario: Capability registry and catalog load as one snapshot

- **WHEN** the agent loads the registry for a governance snapshot
- **THEN** the capability declarations and the semantic-type catalog are
  resolved from the same load, so extraction references never cross catalog
  versions

#### Scenario: Gateway ignores extraction metadata safely

- **WHEN** the gateway loads a registry containing extraction declarations and

```

Full source: openspec/changes/declarative-intent-extraction/specs/registry-ontology-contract/spec.md
