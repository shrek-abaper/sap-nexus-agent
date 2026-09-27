# Brainstorm Summary

- Change: evidence-grounded-definitions
- Date: 2026-09-27
- Mode: autonomous `/goal` (user unavailable for round-trips; proposal
  confirmed-by-goal)

## Confirmed Technical Approach

- Reusable core in `agent/sap_nexus_agent/evidence_grounding.py` + thin CLI
  `scripts/validate-evidence-grounding.py` (same module/script split as
  Phases 1–2, keeps unit tests in `agent/tests/`).
- Two catalogs:
  - `ontology/definitions.yaml`: `definitions[]` with `definitionId`,
    `title`, `statement`, `status`, `evidence` / `evidenceGap`.
  - `ontology/object-links.yaml`: `links[]` with `linkId`,
    `sourceObject`, `targetObject`, `linkType`, `status`, same evidence
    rules.
- `status: grounded` requires `evidence {suite, caseId}` resolving to a
  real case; `status: proposed` requires non-empty `evidenceGap` and no
  evidence requirement; anything else is a violation.
- Evidence resolver loads the suite file (JSON or YAML — the repo's YAML
  suites hold JSON content, `yaml.safe_load` handles both), walks
  `cases[]`, collects ids from `id` / `caseId`.
- Validator collects ALL violations across both catalogs, prints
  `entry-id: reason` lines, exits 1 when any exist; 0 on clean.

## Key Trade-offs and Risks

- Two statuses preserve roadmap vocabulary without fabricating evidence
  (EvoOntology grounded construction); risk: proposed entries linger —
  mitigated by mandatory concrete `evidenceGap`.
- Evidence is case-level, not field-level; sufficient until Definitions
  enter the compile-time derivation pipeline (future change).
- Putting core in the agent package (not scripts/) gives clean imports in
  tests; no runtime code imports it yet, so zero behavioral impact.

## Testing Strategy

- Unit tests with synthetic catalogs in `tmp_path`: grounded pass,
  missing evidence, unknown suite file, unknown case id, proposed-with-gap
  pass, proposed-without-gap fail, invalid status, multi-violation
  collection, and case-id extraction from both `id` and `caseId`.
- One subprocess test: CLI against the shipped catalogs exits 0.
- Full agent suite must stay green.

## Spec Patches

None — the delta spec already covers all accepted behaviors.
