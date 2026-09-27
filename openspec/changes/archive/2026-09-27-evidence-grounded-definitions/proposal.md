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
