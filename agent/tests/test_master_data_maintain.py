"""Real-PG tests for the master-data maintenance CLI.

Edits always flow through governed full snapshots: dry-run by default,
atomic publish with --apply, and the previous snapshot stays live until the
new one commits.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg
import pytest

from sap_nexus_agent.master_data.importer import import_snapshot
from sap_nexus_agent.master_data.maintain import load_active_batch, main as maintain_main

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "master-data" / "fixtures"
MIGRATION = REPO_ROOT / "db" / "migrations" / "0001_master_data.sql"
TEST_DBNAME = os.environ.get("SAP_NEXUS_MD_TEST_DBNAME", "sap_nexus_maintain_test")

MATERIAL = "sapnexus:Material"
CUSTOMER = "sapnexus:Customer"


@pytest.fixture(scope="module")
def pg():
    try:
        with psycopg.connect(dbname="postgres", autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (TEST_DBNAME,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{TEST_DBNAME}"')
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL not reachable for maintain tests")
    try:
        with psycopg.connect(dbname=TEST_DBNAME, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS md CASCADE")
            cur.execute(MIGRATION.read_text(encoding="utf-8"))
    except psycopg.OperationalError:
        pytest.skip(f"test database {TEST_DBNAME} not reachable")
    os.environ["SAP_NEXUS_MD_DBNAME"] = TEST_DBNAME
    for name in ("materials-v1", "customers-v1"):
        document = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
        report = import_snapshot(document)
        assert not report.errors
    yield TEST_DBNAME


def _active_codes(object_type: str) -> dict[str, str]:
    batch = load_active_batch(object_type)
    return {e["canonicalCode"]: e["status"] for e in batch["entities"]}


def test_upsert_new_entity_dry_run_then_apply(pg, capsys):
    args = [
        "upsert", MATERIAL, "DEMOX1",
        "--name-zh", "丁腈密封垫 3mm",
        "--attr", "materialGroup=GASKET", "--attr", "sizeDimension=3mm",
        "--attr", "baseUnitOfMeasure=EA", "--org", "plant=1000",
    ]
    assert maintain_main(args) == 0  # dry-run
    assert "DRY-RUN" in capsys.readouterr().out
    assert "DEMOX1" not in _active_codes(MATERIAL)

    assert maintain_main(args + ["--apply"]) == 0
    out = capsys.readouterr().out
    assert "PUBLISHED" in out
    assert _active_codes(MATERIAL)["DEMOX1"] == "active"
    # previous entities survive the full-snapshot replace
    assert _active_codes(MATERIAL)["DEMOA1"] == "active"


def test_upsert_updates_existing_entity(pg, capsys):
    assert maintain_main([
        "upsert", MATERIAL, "DEMOX1",
        "--attr", "sizeDimension=3.5mm", "--alias", "丁腈垫",
        "--apply",
    ]) == 0
    batch = load_active_batch(MATERIAL)
    entity = next(e for e in batch["entities"] if e["canonicalCode"] == "DEMOX1")
    assert entity["attributes"]["sizeDimension"] == "3.5mm"
    assert entity["attributes"]["materialGroup"] == "GASKET"  # merge keeps other attrs
    assert any(a["alias"] == "丁腈垫" for a in entity["aliases"])
    # zh description preserved from the first upsert and still official
    official = [d for d in entity["descriptions"] if d["official"]]
    assert len(official) == 1 and official[0]["text"] == "丁腈密封垫 3mm"


def test_deactivate_and_reactivate(pg):
    assert maintain_main(["deactivate", CUSTOMER, "C10001", "--apply"]) == 0
    assert _active_codes(CUSTOMER)["C10001"] == "inactive"
    assert maintain_main(["activate", CUSTOMER, "C10001", "--apply"]) == 0
    assert _active_codes(CUSTOMER)["C10001"] == "active"


def test_remove_deletes_from_next_snapshot(pg):
    assert "DEMOC9" in _active_codes(MATERIAL)
    assert maintain_main(["remove", MATERIAL, "DEMOC9", "--apply"]) == 0
    assert "DEMOC9" not in _active_codes(MATERIAL)
    # removing again is a no-op, not an error
    assert maintain_main(["remove", MATERIAL, "DEMOC9", "--apply"]) == 0


def test_repeated_apply_is_idempotent(pg, capsys):
    before = load_active_batch(MATERIAL)["_snapshotId"]
    assert maintain_main(["deactivate", MATERIAL, "DEMOA2", "--apply"]) == 0
    # apply the same state again -> content hash unchanged -> idempotent reuse
    assert maintain_main(["remove", MATERIAL, "DEMOC9", "--apply"]) == 0
    out = capsys.readouterr().out
    assert "IDEMPOTENT" in out
    assert load_active_batch(MATERIAL)["_snapshotId"] != before  # deactivate published


def test_export_round_trip(pg, tmp_path, capsys):
    backup = tmp_path / "backup.json"
    assert maintain_main(["export", MATERIAL, str(backup)]) == 0
    document = json.loads(backup.read_text(encoding="utf-8"))
    assert document["batch"]["objectType"] == MATERIAL
    assert document["entities"], "export must carry entities"
    # exported batch re-imports idempotently against the current snapshot
    report = import_snapshot(document)
    assert not report.errors
    assert report.idempotent_reuse


def test_invalid_attribute_rejected_without_publish(pg, capsys):
    before = load_active_batch(MATERIAL)["_snapshotId"]
    rc = maintain_main([
        "upsert", MATERIAL, "DEMOY2",
        "--name-zh", "非法属性物料", "--attr", "ghostField=x", "--apply",
    ])
    assert rc == 1
    assert "ERROR" in capsys.readouterr().out
    assert load_active_batch(MATERIAL)["_snapshotId"] == before  # nothing published


def test_upsert_requires_exactly_one_official_description(pg):
    # zh name becomes the single official; adding en later keeps one official
    assert maintain_main([
        "upsert", MATERIAL, "DEMOZ3",
        "--name-en", "NBR gasket 3mm", "--name-zh", "丁腈密封垫 Z3",
        "--attr", "materialGroup=GASKET", "--attr", "sizeDimension=3mm",
        "--attr", "baseUnitOfMeasure=EA", "--apply",
    ]) == 0
    entity = next(
        e for e in load_active_batch(MATERIAL)["entities"] if e["canonicalCode"] == "DEMOZ3"
    )
    assert sum(1 for d in entity["descriptions"] if d["official"]) == 1
    assert next(d for d in entity["descriptions"] if d["official"])["language"] == "zh-CN"
