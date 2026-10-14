"""Release pinning tests: execution binds the exact generated package."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sap_nexus_agent.ontology_planning.release import (
    PinnedRelease,
    ReleaseStaleError,
    pin_release,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_pin_real_repo_matches_tracked_artifact():
    pinned = pin_release(REPO_ROOT)
    assert isinstance(pinned, PinnedRelease)
    tracked = json.loads(
        (REPO_ROOT / "ontology/generated/semantic-release.json").read_text()
    )
    assert pinned.package.to_dict()["semanticSnapshotId"] == tracked["semanticSnapshotId"]
    assert pinned.package.registry_snapshot_id == tracked["registrySnapshotId"]


def test_pinned_allowlist_and_operators():
    pinned = pin_release(REPO_ROOT)
    assert pinned.allowlist_fields["sapnexus:PurchaseOrderSupplyFact"] == {
        "purchaseOrder", "purchaseOrderItem", "supplier", "material",
        "plant", "orderQuantity", "purchaseOrderUnit",
    }
    assert pinned.allowlist_fields["sapnexus:InventoryAvailabilityFact"] == {
        "availableQuantity"
    }
    assert pinned.operators == frozenset(
        {"select_fields", "filter_eq", "group_sum", "compare"}
    )
    assert pinned.compiler_version == "0.1.0"


def test_stale_artifact_fails_closed(tmp_path: Path):
    # Build a minimal repo copy by reusing the builder's own output logic.
    import shutil

    for rel in ("registry", "ontology", "schemas"):
        source = REPO_ROOT / rel
        target = tmp_path / rel
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    # Tamper the tracked artifact.
    artifact = tmp_path / "ontology/generated/semantic-release.json"
    document = json.loads(artifact.read_text())
    document["compilerVersion"] = "9.9.9"
    artifact.write_text(json.dumps(document))
    with pytest.raises(ReleaseStaleError):
        pin_release(tmp_path)
