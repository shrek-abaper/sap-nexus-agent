# Comet Design Handoff

- Change: declarative-intent-hardening
- Phase: design
- Mode: compact
- Context hash: 77353016486164883d6bc2983a93d53387a509ed525d1829d78a74b8923bee18

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/declarative-intent-hardening/proposal.md

- Source: openspec/changes/declarative-intent-hardening/proposal.md
- Lines: 1-79
- SHA256: 82fce6f983b17188ddf7ec4ea3a70ac701aa0106779227a19aca66f5908d8e12

```md
# Proposal: declarative-intent-hardening

## Why

The declarative intent extraction layer (registry-driven matchers, clarify
prompts, and per-input extraction declarations) is functionally correct but has
three structural weaknesses that will force expensive rework once the registry
schema is frozen: free-form regex matchers are uncomposable and unexplainable,
clarify prompts enumerate missing-field combinations (exploding with 6 required
PR fields), and extraction blocks hard-code the assumption that parameters come
only from the user utterance. These are closed now, before schema freeze, at
the lowest cost point.

## What Changes

- **B1 — Matcher kind whitelist.** Add named matcher kinds `prefixed`,
  `suffixed`, and `valueShape` (referencing a new shared `valueShapes` section
  in the semantic-type catalog) and rewrite the Plant matcher with them.
  Free-form `regex` matchers are demoted to an escape hatch: every remaining
  regex matcher must carry a `justification` field, and
  `scripts/validate-registry-contract.py` prints the current regex-matcher
  count so the number becomes an observable, reducible metric. The duplicated
  plant pattern `^[A-Z0-9]{4}$` is consolidated into
  `valueShapes.plantCode`. **BREAKING** for registry authors: un-justified
  regex matchers are rejected by the validator.
- **B2 — Clarify de-enumeration.** Add a `groupByBindingKind` clarify strategy
  with a `maxRounds` budget (2): missing fields from the same source group are
  merged into one prompt whose copy is generated from `intent.fieldNames`
  templates instead of hand-written per-combination `cases[]`. The `cases[]`
  list remains as an optional override mechanism for special copy, not the main
  path. PR (6 required fields) is covered by tests for 1 / 2 / 3+ missing
  fields, asserting round count stays within `maxRounds` and one prompt carries
  all missing fields of a group.
- **B3 — Extraction generalized to binding.** The `extraction` block is
  generalized to `binding` with a `sources[]` list of three kinds:
  `userUtterance` (today's matchers), `capabilityOutput` (future dependency
  edges — **not implemented in this batch**, a NotImplemented path with an
  xfail placeholder test), and `default`. Priority is
  `capabilityOutput > userUtterance > default`; a derivable value is never
  elicited from the user. The old `extraction:` shape is retained as a
  deprecated alias: the validator emits a warning with migration guidance.
  **BREAKING** for future registry authors only after deprecation is removed;
  the alias keeps existing declarations valid now.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `declarative-intent-extraction`: matcher kinds are whitelisted to
  prefixed/suffixed/valueShape with a justified-regex escape hatch; clarify
  prompts move from case enumeration to a group-based strategy with a round
  budget; extraction declarations generalize to binding sources with defined
  priority and a deprecated extraction alias.

## Impact

- `registry/semantic-types.yaml`, `registry/capabilities.yaml`
- `schemas/semantic-type-catalog.schema.json`, `schemas/capability.schema.json`,
  `schemas/extraction-declaration.schema.json`
- Agent extraction engine: `agent/sap_nexus_agent/extraction/` (matching,
  engine, clarify) and registry loader as needed
- `scripts/validate-registry-contract.py`
- Tests: matcher equivalence must stay green (matcher_cases 23/23), new B2
  clarify-round tests, B3 xfail placeholder and validator warning tests
- Not touched: frontend, Gateway, approval semantics, SAP execution paths
- No new dependencies

## Scope note (no-split decision)

B1/B2/B3 were considered for splitting into three changes and kept as one: the
three items share `registry/capabilities.yaml`, the registry contract schemas,
the extraction engine, and the registry validator, so splitting would create
cross-change conflicts on the same files with no delivery benefit. Each item
keeps its own task group, independent commit series, and exit criteria inside
this change.

```

## openspec/changes/declarative-intent-hardening/design.md

- Source: openspec/changes/declarative-intent-hardening/design.md
- Lines: 1-121
- SHA256: 92a87960d6437ffef77702f8f53ea9bb359cb6b86f17c9c9ea1a83c743938b77

[TRUNCATED]

