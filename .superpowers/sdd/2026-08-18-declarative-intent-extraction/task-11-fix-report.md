# Task 11 Fix Report: parity regression repair

Status: DONE_WITH_CONCERNS

## Summary

Fixed the Task 10 declaration-driven extraction engine parity regression found by the Task 11 differential harness. The frozen parity harness now passes all rows/legs. The full agent suite is back to the documented pre-existing baseline failure count with no new failures from this repair.

## Independent root-cause verification

### 1. Compiled regex miss incorrectly used loose keyword fallback

Verified in `agent/sap_nexus_agent/extraction/_matching.py`:

- `match_value()` compiles matchers at lines 39-41.
- The fallback remains correct only for `compiled is None` at line 41, i.e. regex compile failure.
- The compiled-regex no-match branch now returns `None` at lines 48-50.

Legacy ground truth is `agent/sap_nexus_agent/pr_intent.py:14`, where `ACCT_ASSGN_CAT_PATTERN = re.compile(r"(?:间采|账号分配)\s*[Kk]")`; bare `间采` must not produce `acct_assgn_cat=K`.

### 2. D3 material inheritance re-rendered clarification after shrinking missing

Verified in `agent/sap_nexus_agent/extraction/engine.py`:

- `_inherit_material_for_same_capability()` inherits `material` from last context at lines 240-242.
- It now replaces only `parameters`, `missing_parameters`, and `capability_id` at lines 243-248.
- It no longer calls `render_clarify()` after removing `material` from `missing_parameters`, preserving the original clarification text from the initial `parse_declared()` result.

This matches the legacy D3 quirk pinned by Task 10 notes and Task 11 fixture `inv-sticky-new-turn-inherit`: missing shrinks from `[material, plant]` to `[plant]`, but clarification remains `请提供要查询的物料编号和工厂。`.

## Exact fix diff

```diff
diff --git a/agent/sap_nexus_agent/extraction/_matching.py b/agent/sap_nexus_agent/extraction/_matching.py
index b5f1deb..93b9f14 100644
--- a/agent/sap_nexus_agent/extraction/_matching.py
+++ b/agent/sap_nexus_agent/extraction/_matching.py
@@ -47,7 +47,7 @@ def match_value(
         return None
     regex_match = compiled.search(text)
     if regex_match is None:
-        return _constant_keyword_fallback(matcher, text)
+        return None
     value = _captured_value(regex_match, matcher)
     return value if _accepted(value, filters, excluded_values) else None
 
diff --git a/agent/sap_nexus_agent/extraction/engine.py b/agent/sap_nexus_agent/extraction/engine.py
index 2cbac2c..b097181 100644
--- a/agent/sap_nexus_agent/extraction/engine.py
+++ b/agent/sap_nexus_agent/extraction/engine.py
@@ -240,13 +240,10 @@ def _inherit_material_for_same_capability(
     parameters = dict(parsed.parameters)
     parameters["material"] = context.last_context.parameters["material"]
     missing = [name for name in parsed.missing_parameters if name != "material"]
-    descriptor = catalog.find(context.last_context.capability_id)
-    clarification = render_clarify(descriptor, missing) if descriptor is not None else parsed.clarification
     return replace(
         parsed,
         parameters=parameters,
         missing_parameters=missing,
-        clarification=clarification,
         capability_id=context.last_context.capability_id,
     )
 
diff --git a/agent/tests/test_extraction_engine.py b/agent/tests/test_extraction_engine.py
index 6dd1e12..b737c22 100644
--- a/agent/tests/test_extraction_engine.py
+++ b/agent/tests/test_extraction_engine.py
@@ -86,7 +86,7 @@ def test_extract_parameters_pr_conditional_cost_center():
     catalog = _catalog()
     pr = _cap(catalog, "MM.PR.CreateDraft")
     with_acct = engine.extract_parameters(
-        "创建PR 间采 物料 DEMOA2 工厂 1000 数量 10 EA 交货日期 2026-10-01 采购组 002 成本中心 4700", pr, catalog)
+        "创建PR 间采K 物料 DEMOA2 工厂 1000 数量 10 EA 交货日期 2026-10-01 采购组 002 成本中心 4700", pr, catalog)
     assert with_acct["acct_assgn_cat"] == "K"
     assert with_acct["cost_center"] == "4700"
     without = engine.extract_parameters(
```

