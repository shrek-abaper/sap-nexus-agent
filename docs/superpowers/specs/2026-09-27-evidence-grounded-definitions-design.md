---
comet_change: evidence-grounded-definitions
role: technical-design
canonical_spec: openspec
archived-with: 2026-09-27-evidence-grounded-definitions
status: final
---

# Evidence-Grounded Definitions — Design Doc

## 1. Overview

Business caliber Definitions and object-level links enter the ontology only
under an evidence contract. A reusable core validates two YAML catalogs; a
thin CLI exposes it. Entries are `grounded` (evidence resolves to a real
eval case) or `proposed` (an explicit evidence gap is declared).

## 2. Catalog formats

### 2.1 `ontology/definitions.yaml`

```yaml
version: 1
definitions:
  - definitionId: sapnexus:def.available-for-commitment
    title: Available stock for commitment
    statement: >-
      The quantity available to promise is computed from the MD04
      stock/requirements list; unrestricted stock alone is not the
      commitment quantity.
    status: grounded
    evidence:
      suite: evals/eval_harness_seed_cases.json
      caseId: bc_mm_inventory_business_caliber_001
  - definitionId: sapnexus:def.overdue
    title: Overdue open item
    status: proposed
    evidenceGap: >-
      No overdue computation exists in code or evals; AR/AP return
      blineDate only. Requires an overdue-capability change.
  - definitionId: sapnexus:def.credit-exposure
    title: Customer credit exposure
    status: proposed
    evidenceGap: >-
      No composite exposure capability exists; review_customer_exposure
      is a roadmap target only.
```

### 2.2 `ontology/object-links.yaml`

```yaml
version: 1
links:
  - linkId: customer-ar-item
    sourceObject: Customer
    targetObject: ARItem
    linkType: has-open-items
    status: grounded
    evidence:
      suite: evals/ar_open_items_cases.yaml
      caseId: ar-happy-path
  - linkId: customer-sales-order-item
    sourceObject: Customer
    targetObject: SalesOrderItem
    linkType: has-sales-orders
    status: grounded
    evidence:
      suite: evals/sales_order_list_cases.yaml
      caseId: so-by-customer
```

## 3. Core module: `agent/sap_nexus_agent/evidence_grounding.py`

Functions:

| Function | Responsibility |
|---|---|
| `load_catalog(path) -> dict` | `yaml.safe_load`; returns `{}` on empty. |
| `resolve_case_ids(repo_root, suite_rel) -> set[str] \| None` | Read suite (JSON or YAML), return ids from `cases[].id` / `.caseId`; `None` when the file is missing. |
| `validate_entry(entry, id_key, repo_root) -> list[str]` | Violation strings for one entry: unknown status; grounded without evidence; grounded with unresolvable suite/case; proposed without gap. Empty list = valid. |
| `validate_catalogs(repo_root, definitions_path, object_links_path) -> list[str]` | Prefix each violation with catalog and entry id; return all. |

Rules detail:

1. `status` not in `{grounded, proposed}` → violation.
2. `grounded` + missing `evidence` → missing-evidence violation.
3. `grounded` + suite file absent or `caseId` not in resolved ids →
   unresolvable-evidence violation.
4. `proposed` + empty/missing `evidenceGap` → violation.
5. `proposed` with gap → valid regardless of evidence presence.
6. Entry id resolved from `definitionId` or `linkId`.

## 4. CLI: `scripts/validate-evidence-grounding.py`

- Insert `agent/` on `sys.path`; call `validate_catalogs` against the two
  shipped catalog paths.
- Print one `violation: <text>` line per finding; print
  `Evidence grounding: OK` on success; exit 1 / 0 accordingly.

## 5. Edge cases

- Suite YAML files hold JSON text — `yaml.safe_load` parses both; extension
  is irrelevant.
- Cases keyed by either `id` (most suites) or `caseId` (seed JSON) — both
  accepted.
- Catalog file missing → treated as a violation (catalog must exist).
- Empty `definitions` / `links` list validates (no entries) — but the
  shipped files carry entries.

## 6. Test strategy

`agent/tests/test_evidence_grounding.py`:

- `resolve_case_ids` accepts both id keys; missing suite → `None`.
- Synthetic grounded entry with a real temp suite → valid.
- Grounded missing evidence / bad suite / bad case id → violations.
- Proposed with gap → valid; without gap → violation; invalid status →
  violation.
- Aggregator prefixes and collects multiple violations.
- Subprocess: shipped catalogs → CLI exit 0.

## 7. Risks

- Proposed entries may stagnate; the concrete `evidenceGap` text names the
  required future change so it cannot become an anonymous placeholder.
- No runtime consumer yet; risk of drift between catalog and code is
  bounded because grounded evidence is itself a regression case.
