# Comet Design Handoff

- Change: evidence-grounded-definitions
- Phase: design
- Mode: compact
- Context hash: 310b146733475e9d6e6be8ff699e3ff5d74e29d46624f3028dda918d62ed6832

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/evidence-grounded-definitions/proposal.md

- Source: openspec/changes/evidence-grounded-definitions/proposal.md
- Lines: 1-49
- SHA256: ab170c34a6ea5a7274d36a52096f191cdb3ff9fb33ce446a0c7d853062bc7bbe

```md
## Why

Business calibers (Definitions) and cross-object relations have no governed
home today: `ontology/capability-relations.yaml` is empty and there is no
mechanism preventing an unverified assertion from entering the ontology.
Following the EvoOntology research
(`docs/proposals/evoontology-semantica-evaluation.md`, Phase 3), semantic
objects may only be published as authoritative when bound to evidence that
resolves to a real evaluation case. This also gives the roadmap calibers
(available stock / overdue / credit exposure) a truthful status instead of
silent implicit assumptions.

## What Changes

- Add `ontology/definitions.yaml`: a catalog of business caliber
  Definitions with an evidence block per entry and a publication status:
  `grounded` (evidence resolves) or `proposed` (evidence gap declared).
- Add `ontology/object-links.yaml`: object-level links with the same
  evidence requirements.
- Add `scripts/validate-evidence-grounding.py`: fail-closed validation that
  every entry carries evidence, that referenced evidence resolves to an
  existing eval case id, and that only `grounded` entries may be treated as
  authoritative; `proposed` entries must declare an `evidenceGap` reason.
- Add tests covering grounded publication, proposed-with-gap, missing
  evidence, and unresolvable evidence.

## Capabilities

### New Capabilities
- `ontology-evidence-grounding`: Evidence-grounded business Definitions and
  object links; catalog formats and the validation rules governing what may
  enter the ontology as authoritative.

### Modified Capabilities
<!-- None: no existing spec requirements change. -->

## Impact

- New ontology files (`ontology/definitions.yaml`,
  `ontology/object-links.yaml`); no existing runtime/registry behavior
  changes — validation is additive and the catalogs introduce no executable
  behavior by themselves.
- Grounded at creation: ATP caliber is bound to
  `evals/eval_harness_seed_cases.json#bc_mm_inventory_business_caliber_001`;
  `Customer → ARItem` to `evals/ar_open_items_cases.yaml#ar-happy-path`;
  `Customer → SalesOrderItem` to
  `evals/sales_order_list_cases.yaml#so-by-customer`.
- Overdue and credit exposure are recorded as `proposed` with explicit
  evidence gaps; implementing their computation is a separate future change.

```

## openspec/changes/evidence-grounded-definitions/design.md

- Source: openspec/changes/evidence-grounded-definitions/design.md
- Lines: 1-47
- SHA256: 04932f5c562003b0e15a80059fe427bbdff26e52d34f3f0b95e3e7e2a3d45dd7

```md
## Context

- `ontology/capability-relations.yaml` is empty and there is no governed
  location for business calibers (Definitions) today.
- Existing ontology tooling (`scripts/build-ontology-bundle.py`,
  `scripts/validate_registry_contract.py`) does not cover Definition/link
  evidence; this change is additive and introduces no executable behavior by
  itself.
- The validation must be offline and dependency-light: eval suites are
  JSON/YAML files already in the repo, so resolvability is a file+id lookup.

## Goals / Non-Goals

**Goals:**
- Two catalog files (`definitions.yaml`, `object-links.yaml`) whose
  grounded entries bind to resolvable eval-case evidence.
- A single fail-closed validator enforcing evidence presence,
  resolvability, and the grounded/proposed distinction.

**Non-Goals:**
- No computation of overdue or credit-exposure semantics (they are recorded
  as `proposed`; implementation is a future capability change).
- No runtime behavior changes, no wiring of Definitions into the agent
  pipeline, no compile-time derivation changes.
- No LLM-assisted evidence discovery.

## Decisions

1. **Two explicit statuses rather than one.** `grounded` requires
   resolvable evidence; `proposed` requires an `evidenceGap` reason. This
   implements EvoOntology's grounded construction truthfully: the roadmap
   vocabulary is preserved without fabricating verification.
2. **Evidence reference shape: `suite` (repo-relative eval file) +
   `caseId`.** Resolved by parsing JSON/YAML once per suite. An entry whose
   suite or case id is absent fails as unresolvable evidence.
3. **Standalone validator.** Kept separate from the registry-contract
   validator because ontology catalogs have a different schema and lifecycle;
   it is pure standard-library Python (PyYAML already used project-wide).
4. **Catalogs share one schema family** (`entry` with status/evidence) so the
   validator handles both with a single code path.

## Risks / Trade-offs

- Proposed entries can accumulate and become stale; mitigated by requiring a
  concrete `evidenceGap` reason that future changes must close.
