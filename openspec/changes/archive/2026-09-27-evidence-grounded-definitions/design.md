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
