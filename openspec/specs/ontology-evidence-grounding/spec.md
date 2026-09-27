# ontology-evidence-grounding Specification

## Purpose
Govern which business caliber Definitions and object-level links may enter
the ontology as authoritative: every entry must carry evidence, evidence
must resolve to a real evaluation case, and unverified entries must remain
explicitly `proposed` rather than silently treated as fact.

## Requirements

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

#### Scenario: Validation reports all violations
- **WHEN** both catalogs contain violations
- **THEN** every violation is listed before the command exits non-zero

#### Scenario: Validation of a clean catalog set
- **WHEN** all grounded entries resolve and proposed entries declare gaps
- **THEN** the command exits zero