```md
# Design: declarative-intent-hardening

## Context

The registry contract (v2 capabilities + v1 semantic-type catalog) is about to
freeze. Today matchers are free regex (semantic-types.yaml), clarify prompts
enumerate missing-set combinations, and extraction blocks assume a single
text source (`resolver: text`). The extraction engine
(`agent/sap_nexus_agent/extraction/`) reads these declarations through
`registry_loader.py`; `scripts/validate-registry-contract.py` validates them
against `schemas/*.schema.json`. See proposal.md for motivation.

## Goals / Non-Goals

**Goals:**

- B1: named matcher kinds + `valueShapes` + justified-regex escape hatch +
  observable regex count in the validator
- B2: `groupByBindingKind` clarify strategy with `maxRounds` budget and
  fieldNames-templated copy; `cases[]` demoted to optional override
- B3: `binding.sources[]` schema with `capabilityOutput > userUtterance >
  default` priority; `capabilityOutput` NotImplemented + xfail placeholder;
  deprecated `extraction` alias with validator warning + migration guidance

**Non-Goals:**

- No capabilityOutput execution implementation
- No capability dependency edges (D2), no approval/subject-hash changes (D4)
- No frontend or Gateway changes, no new dependencies
- No new matcher kinds beyond the three named kinds in this batch

## Decisions

1. **Named kinds encode as structured matcher configs, not new regex syntax.**
   `prefixed: {prefix: [...]}`, `suffixed: {suffix: [...]}`,
   `valueShape: {shape: <name>}` compiled by the matching layer into bounded
   regexes at load time. Rationale: composable, explainable (a clarify prompt
   can be derived from prefixes/suffixes), and auditable by the validator.
   Alternative considered: keep regex but require naming — rejected, since it
   preserves unlimited expressiveness without composability.

2. **`valueShapes` live at catalog top level** (`semantic-types.yaml`
   `valueShapes: {plantCode: '^[A-Z0-9]{4}$', ...}`), referenced by matcher
   and validated against the input `pattern` contract. Rationale: one home for
   duplicated shapes; matches the spec requirement to consolidate
   `^[A-Z0-9]{4}$` (today duplicated in Inventory + PO plant inputs).

3. **Plant rewrite = named kinds + one justified regex.** The
   prefixed/suffixed form ("在 1000 工厂") maps to prefixed+suffixed+valueShape.
   The bare-code fallback with lookaround guards (`(?<!\d)([A-Z]\d{3}|\d{4})(?!\d)`)
   cannot be expressed by the named kinds and stays a regex matcher carrying a
   justification. Equivalence is proven by matcher_cases staying 23/23; the
   valueShape `^[A-Z0-9]{4}$` accepts letter-mixed codes (e.g. AB12) the old
   extraction regex rejected, which aligns extraction with the input pattern —
   no existing eval case depends on the stricter legacy behavior (verified by
   grep before the change).

4. **Regex count is a validator metric, not a gate.** The validator prints the
   total number of regex matchers in the semantic-type catalog plus
   capability-level regex matchers; justification is mandatory per matcher.
   The count is reported so decline is observable, but a nonzero count does
   not fail validation. Rationale: Plant's guarded bare-scan is a legitimate
   escape-hatch case today.

5. **Clarify strategy is declaration-driven with engine-level round tracking.**
   `clarifyPrompt.zh-CN.strategy: groupByBindingKind` + `maxRounds: 2`. The
   clarify renderer groups missing fields by source group (today: one
   userUtterance group; future: per capabilityOutput source), renders one
   prompt per group via `fieldNames` templates, and counts rounds in the turn
   state; budget exhaustion degrades to the `fallback` template. `cases[]`
   entries are checked first (exact missing-set match) and stay as overrides.
   Rationale: PR's 6 required fields currently collapse to fallback
   immediately; grouping makes one prompt carry all six with no combination
   enumeration. Alternative considered: fully generative LLM prompts —
   rejected (rule mode must stay deterministic and LLM-free).

6. **Binding is a superset shape with a deprecated alias, not a rename.**
   New shape `binding.sources[]`; the loader normalizes legacy `extraction:`
   into a single `userUtterance` source internally. The validator emits a
   warning per `extraction:` usage with migration text. Priority

```

Full source: openspec/changes/declarative-intent-hardening/design.md

## openspec/changes/declarative-intent-hardening/tasks.md

- Source: openspec/changes/declarative-intent-hardening/tasks.md
- Lines: 1-29
- SHA256: 1f914b5d32cb871ecf01b57b5450fa0145c67429859333fe7b1b795206d7eead

```md
# Tasks: declarative-intent-hardening

## 1. B1 — Matcher kind whitelist

- [ ] 1.1 Extend `schemas/semantic-type-catalog.schema.json`: matcher kind enum gains `prefixed`, `suffixed`, `valueShape`; catalog-level `valueShapes` section; `regex` kind requires non-empty `justification`. Extend the loader model (`registry_loader.py`) to parse the new kinds and valueShapes.
- [ ] 1.2 Implement named-kind compilation in `agent/sap_nexus_agent/extraction/_matching.py`: `prefixed` (value after prefix token), `suffixed` (value before suffix token), `valueShape` (reference to `valueShapes` entry), keeping capture-group semantics identical to the regex path.
- [ ] 1.3 Add `valueShapes.plantCode: '^[A-Z0-9]{4}$'` to `registry/semantic-types.yaml`; rewrite the Plant prefixed/suffixed matcher with `prefixed: [在]` + `suffixed: [工厂]` + `valueShape: plantCode`; keep the bare-code fallback as a regex matcher with a `justification` (guarded bare scan cannot be expressed by named kinds).
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

```

## openspec/changes/declarative-intent-hardening/specs/declarative-intent-extraction/spec.md

- Source: openspec/changes/declarative-intent-hardening/specs/declarative-intent-extraction/spec.md
- Lines: 1-239
- SHA256: d110906e71f68c52301142ae474867a7d1d15d2c355acf0e0c7f51935d1c2c65

[TRUNCATED]

```md
# Delta spec: declarative-intent-extraction

## ADDED Requirements

### Requirement: Input binding sources and priority

Per-input declarations SHALL support a `binding` block with a `sources[]`
list of three kinds: `userUtterance` (matcher-driven extraction from the user
utterance, equivalent to today's extraction matchers), `capabilityOutput` (a
value derived from another capability's fact, reserved for future dependency
edges), and `default` (a constant fallback value). Source priority SHALL be
`capabilityOutput > userUtterance > default`: when a capabilityOutput source
can produce a value the system MUST NOT elicit the field from the user and
MUST NOT fall back to a default. The `capabilityOutput` kind SHALL be
accepted and validated by the schema and validator, but its execution path
MAY remain unimplemented in this batch; an unimplemented path SHALL be
surfaced by a failing xfail placeholder test so future implementation has a
fixed landing point.

#### Scenario: capabilityOutput beats user utterance

- **WHEN** an input declares both a `capabilityOutput` source and a
  `userUtterance` matcher and the capabilityOutput source can produce a value
- **THEN** the resolved value comes from the capabilityOutput source
- **AND** no clarification question for that field is raised

#### Scenario: default only fills when no other source produces

- **WHEN** an input declares a `default` source and no higher-priority source
  produces a value
- **THEN** the default value fills the input

#### Scenario: unimplemented capabilityOutput has a failing placeholder

- **WHEN** the capabilityOutput execution path is not yet implemented
- **THEN** an xfail-marked test referencing that path fails with a clear
  not-implemented reason instead of being silently absent

### Requirement: Deprecated extraction alias with migration warning

The pre-existing `extraction:` declaration shape SHALL remain valid as a
deprecated alias of `binding:` with a single `userUtterance` source. The
registry validator SHALL emit a warning for every `extraction:` usage and the
warning SHALL carry migration guidance pointing at the `binding.sources[]`
shape. Declarations that use neither `binding` nor `extraction` for an input
that requires extraction SHALL be reported as invalid exactly as before.

#### Scenario: extraction alias still works with a warning

- **WHEN** the registry is validated and an input declares `extraction:`
  matchers
- **THEN** validation succeeds
- **AND** a warning naming the deprecated shape and its `binding.sources[]`
  replacement is reported

#### Scenario: binding shape validates without warnings

- **WHEN** the registry is validated and an input declares `binding.sources[]`
- **THEN** validation succeeds with no deprecation warning

## MODIFIED Requirements

### Requirement: Declaration-driven single-turn intent extraction

The rule-based intent path SHALL detect capabilities and extract slot
parameters exclusively from registry declarations: capability-level
`primaryKeywords` for trigger detection, optional `weakKeywords` that
participate in ambiguity counting only (never trigger), and per-input
`binding` sources (matchers from the `userUtterance` kind, semantic-type
references, or keyword constants) for slot filling. The extraction engine
SHALL contain no capability-specific branches: adding a capability with valid
extraction declarations SHALL make it recognizable and slot-fillable in rule
mode without code changes. Ambiguity SHALL be flagged when two or more
capabilities weakly or primarily match while no capability has a primary
keyword hit. Technical-override rejection (RFC name / OData override
detection) SHALL take priority over declaration-driven matching, unchanged
from the legacy behavior.

#### Scenario: Declared capability recognized without code change


```

Full source: openspec/changes/declarative-intent-hardening/specs/declarative-intent-extraction/spec.md
