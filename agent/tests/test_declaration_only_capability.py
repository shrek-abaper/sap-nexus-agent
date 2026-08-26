"""Task 19: declaration-only capability end-to-end proof.

Writes a temporary registry pair (capabilities.yaml + semantic-types.yaml)
containing ONLY ONE brand-new capability that does not exist anywhere in the
real registry, points ``load_intent_catalog`` at that temporary location via
the ``SAP_NEXUS_AGENT_ROOT`` environment variable (the mechanism
``registry_loader._resolve_registry_path`` actually exposes), and asserts
through the PRODUCTION ``sap_nexus_agent.intent.parse_intent`` entry point
that the capability triggers, extracts its declared input, computes the
missing parameter, and renders the declared CLARIFY text - with zero
``agent/sap_nexus_agent`` code referencing the capability id, its primary
keyword, or its semantic type. This is the executable form of the delta
spec's "Declared capability recognized without code change" scenario.
"""
from __future__ import annotations

from pathlib import Path

from sap_nexus_agent.intent import parse_intent

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_SRC = REPO_ROOT / "agent" / "sap_nexus_agent"

CAPABILITY_ID = "Test.Sample.GetStockNote"
PRIMARY_KEYWORD = "样本备注"
SEMANTIC_TYPE_ID = "SampleNoteCode"
CLARIFY_TEXT = "请提供样本备注编号。"

CAPABILITIES_YAML = f"""\
version: 2
capabilities:
  - capabilityId: {CAPABILITY_ID}
    name: Sample Stock Note Fixture
    description: Fixture-only capability declared purely for a declaration-only end-to-end test.
    status: active
    kind: Function
    domain: Test
    businessObject: SampleStockNote
    intent:
      intentName: sample_get_stock_note
      primaryKeywords:
        - '{PRIMARY_KEYWORD}'
      clarifyPrompt:
        zh-CN:
          cases:
            - missing:
                - noteCode
              text: '{CLARIFY_TEXT}'
    inputs:
      - name: noteCode
        semanticName: noteCode
        semanticType: sapnexus:SampleNoteCode
        required: true
        type: string
        extraction:
          matchers:
            - kind: semanticType
              ref: {SEMANTIC_TYPE_ID}
          priority: 10
          resolver: text
"""

# Raw string: the YAML pattern is single-quoted, so PyYAML keeps the
# backslash literal - the regex must see `\s`, not an already-escaped space.
SEMANTIC_TYPES_YAML = r"""version: 1
semanticTypes:
  - id: SampleNoteCode
    priority: 10
    matchers:
      - kind: regex
        pattern: '备注编号\s*([A-Z0-9]+)'
"""


def _write_registry(tmp_path: Path) -> None:
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    (registry_dir / "capabilities.yaml").write_text(CAPABILITIES_YAML, encoding="utf-8")
    (registry_dir / "semantic-types.yaml").write_text(SEMANTIC_TYPES_YAML, encoding="utf-8")


def _assert_capability_referenced_nowhere_in_agent_source() -> None:
    """(d) design property: the fixture capability id, its primary keyword,
    and its semantic type id appear NOWHERE under agent/sap_nexus_agent - only
    in this test file and the temporary fixture data it writes to tmp_path."""
    offenders: dict[str, list[str]] = {
        CAPABILITY_ID: [],
        PRIMARY_KEYWORD: [],
        SEMANTIC_TYPE_ID: [],
    }
    for path in AGENT_SRC.rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        for needle, hits in offenders.items():
            if needle in content:
                hits.append(str(path.relative_to(REPO_ROOT)))

    assert offenders == {CAPABILITY_ID: [], PRIMARY_KEYWORD: [], SEMANTIC_TYPE_ID: []}


def test_declaration_only_capability_full_rule_mode_flow(tmp_path, monkeypatch):
    """Full rule-mode round trip through the production parse_intent entry
    point, using only a temporary registry that ``load_intent_catalog``
    resolves via the ``SAP_NEXUS_AGENT_ROOT`` env var (registry_loader.py's
    ``_resolve_registry_path``, step 2)."""
    # (d) zero agent/sap_nexus_agent code references the fixture capability -
    # checked first, independent of tmp_path/env var setup below.
    _assert_capability_referenced_nowhere_in_agent_source()

    _write_registry(tmp_path)
    monkeypatch.setenv("SAP_NEXUS_AGENT_ROOT", str(tmp_path))

    # (a) triggers on its primary keyword, (b) input value extracted when present.
    present = parse_intent("查询样本备注，备注编号 NOTE001")
    assert present.capability_id == CAPABILITY_ID
    assert present.parameters.get("noteCode") == "NOTE001"
    assert present.missing_parameters == []

    # (c) missing required input -> missing_parameters + declared CLARIFY text.
    missing = parse_intent("查询样本备注")
    assert missing.capability_id == CAPABILITY_ID
    assert missing.missing_parameters == ["noteCode"]
    assert missing.clarification == CLARIFY_TEXT