The `test_extraction_engine.py` edit aligns the older Task 10 direct unit positive fixture with the corrected legacy regex contract. The Task 11 frozen parity harness, frozen oracle, and fixture expectations were not modified.

## Verification evidence

### RED before fix

Command:

```bash
.venv/bin/python -m pytest agent/tests/test_extraction_parity.py -q
```

Result before production fix:

```text
3 failed, 105 passed in 2.64s
```

Failing rows were exactly:

- `pr-indirect-full`
- `pr-indirect-missing-cost-center`
- `inv-sticky-new-turn-inherit`

### Targeted GREEN after fix

Command:

```bash
.venv/bin/python -m pytest agent/tests/test_extraction_parity.py -q
```

Result:

```text
108 passed in 2.66s
```

Additional targeted unit + parity check after aligning the older Task 10 unit positive fixture:

```bash
.venv/bin/python -m pytest agent/tests/test_extraction_engine.py::test_extract_parameters_pr_conditional_cost_center agent/tests/test_extraction_parity.py -q
```

Result:

```text
109 passed in 2.76s
```

### Full agent suite

Command:

```bash
.venv/bin/python -m pytest agent/tests -q
```

Result:

```text
15 failed, 1335 passed, 1 skipped in 55.44s
```

The 15 failures match the documented pre-existing baseline category in the SDD ledger: eval runner/governed-context snapshot failures, PO legacy parsing/orchestrator failures, and the canonical Unicode hash failure. The repair introduced no new full-suite failures.

### Syntax check

Command:

```bash
.venv/bin/python -m py_compile agent/sap_nexus_agent/extraction/_matching.py agent/sap_nexus_agent/extraction/engine.py agent/tests/test_extraction_engine.py agent/tests/legacy_intent_reference.py agent/tests/test_extraction_parity.py
```

Result: passed with no output.

## Commits

1. `478e29cf1b1dcc02c8c8790d653e6ecbed830e2e` - `fix: engine keyword-fallback over-match and D3 sticky clarification preservation`
2. `17c2b15845f8eb799673689a887f9a45fc0380c0` - `test: frozen parity fixture tables and differential legacy-vs-engine harness`

## Changed files list

First commit:

- `agent/sap_nexus_agent/extraction/_matching.py`
- `agent/sap_nexus_agent/extraction/engine.py`
- `agent/tests/test_extraction_engine.py`

Second commit:

- `agent/tests/fixtures/parity/inventory.yaml`
- `agent/tests/fixtures/parity/po.yaml`
- `agent/tests/fixtures/parity/pr.yaml`
- `agent/tests/legacy_intent_reference.py`
- `agent/tests/test_extraction_parity.py`

Report artifact:

- `.superpowers/sdd/2026-08-18-declarative-intent-extraction/task-11-fix-report.md`

Unrelated existing untracked path left untouched:

- `.omo/`

## Concerns

- The full agent suite still has 15 documented pre-existing failures. This repair did not add new failures, but the suite is not fully green.
- `agent/sap_nexus_agent/extraction/engine.py` is 246 pure LOC after the fix, inside the 200-250 warning band. This repair net-deleted lines; the next substantive edit should consider splitting responsibilities before adding more logic.

## Risk signals

- cross-module/security/concurrency/schema/API-contract/diff-size:
  - cross-module/cross-subsystem coordinated change: hit (engine behavior + legacy differential parity harness + direct unit alignment)
  - security-sensitive surface: none
  - concurrency/locks/shared mutable state: none
  - data or schema migration: none
  - public API contract or external interface change: none
- diff exceeds 200 lines: hit for second commit only (Task 11 harness adds 810 fixture/oracle/test lines); production fix commit is 3 files, 2 insertions/5 deletions