- Evidence binding is at case granularity; a future change may strengthen it
  to field-level assertions when Definitions enter the derivation pipeline.

```

## openspec/changes/evidence-grounded-definitions/tasks.md

- Source: openspec/changes/evidence-grounded-definitions/tasks.md
- Lines: 1-26
- SHA256: 73e3e94ec4c95e6c8328a4aa8efb1d1d348ecc5a5406508f03f8ebec9bf4b578

```md
## 1. Ontology catalogs

- [ ] 1.1 Add `ontology/definitions.yaml`: ATP/available-for-commitment caliber
  (`grounded`, evidence
  `evals/eval_harness_seed_cases.json#bc_mm_inventory_business_caliber_001`),
  and overdue / credit-exposure entries (`proposed`, each with an
  `evidenceGap` reason)
- [ ] 1.2 Add `ontology/object-links.yaml` with `Customer → ARItem` and
  `Customer → SalesOrderItem`, both `grounded` with their eval-case evidence

## 2. Validation

- [ ] 2.1 Add `scripts/validate-evidence-grounding.py`: load both catalogs,
  enforce evidence presence, resolve suite/case ids, enforce the
  grounded/proposed rules, list all violations, fail-closed exit code

## 3. Tests

- [ ] 3.1 Add `agent/tests/test_evidence_grounding.py`: grounded happy paths,
  missing evidence, unresolvable suite/case id, proposed-with-gap passes,
  proposed-without-gap fails, and validator exit codes

## 4. Verification

- [ ] 4.1 Run the validator on the shipped catalogs (exit zero), run the new
  tests, run the full agent suite, and record results in verification

```

## openspec/changes/evidence-grounded-definitions/specs/ontology-evidence-grounding/spec.md

- Source: openspec/changes/evidence-grounded-definitions/specs/ontology-evidence-grounding/spec.md
- Lines: 1-88
- SHA256: c1b592fa5d0e2c27a19ae630b2453821082fef846cbcbe2bbf7525c93d120a31

[TRUNCATED]

```md
## Purpose

Govern which business caliber Definitions and object-level links may enter
the ontology as authoritative: every entry must carry evidence, evidence
must resolve to a real evaluation case, and unverified entries must remain
explicitly `proposed` rather than silently treated as fact.

## ADDED Requirements

### Requirement: Business Definitions catalog

`ontology/definitions.yaml` SHALL list each business caliber Definition with
a stable `definitionId`, a human-readable statement, a `status`
(`grounded` or `proposed`), and an `evidence` block referencing an eval
suite and case id.

#### Scenario: Grounded Definition with resolvable evidence
- **WHEN** a Definition declares `status: grounded` and
  `evidence.caseId` exists in the referenced eval suite
- **THEN** the Definition is valid and may be treated as authoritative

#### Scenario: Definition without evidence
- **WHEN** a Definition entry has no `evidence` block
- **THEN** the validation fails with a missing-evidence error naming the
  `definitionId`

### Requirement: Object links catalog

`ontology/object-links.yaml` SHALL list each object-level link (source
object, target object, link type) with the same status and evidence
requirements as Definitions.

#### Scenario: Grounded object link
- **WHEN** a link from `Customer` to `ARItem` references
  `evals/ar_open_items_cases.yaml#ar-happy-path`
- **THEN** the link validates as grounded

#### Scenario: Object link without evidence
- **WHEN** a link entry has no evidence
- **THEN** validation fails naming the link

### Requirement: Evidence must resolve

Every grounded entry's `evidence` MUST resolve: the named eval suite file
must exist and must contain the named case id.

#### Scenario: Evidence references a missing case id
- **WHEN** a grounded entry references a case id that does not exist in
  the named suite
- **THEN** validation fails with an unresolvable-evidence error

#### Scenario: Evidence references a missing suite file
- **WHEN** a grounded entry names an eval file that does not exist
- **THEN** validation fails with an unresolvable-evidence error

### Requirement: Proposed entries must declare an evidence gap

An entry MAY declare `status: proposed` when its semantics are not yet
implemented or verified. Such an entry MUST carry an `evidenceGap` reason
and MUST NOT be reported as authoritative.

#### Scenario: Proposed entry with an evidence gap
- **WHEN** an entry declares `status: proposed` and a non-empty
  `evidenceGap`
- **THEN** validation passes while excluding the entry from grounded
  results

#### Scenario: Proposed entry without a gap reason
- **WHEN** an entry declares `status: proposed` but omits `evidenceGap`
- **THEN** validation fails

#### Scenario: Proposed entry must not masquerade as grounded
- **WHEN** a proposed entry is absent from grounded validation output
- **THEN** no component is permitted to treat the caliber as verified

### Requirement: Fail-closed validation command

`scripts/validate-evidence-grounding.py` SHALL validate both catalogs and
exit non-zero on any violation, emitting the offending entry identity and
reason. A clean run exits zero.

```

Full source: openspec/changes/evidence-grounded-definitions/specs/ontology-evidence-grounding/spec.md