# ---- Verify-phase finding R7: the real 4th capability had no such lock ----
#
# `_assert_capability_referenced_nowhere_in_agent_source` above locks a *fixture*
# capability out of the agent source, which proves the mechanism. It said nothing
# about `MM.Material.GetInfo`, the capability this change actually registered, so
# invariant 6's "adding the 4th capability requires no code" rested on a
# `git diff` taken at one moment rather than on a standing check.


REAL_FOURTH_CAPABILITY_ID = "MM.Material.GetInfo"
REAL_FOURTH_FACT_TYPE_ID = "sapnexus:MaterialInfoFact"


def test_the_fourth_capability_is_named_nowhere_in_production_source():
    """R7 — invariant 6 as a standing check rather than a one-off diff.

    The capability id and its Fact Type id must not appear in any production
    source file, in any language. Tests, evals, docs and the registry itself are
    excluded: naming it there is the point. Java and TypeScript are included
    because correction C13 established that a Python-only measurement cannot see
    the real cost of adding a capability.
    """
    roots = [
        REPO_ROOT / "agent" / "sap_nexus_agent",
        REPO_ROOT / "scripts",
        REPO_ROOT / "services" / "gateway",
        REPO_ROOT / "frontend" / "src",
    ]
    patterns = ("*.py", "*.java", "*.ts", "*.tsx")
    offenders: dict[str, list[str]] = {
        REAL_FOURTH_CAPABILITY_ID: [],
        REAL_FOURTH_FACT_TYPE_ID: [],
    }
    scanned = 0
    for root in roots:
        if not root.exists():
            continue
        for pattern in patterns:
            for path in root.rglob(pattern):
                parts = set(path.parts)
                if "build" in parts or "node_modules" in parts or "test" in parts:
                    continue
                if path.name.endswith((".test.ts", ".test.tsx")):
                    continue
                scanned += 1
                content = path.read_text(encoding="utf-8", errors="ignore")
                for needle, hits in offenders.items():
                    if needle in content:
                        hits.append(str(path.relative_to(REPO_ROOT)))

    assert scanned > 100, f"scan found only {scanned} files - the globs are wrong"
    assert offenders == {
        REAL_FOURTH_CAPABILITY_ID: [],
        REAL_FOURTH_FACT_TYPE_ID: [],
    }


def test_the_fourth_capability_is_named_in_the_registry_and_ontology():
    """Positive control for R7: the absence above must mean "declared, not absent".

    Without this, deleting the capability entirely would satisfy the lock.
    """
    import yaml

    # Parsed, not substring-matched. Mutation M45 renamed the capability to
    # `MM.Material.GetInfoXX` and a substring check passed, because the original
    # id is a prefix of the renamed one - the positive control was vacuous
    # against exactly the mutation it existed to catch.
    registry = yaml.safe_load(
        (REPO_ROOT / "registry" / "capabilities.yaml").read_text(encoding="utf-8")
    )
    fact_types = yaml.safe_load(
        (REPO_ROOT / "ontology" / "fact-types.yaml").read_text(encoding="utf-8")
    )
    bindings = yaml.safe_load(
        (REPO_ROOT / "registry" / "executor-bindings.yaml").read_text(encoding="utf-8")
    )

    capability = next(
        (
            c
            for c in registry["capabilities"]
            if c["capabilityId"] == REAL_FOURTH_CAPABILITY_ID
        ),
        None,
    )
    assert capability is not None, "the fourth capability is not registered at all"
    assert capability["status"] == "active"
    assert capability["kind"] == "Function"
    assert {
        output["factTypeRef"]
        for output in capability["outputs"]
        if "factTypeRef" in output
    } == {REAL_FOURTH_FACT_TYPE_ID}
    assert REAL_FOURTH_FACT_TYPE_ID in {
        fact_type["factTypeId"] for fact_type in fact_types["factTypes"]
    }
    assert capability["executorBinding"]["bindingId"] in {
        binding["bindingId"] for binding in bindings["bindings"]
    }
