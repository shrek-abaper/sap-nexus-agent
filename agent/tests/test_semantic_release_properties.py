"""Determinism, change sensitivity, insulation, and tamper properties."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from sap_nexus_agent.semantic_release.builder import build_semantic_release
from sap_nexus_agent.semantic_planning.loader import load_semantic_sources
from sap_nexus_agent.semantic_planning.validation import build_semantic_contracts

REPO_ROOT = Path(__file__).resolve().parents[2]

LEGACY_FILES = [
    "registry/capabilities.yaml",
    "registry/executor-bindings.yaml",
    "registry/semantic-types.yaml",
    "ontology/fact-types.yaml",
    "ontology/capability-relations.yaml",
]
SEMANTIC_FILES = [
    "ontology/analysis-fact-fields.yaml",
    "ontology/analysis-operators.yaml",
    "ontology/analysis-versions.yaml",
    "ontology/definition-applicability.yaml",
    "ontology/object-types.yaml",
    "ontology/definitions.yaml",
    "ontology/object-links.yaml",
    "ontology/business-rules.yaml",
]


@pytest.fixture
def mini_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for rel in LEGACY_FILES + SEMANTIC_FILES:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / rel, target)
    shutil.copytree(REPO_ROOT / "schemas", tmp_path / "schemas")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _build_ids(root: Path) -> tuple[str, str, list[dict]]:
    document = build_semantic_release(root).to_dict()
    return (
        document["registrySnapshotId"],
        document["semanticSnapshotId"],
        document["sources"],
    )


def test_byte_deterministic_and_sorted_sources(mini_repo: Path):
    first = build_semantic_release(mini_repo).to_dict()
    second = build_semantic_release(mini_repo).to_dict()
    assert first == second
    paths = [row["path"] for row in first["sources"]]
    assert paths == sorted(paths)


def test_legacy_snapshot_id_is_the_unchanged_registry_snapshot(mini_repo: Path):
    package = build_semantic_release(mini_repo).to_dict()
    contracts = build_semantic_contracts(load_semantic_sources(mini_repo))
    assert contracts.snapshot is not None
    assert package["registrySnapshotId"] == contracts.snapshot.snapshot_id


def _mutate(root: Path, rel: str, mutate_fn) -> None:
    path = root / rel
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate_fn(document)
    path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "rel,mutate_fn",
    [
        ("ontology/object-types.yaml",
         lambda d: d["objectTypes"].append(
             {"objectTypeId": "sapnexus:Vendor",
              "semanticType": "sapnexus:Supplier",
              "keyFields": ["supplier"], "scopeFields": []})),
        ("ontology/analysis-fact-fields.yaml",
         lambda d: d["allowlist"].append(
             {"factTypeId": "sapnexus:MaterialInfoFact",
              "fields": [{"name": "material",
                          "semanticType": "sapnexus:MaterialNumber"}]})),
        ("ontology/analysis-operators.yaml",
         lambda d: d["operators"][0]["constraints"].append("new-constraint")),
        ("ontology/definition-applicability.yaml",
         lambda d: d["applicability"].append(
             {"definitionId": "sapnexus:def.available-for-commitment",
              "status": "grounded", "applicableScopes": ["MM"]})),
        ("ontology/analysis-versions.yaml",
         lambda d: d.update(compilerVersion="0.2.0")),
        ("ontology/definitions.yaml",
         lambda d: d["definitions"][1].update(title="Changed title")),
        ("ontology/object-links.yaml",
         lambda d: d["links"][0].update(linkType="changed-link")),
        ("ontology/business-rules.yaml",
         lambda d: d.update(version=2)),
    ],
)
def test_semantic_change_moves_semantic_id_only(mini_repo: Path, rel, mutate_fn):
    baseline_registry, baseline_semantic, baseline_sources = _build_ids(mini_repo)
    baseline_digest = next(
        row["digest"] for row in baseline_sources if row["path"] == rel
    )
    _mutate(mini_repo, rel, mutate_fn)
    new_registry, new_semantic, new_sources = _build_ids(mini_repo)
    new_digest = next(row["digest"] for row in new_sources if row["path"] == rel)
    assert new_semantic != baseline_semantic
    assert new_digest != baseline_digest
    assert new_registry == baseline_registry


def test_outsider_file_does_not_move_ids(mini_repo: Path):
    _, baseline_semantic, _ = _build_ids(mini_repo)
    (mini_repo / "ontology/random.yaml").write_text(
        "version: 1\n", encoding="utf-8"
    )
    (mini_repo / "notes.txt").write_text("noise", encoding="utf-8")
    _, new_semantic, _ = _build_ids(mini_repo)
    assert new_semantic == baseline_semantic


def test_tampered_digest_fails_structural_validation(mini_repo: Path):
    from sap_nexus_agent.semantic_release.validation import validate_structure

    package = build_semantic_release(mini_repo).to_dict()
    assets = {
        row["path"]: yaml.safe_load((mini_repo / row["path"]).read_text())
        for row in package["sources"]
        if row["role"] == "semantic"
    }
    package["sources"][0]["digest"] = "sha256:" + "9" * 64
    report = validate_structure(
        package, assets,
        registry_snapshot_id=package["registrySnapshotId"],
        repo_root=mini_repo,
    )
    assert any(issue.code == "SR_DIGEST_MISMATCH" for issue in report.issues)