## Fix round 1: matched_intents parity

Status: DONE_WITH_CONCERNS

### Summary

Fixed the Task 11 reviewer Critical finding: the parity harness now freezes and asserts the ordered `matched_intents` list for every fixture row across legacy, declaration engine, and production parse legs. This closes the gap where multi-intent candidate drift, SHOW_OPTIONS candidate drift, or per-candidate parameter/missing drift could pass while summary fields stayed unchanged.

### Rows with frozen `matched_intents` expectations

All 36 fixture rows now have an explicit `expect.matched_intents` list, not only the rows with non-null candidates. This was intentional so SELECT/CLARIFY, SHOW_OPTIONS, ESCALATE_TO_PLANNER, REJECT, technical override, and sticky rows all pin whether candidates are present or absent.

Rows where `matched_intents` materially matters for the reviewer finding:

- Multi-intent / planner rows:
  - `pr.pr-multi-with-inventory` freezes two candidates in order: `MM.Inventory.GetAvailability`, then `MM.PR.CreateDraft`.
  - `inventory.inv-multi-with-po` freezes two candidates in order: `MM.Inventory.GetAvailability`, then `MM.PurchaseOrder.GetList`.
  - `po.po-weak-ambiguous-escalate` freezes two candidates in order: `MM.Inventory.GetAvailability`, then `MM.PurchaseOrder.GetList`.
- Single-candidate SHOW_OPTIONS rows:
  - `pr.pr-ambiguous-show-options` freezes one `MM.Inventory.GetAvailability` candidate with missing `material`, `plant`.
  - `inventory.inv-ambiguous-show-options` freezes one `MM.Inventory.GetAvailability` candidate with missing `material`, `plant`.
- Empty-candidate null-capability rows now also assert absence explicitly:
  - `pr.pr-no-trigger`
  - `pr.pr-technical-override`
  - `inventory.inv-technical-override`
  - `po.po-import-no-false-positive`
  - `po.po-technical-override`
  - `po.weak-only-no-trigger-ambiguous`

The remaining SELECT/CLARIFY/sticky rows also freeze their single candidate because current legacy, engine, and production behavior does produce one `MatchedIntent` for those rows.

### How true values were frozen

Commands used:

```bash
PYTHONPATH=agent:agent/tests .venv/bin/python - <<'PY'
from __future__ import annotations
from pathlib import Path
from typing import Any
import yaml

from legacy_intent_reference import parse as legacy_parse
from legacy_intent_reference import sticky as legacy_sticky
from sap_nexus_agent.conversation_context import ConversationContext, LastContext
from sap_nexus_agent.extraction import engine
from sap_nexus_agent.intent import _detect_odata_override, _detect_rfc_name, parse_intent
from sap_nexus_agent.llm_intent import resolve_with_context
from sap_nexus_agent.registry_loader import load_intent_catalog

FIXTURES = Path('agent/tests/fixtures/parity')
TABLES = ('pr', 'inventory', 'po')


def context(row: dict[str, Any]) -> ConversationContext:
    last_context = row['last_context']
    parameters = dict(last_context.get('parameters') or {})
    return ConversationContext(
        last_context=LastContext(
            capability_id=str(last_context['capability_id']),
            parameters={str(key): str(value) for key, value in parameters.items()},
            missing_parameters=[str(value) for value in last_context.get('missing_parameters', [])],
            decision_type=str(last_context.get('decision_type', 'CLARIFY')),
        ),
        history=(),
    )


def matched(result: Any) -> list[dict[str, Any]]:
    return [
        {
            'capability_id': item.capability_id,
            'parameters': dict(item.parameters),
            'missing': list(item.missing),
        }
        for item in result.matched_intents
    ]

catalog = load_intent_catalog()
for table in TABLES:
    doc = yaml.safe_load((FIXTURES / f'{table}.yaml').read_text(encoding='utf-8'))
    for row in doc['rows']:
        if row['mode'] == 'sticky':
            legacy = legacy_sticky(row['utterance'], context(row))
            eng = engine.sticky_parse(row['utterance'], context(row), catalog)
            prod = resolve_with_context(row['utterance'], context(row), catalog)
        else:
            legacy = legacy_parse(row['utterance'])
            eng = engine.parse_declared(
                row['utterance'],
                catalog,
                contains_rfc_name=_detect_rfc_name(row['utterance']),
                contains_odata_override=_detect_odata_override(row['utterance']),
            )
            prod = parse_intent(row['utterance'])
        values = {'legacy': matched(legacy), 'engine': matched(eng), 'production': matched(prod)}
        if values['legacy'] != values['engine'] or values['legacy'] != values['production']:
            print('MISMATCH', table, row['name'], values)
            raise SystemExit(2)
        if values['legacy']:
            print(f"{table}.{row['name']}")
            print(yaml.safe_dump({'matched_intents': values['legacy']}, allow_unicode=True, sort_keys=False).rstrip())
PY
```

