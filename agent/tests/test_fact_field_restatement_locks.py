"""Every restatement of a Fact Type field list is checked (T1: tasks 2.6/2.7).

Requirement: openspec/changes/derived-parameter-binding/specs/
registry-ontology-contract/spec.md — `ontology/fact-types.yaml` is the authority
for a Fact Type's field list, so no other site may carry an *unchecked*
independent copy of it.

`sapnexus:PurchaseOrderSupplyFact` is the worst case: it is the only Fact whose
fields are all `cardinality: many`, so the C5 publication rule (which binds a
`one` field to a same-named capability output) exempts every one of them. Nothing
else was holding these seven names together, and they had already drifted —
`_PO_REQUIRED_EVIDENCE` ordered `plant` before `material` while the registry's
now-deleted `itemFields` ordered `material` before `plant`, and the TS evidence
literal carried a seventh key, `purchaseOrderItem`, that the ontology did not
declare at all until task 2.6a.

Two lock strengths are used, and the difference is deliberate:

* **Exact equality** for the TS evidence literal. It is the projection that
  *produces* the Fact, so it must publish precisely the declared field set —
  a missing key starves a declared field, an extra key is an undeclared one.
* **Subset** for the three `narrator.py` sites. Each is a *consumer*, and
  consuming fewer fields than are declared is legitimate: `_PO_REQUIRED_EVIDENCE`
  is a narration **precondition** (every listed field must be present and
  non-None or narration raises), so forcing it to equal the declared set would
  make narration reject any fact whose `purchaseOrderItem` happens to be absent.
  Changing runtime behaviour to satisfy a test is backwards. Subset still catches
  the drift that matters: a typo, or a field renamed in the ontology.

Task 2.7.4 requires evidence that each lock *fails* when the authority changes.
Each positive test is therefore paired with a negative one that runs the same
comparison against a declared set with one field renamed. The mutation is applied
to an in-memory copy, so there is no source file to restore.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

PO_FACT_TYPE_ID = "sapnexus:PurchaseOrderSupplyFact"

FACT_BUILDER_TS = REPO_ROOT / "frontend/src/runtime/projection/fact-builder.ts"
EVENT_PROJECTOR_TS = REPO_ROOT / "frontend/src/runtime/plan-evidence/event-projector.ts"
NARRATOR_PY = REPO_ROOT / "agent/sap_nexus_agent/narrator.py"


# ---- the authority ----


def _declared_fields(fact_type_id: str = PO_FACT_TYPE_ID) -> set[str]:
    catalog = yaml.safe_load(
        (REPO_ROOT / "ontology" / "fact-types.yaml").read_text(encoding="utf-8")
    )
    fact_type = next(
        item for item in catalog["factTypes"] if item["factTypeId"] == fact_type_id
    )
    return {field["name"] for field in fact_type["fields"]}


def _renamed(declared: set[str], original: str, replacement: str) -> set[str]:
    """The 2.7.4 mutation: the authority renames one field."""
    assert original in declared, original
    return (declared - {original}) | {replacement}


# ---- restated copies, read as text from their own source files ----


def _ts_evidence_keys() -> set[str]:
    source = FACT_BUILDER_TS.read_text(encoding="utf-8")
    builder = source[source.index("const purchaseOrderBuilder") :]
    marker = "evidence: [{"
    start = builder.index(marker) + len(marker)
    block = builder[start : builder.index("}]", start)]
    keys = set(re.findall(r"^\s*(\w+):", block, re.MULTILINE))
    assert keys, "failed to parse the evidence literal — the lock would be vacuous"
    return keys


def _narrator_source() -> str:
    return NARRATOR_PY.read_text(encoding="utf-8")


def _required_evidence_names() -> set[str]:
    source = _narrator_source()
    start = source.index("_PO_REQUIRED_EVIDENCE = (")
    block = source[start : source.index(")", start)]
    names = set(re.findall(r'"(\w+)"', block))
    assert names, "failed to parse _PO_REQUIRED_EVIDENCE"
    return names


def _list_message_keys() -> set[str]:
    """Keys the LLM prompt builder reads, via `ev.get('...')`."""
    keys = set(re.findall(r"ev\.get\(\'(\w+)\'", _narrator_source()))
    assert keys, "failed to parse the ev.get(...) keys"
    return keys


def _fallback_keys() -> set[str]:
    """Keys the deterministic fallback renders, via `evidence['...']`."""
    keys = set(re.findall(r"evidence\[\'(\w+)\'\]", _narrator_source()))
    assert keys, "failed to parse the evidence[...] keys"
    return keys


# ---- 2.6a: the seventh field is declared, so the TS lock can be exact ----


def test_purchase_order_item_is_a_declared_field():
    """`purchaseOrderItem` is load-bearing on the TS side — a member of
    `PurchaseOrderRow` and a component of `rowSortKey`, so it affects
    deterministic ordering. Task 2.5 missed it; 2.6a declares it."""
    assert "purchaseOrderItem" in _declared_fields()


# ---- 2.7.1: the producer lock is exact ----


def test_ts_evidence_literal_equals_the_declared_field_set():
    assert _ts_evidence_keys() == _declared_fields()


def test_ts_evidence_lock_fails_when_the_authority_renames_a_field():
    mutated = _renamed(_declared_fields(), "purchaseOrderUnit", "orderUnit")
    assert _ts_evidence_keys() != mutated


# ---- 2.7.2: the consumer locks are subsets ----


@pytest.mark.parametrize(
    "restated",
    [
        pytest.param(_required_evidence_names, id="_PO_REQUIRED_EVIDENCE"),
        pytest.param(_list_message_keys, id="_build_list_messages"),
        pytest.param(_fallback_keys, id="_list_fallback"),
    ],
)
def test_narrator_sites_only_consume_declared_fields(restated):
    assert restated() <= _declared_fields()


@pytest.mark.parametrize(
    "restated",
    [
        pytest.param(_required_evidence_names, id="_PO_REQUIRED_EVIDENCE"),
        pytest.param(_list_message_keys, id="_build_list_messages"),
        pytest.param(_fallback_keys, id="_list_fallback"),
    ],
)
def test_narrator_locks_fail_when_the_authority_renames_a_consumed_field(restated):
    """`supplier` is consumed by all three sites, so renaming it in the authority
    must break every one of them. A subset lock that survives this would be
    vacuous."""
    mutated = _renamed(_declared_fields(), "supplier", "vendorName")
    assert not restated() <= mutated


# ---- 2.7: correction C9 — event-projector.ts:69 is NOT a restatement site ----


def test_event_projector_fact_allowlist_is_not_a_field_list_restatement():
    """`ALLOWED_PAYLOAD_KEYS.fact` governs which keys survive projection into a
    ReasoningFact **envelope**. Task 2.7 originally listed it as a Fact field-list
    restatement; it is not one, and locking it against `ontology/fact-types.yaml`
    would assert equality between two unrelated sets.

    Asserted positively rather than left as a note, so a future reader cannot
    re-make the mistake: the allowlist contains envelope keys no Fact Type
    declares, and omits PO fields every Fact Type consumer needs.
    """
    source = EVENT_PROJECTOR_TS.read_text(encoding="utf-8")
    start = source.index("fact:", source.index("ALLOWED_PAYLOAD_KEYS"))
    block = source[start : source.index("]", start)]
    allowlist = set(re.findall(r'"(\w+)"', block))
    assert allowlist, "failed to parse ALLOWED_PAYLOAD_KEYS.fact"

    envelope_only = {"factId", "factTypeId", "asOf"}
    assert envelope_only <= allowlist, envelope_only - allowlist
    all_declared = set().union(
        *(
            _declared_fields(fact_type_id)
            for fact_type_id in (
                "sapnexus:InventoryAvailabilityFact",
                PO_FACT_TYPE_ID,
                "sapnexus:PurchaseRequisitionCreatedFact",
            )
        )
    )
    assert not envelope_only & all_declared
    assert not _declared_fields() <= allowlist


# ---- 2.7.3: Java ----


def test_no_java_main_source_restates_a_purchase_order_only_field():
    """A tripwire, not a lock, and scoped to what it can honestly assert.

    2.7.3 asks which Java DTOs restate a Fact field list. The answer is **none**,
    and the reasoning is a derivation chain rather than an absence of grep hits:

    * Java main sources do name three Fact field names — `availableQuantity`,
      `mrpElementLines`, `prNumber` — but each is a **declared capability output**,
      and the C5 publication rule already binds every `cardinality: one` field to
      a same-named output. Those are derived through the registry.
    * `material`, `plant` and `supplier` appear widely because they are declared
      capability **input** names (`supplier` is `MM.PurchaseOrder.GetList`'s
      `vendor.semanticName`). In-contract, not restatements.
    * `purchaseOrder` appears in exactly two Java **test** files, as a two-field
      stub OData row payload and as a fixture method name — a partial fixture, not
      an enumeration of the Fact's fields, and not a DTO.

    So the tripwire targets the PO fields no capability signature mentions, which
    is derived from the registry rather than hand-picked, and asserts they appear
    in no Java *main* source. A DTO lives in `src/main/java`; scoping there is
    what keeps the assertion from firing on test stubs.
    """
    registry = yaml.safe_load(
        (REPO_ROOT / "registry" / "capabilities.yaml").read_text(encoding="utf-8")
    )
    contract_names: set[str] = set()
    for capability in registry["capabilities"]:
        for container in ("inputs", "outputs"):
            for field in capability.get(container) or ():
                contract_names.add(field["name"])
                if field.get("semanticName"):
                    contract_names.add(field["semanticName"])

    fact_only = _declared_fields() - contract_names
    assert fact_only, "every PO field is in-contract — the tripwire would be vacuous"

    java_main = list((REPO_ROOT / "services").rglob("src/main/java/**/*.java"))
    assert java_main, "no Java main sources found — the tripwire would be vacuous"
    offenders = {
        f"{path.relative_to(REPO_ROOT)}:{field}"
        for path in java_main
        for field in fact_only
        if re.search(rf"\b{re.escape(field)}\b", path.read_text(encoding="utf-8"))
    }
    assert offenders == set(), offenders


# ---- 2.6: the deleted restatement stays deleted ----


def test_purchase_order_narrative_declares_no_field_mapping():
    """`itemFields` had no consumer: `field_mapping` is read only by
    `_resolve_template_vars`, reached only from the `single-value` narration body,
    while the `list` path hardcodes its own names. Deleting it was the only option
    that removed the copy rather than freezing a dead one in place (task 2.6).
    """
    registry = yaml.safe_load(
        (REPO_ROOT / "registry" / "capabilities.yaml").read_text(encoding="utf-8")
    )
    capability = next(
        item
        for item in registry["capabilities"]
        if item["capabilityId"] == "MM.PurchaseOrder.GetList"
    )
    narrative = capability["narrative"]
    assert narrative["factShape"] == "list"
    assert "fieldMapping" not in narrative
