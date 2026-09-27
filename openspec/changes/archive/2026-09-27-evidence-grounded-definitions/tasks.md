## 1. Ontology catalogs

- [x] 1.1 Add `ontology/definitions.yaml`: ATP/available-for-commitment caliber
  (`grounded`, evidence
  `evals/eval_harness_seed_cases.json#bc_mm_inventory_business_caliber_001`),
  and overdue / credit-exposure entries (`proposed`, each with an
  `evidenceGap` reason)
- [x] 1.2 Add `ontology/object-links.yaml` with `Customer → ARItem` and
  `Customer → SalesOrderItem`, both `grounded` with their eval-case evidence

## 2. Validation

- [x] 2.1 Add `scripts/validate-evidence-grounding.py`: load both catalogs,
  enforce evidence presence, resolve suite/case ids, enforce the
  grounded/proposed rules, list all violations, fail-closed exit code

## 3. Tests

- [x] 3.1 Add `agent/tests/test_evidence_grounding.py`: grounded happy paths,
  missing evidence, unresolvable suite/case id, proposed-with-gap passes,
  proposed-without-gap fails, and validator exit codes

## 4. Verification

- [x] 4.1 Run the validator on the shipped catalogs (exit zero), run the new
  tests, run the full agent suite, and record results in verification
