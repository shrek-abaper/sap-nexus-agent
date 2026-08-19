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
