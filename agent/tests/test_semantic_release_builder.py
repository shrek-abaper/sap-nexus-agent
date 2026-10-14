"""Builder assembly tests for SemanticRelease v1 packages."""

from __future__ import annotations

from pathlib import Path

from sap_nexus_agent.semantic_release.builder import build_semantic_release
from sap_nexus_agent.semantic_release.validation import validate_structure
from sap_nexus_agent.semantic_planning.snapshot import canonical_json_bytes

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_build_package_happy_path():
    pkg = build_semantic_release(REPO_ROOT)
    document = pkg.to_dict()
    assert document["schemaVersion"] == 1
    assert document["registrySnapshotId"].startswith("sha256:")
    assert document["semanticSnapshotId"].startswith("sha256:")
    assert {source["role"] for source in document["sources"]} == {
        "legacy",
        "semantic",
    }
    legacy = [s for s in document["sources"] if s["role"] == "legacy"]
    assert len(legacy) == 5
    semantic = [s for s in document["sources"] if s["role"] == "semantic"]
    assert len(semantic) == 8
    assert document["businessValidity"] == {"applicability": []}
    assert document["compilerVersion"] == "0.1.0"


def test_build_is_byte_deterministic():
    first = build_semantic_release(REPO_ROOT).to_dict()
    second = build_semantic_release(REPO_ROOT).to_dict()
    assert canonical_json_bytes(first) == canonical_json_bytes(second)


def test_built_package_passes_structural_validation():
    pkg = build_semantic_release(REPO_ROOT)
    document = pkg.to_dict()
    assets = {
        source["path"]: _document(source["path"])
        for source in document["sources"]
        if source["role"] == "semantic"
    }
    report = validate_structure(
        document,
        assets,
        registry_snapshot_id=document["registrySnapshotId"],
        repo_root=REPO_ROOT,
    )
    assert report.valid, [str(issue) for issue in report.issues]


def _document(rel_path: str) -> dict:
    import yaml

    return yaml.safe_load((REPO_ROOT / rel_path).read_text(encoding="utf-8"))