Evidence:

- First attempt without `PYTHONPATH=agent:agent/tests` failed with `ModuleNotFoundError: No module named 'legacy_intent_reference'`; this was an execution-path issue, not a parity discrepancy.
- The corrected command printed every non-empty candidate list and exited `0`, meaning `legacy == engine == production` for all matched-intent lists before values were copied into YAML.
- No engine-vs-legacy discrepancy was found, so no production path files were touched.

### RED/GREEN evidence

RED command after adding the new assertion but before adding YAML expectations:

```bash
.venv/bin/python -m pytest agent/tests/test_extraction_parity.py -q
```

RED result:

```text
108 failed in 3.18s
```

The failures were `KeyError: 'matched_intents'` in `_assert_row`, proving the harness now requires frozen candidate expectations for every legacy/engine/production leg.

GREEN command after adding frozen YAML expectations:

```bash
.venv/bin/python -m pytest agent/tests/test_extraction_parity.py -q
```

GREEN result:

```text
108 passed in 6.42s
```

Additional syntax check:

```bash
.venv/bin/python -m py_compile agent/tests/test_extraction_parity.py
```

Result: passed with no output.

### Full agent suite

Command:

```bash
.venv/bin/python -m pytest agent/tests -q
```

Result:

```text
15 failed, 1335 passed, 1 skipped in 114.68s (0:01:54)
```

The failure count and categories match the documented pre-existing baseline supplied for this fix round: eval runner/governed-context snapshot failures, PO legacy parsing/orchestrator failures, and canonical Unicode hash failure. No parity harness failures remained.

### Commit

Harness fix commit:

```text
427e182a5b08822dd5eaeb96b9e29f62db0cbaa7 fix: assert matched-intent parity in the differential harness
```

I used a new commit instead of amending `17c2b15` because the repository is currently on `main` tracking `origin/main`; rewriting history on `main` is disallowed by the git workflow safety rules.

### Changed files

Harness fix commit changed:

- `agent/tests/test_extraction_parity.py`
- `agent/tests/fixtures/parity/pr.yaml`
- `agent/tests/fixtures/parity/inventory.yaml`
- `agent/tests/fixtures/parity/po.yaml`

Report artifact changed:

- `.superpowers/sdd/2026-08-18-declarative-intent-extraction/task-11-fix-report.md`

Unrelated existing untracked path left untouched:

- `.omo/`

### Concerns

- The full agent suite still has the documented 15 pre-existing failures, so final status remains `DONE_WITH_CONCERNS` rather than fully green.
- Fixture diff is sizeable (+239 lines) because candidate sets are now frozen explicitly for all 36 rows; this is deliberate to prevent both candidate drift and accidental non-empty/empty drift.

### Risk signals

- cross-module/cross-subsystem coordinated change: hit (test harness + three fixture tables + SDD report)
- security-sensitive surface: none
- concurrency/locks/shared mutable state: none
- data or schema migration: none
- public API contract or external interface change: none
- diff exceeds 200 lines: hit (+239 harness/fixture insertions, mostly frozen YAML expectations)
