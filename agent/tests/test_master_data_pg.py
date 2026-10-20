"""Real-PostgreSQL tests for the master-data snapshot store and provider.

These tests run against a real local PostgreSQL (prompt phase A exit: no
Mock provider may replace PG integration tests). They skip only when no
database is reachable, and the skip is reported honestly in verification.

Setup (one time, peer auth):
    createdb sap_nexus_test
    psql -d sap_nexus_test -f db/migrations/0001_master_data.sql
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg
import pytest

from sap_nexus_agent.master_data import (
    EntityKey,
    MasterDataProvider,
    ProviderError,
    SearchRequest,
    TrustedScope,
    import_snapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "master-data" / "fixtures"
MIGRATION = REPO_ROOT / "db" / "migrations" / "0001_master_data.sql"
TEST_DBNAME = os.environ.get("SAP_NEXUS_MD_TEST_DBNAME", "sap_nexus_test")

SCOPE = TrustedScope(principal="test-principal", source_systems=("S4H",), clients=("100",))


def _admin_connect(dbname: str):
    return psycopg.connect(dbname=dbname, autocommit=True)


@pytest.fixture(scope="module")
def pg():
    """Fresh md schema + all v1 fixtures in a dedicated test database."""
    try:
        with _admin_connect("postgres") as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (TEST_DBNAME,))
                if cur.fetchone() is None:
                    cur.execute(f'CREATE DATABASE "{TEST_DBNAME}"')
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL not reachable for master-data tests")

    try:
        with _admin_connect(TEST_DBNAME) as conn:
            with conn.cursor() as cur:
                cur.execute("DROP SCHEMA IF EXISTS md CASCADE")
                cur.execute(MIGRATION.read_text(encoding="utf-8"))
    except psycopg.OperationalError:
        pytest.skip(f"test database {TEST_DBNAME} not reachable")

    os.environ["SAP_NEXUS_MD_DBNAME"] = TEST_DBNAME
    for name in ("materials-v1", "customers-v1", "suppliers-v1"):
        document = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
        report = import_snapshot(document)
        assert not report.errors, report.errors
    yield TEST_DBNAME


@pytest.fixture()
def provider(pg):
    p = MasterDataProvider.connect()
    yield p
    p.close()


# ---------------------------------------------------------------------------
# Importer (prompt §11 case 10, §5.3)
# ---------------------------------------------------------------------------

def test_dry_run_publishes_nothing(pg):
    document = json.loads((FIXTURES / "materials-v2.json").read_text(encoding="utf-8"))
    report = import_snapshot(document, dry_run=True)
    assert not report.errors
    assert report.dry_run and report.superseded_snapshot_ids
    with _admin_connect(pg) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM md.snapshot WHERE status='active' AND object_type='sapnexus:Material'")
        assert cur.fetchone()[0] == 1  # still the v1 snapshot


def test_reimport_is_idempotent(pg):
    document = json.loads((FIXTURES / "materials-v1.json").read_text(encoding="utf-8"))
    first = import_snapshot(document)
    second = import_snapshot(document)
    assert second.idempotent_reuse and second.snapshot_id == first.snapshot_id


def test_full_snapshot_replaces_only_declared_coverage(pg):
    document = json.loads((FIXTURES / "materials-v2.json").read_text(encoding="utf-8"))
    report = import_snapshot(document)
    assert not report.errors and not report.idempotent_reuse
    assert len(report.superseded_snapshot_ids) == 1

    p = MasterDataProvider.connect()
    # DEMOB1 / DEMOC9 disappeared with the replaced snapshot.
    gone = p.search(SearchRequest("md.material.search", query="Ø20.5"), SCOPE)
    assert gone.candidates == ()
    # Customer snapshot is untouched by the material replacement.
    customers = p.search(SearchRequest("md.customer.search", query="华远机械"), SCOPE)
    assert len(customers.candidates) == 2
    p.close()


def test_invalid_batch_never_partially_publishes(pg):
    document = json.loads((FIXTURES / "customers-v1.json").read_text(encoding="utf-8"))
    document["entities"].append(dict(document["entities"][0]))  # duplicate identity
    before = import_snapshot(json.loads((FIXTURES / "customers-v1.json").read_text(encoding="utf-8")))
    report = import_snapshot(document)
    assert report.errors and report.snapshot_id is None
    after = import_snapshot(json.loads((FIXTURES / "customers-v1.json").read_text(encoding="utf-8")))
    assert after.idempotent_reuse and after.snapshot_id == before.snapshot_id


def test_incremental_snapshot_kind_rejected(pg):
    document = json.loads((FIXTURES / "customers-v1.json").read_text(encoding="utf-8"))
    document["batch"]["snapshotKind"] = "incremental"
    report = import_snapshot(document)
    assert any("only full snapshots" in error for error in report.errors)


def test_unknown_source_time_not_faked(pg):
    with _admin_connect(pg) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT source_extracted_at, loaded_at FROM md.v_snapshot_current"
            " WHERE object_type='sapnexus:Customer'"
        )
        extracted_at, loaded_at = cur.fetchone()
    assert extracted_at is None  # customers fixture declares null
    assert loaded_at is not None


# ---------------------------------------------------------------------------
# Provider retrieval (prompt §11 cases 1-9, 11, 12)
# ---------------------------------------------------------------------------

def test_description_fragment_recalls_real_codes(provider):
    result = provider.search(SearchRequest("md.material.search", query="蓝色耐高温密封圈"), SCOPE)
    codes = {c.key.canonical_code for c in result.candidates}
    assert {"DEMOA1", "DEMOA2"} <= codes  # case 1
    # v2 removed DEMOB1/DEMOC9 from the active snapshot
    assert "DEMOC9" not in codes  # case 9: inactive never a candidate
    assert result.completeness == "complete-result-set"


def test_same_name_different_spec_yields_multiple_candidates(provider):
    result = provider.search(SearchRequest("md.material.search", query="蓝色耐高温密封圈"), SCOPE)
    by_code = {c.key.canonical_code: c for c in result.candidates}
    # case 2: the same Chinese name with different specs yields multiple
    # candidates whose distinguishing attributes keep the specs apart
    assert {"DEMOA1", "DEMOA2"} <= set(by_code)
    assert by_code["DEMOA1"].distinguishing["sizeDimension"] == "20mm"
    assert by_code["DEMOA2"].distinguishing["sizeDimension"] == "25mm"


def test_short_name_maps_to_multiple_legal_entities(provider):
    customers = provider.search(SearchRequest("md.customer.search", query="华远机械"), SCOPE)
    assert {c.key.canonical_code for c in customers.candidates} == {"C10001", "C10002"}  # case 3
    suppliers = provider.search(SearchRequest("md.supplier.search", query="宏达"), SCOPE)
    assert {c.key.canonical_code for c in suppliers.candidates} == {"V10001", "V10002"}
    assert all(c.match_kind == "approved-alias" for c in suppliers.candidates)


def test_multilanguage_alias_org_rows_do_not_duplicate(provider):
    result = provider.search(SearchRequest("md.material.search", query="Blue high-temp seal ring D20"), SCOPE)
    assert [c.key.canonical_code for c in result.candidates] == ["DEMOA1"]  # case 4
    result = provider.search(
        SearchRequest("md.material.search", query="密封圈", org_filters={"plant": "2000"}), SCOPE
    )
    assert [c.key.canonical_code for c in result.candidates] == ["DEMOA1"]


def test_same_code_across_object_types_not_confused(provider):
    # V10001 exists as Supplier; as a Customer key it must not resolve.
    assert provider.get_by_key(EntityKey("S4H", "100", "sapnexus:Customer", "V10001"), SCOPE) is None
    supplier = provider.get_by_key(EntityKey("S4H", "100", "sapnexus:Supplier", "V10001"), SCOPE)
    assert supplier is not None and supplier.key.object_type == "sapnexus:Supplier"  # case 5


def test_code_shapes_preserved(provider):
    assert provider.get_by_key(EntityKey("S4H", "100", "sapnexus:Material", "00SEAL01"), SCOPE)
    assert provider.get_by_key(EntityKey("S4H", "100", "sapnexus:Customer", "0CUST09"), SCOPE)
    special = provider.get_by_key(EntityKey("S4H", "100", "sapnexus:Material", "SEAL-HT/B"), SCOPE)
    assert special is not None and special.key.canonical_code == "SEAL-HT/B"  # case 6
    decimal = provider.search(SearchRequest("md.material.search", query="垫片 1.5mm"), SCOPE)
    assert any(c.distinguishing.get("sizeDimension") == "1.5mm" for c in decimal.candidates)


def test_short_input_bounded_no_trigram(provider):
    # case 7: a two-char/one-char input must not fall into trigram recall
    result = provider.search(SearchRequest("md.material.search", query="垫片"), SCOPE)
    assert all(c.match_kind != "trigram" for c in result.candidates)
    assert any(c.key.canonical_code == "SEAL-HT/B" for c in result.candidates)


def test_injection_and_wildcards_stay_literal(provider):
    for payload in ("%' OR '1'='1", "%", "_", "\\%"):
        result = provider.search(SearchRequest("md.material.search", query=payload), SCOPE)
        assert result.candidates == (), payload  # case 8
    # A wildcard that genuinely appears in data only matches literally.
    result = provider.search(SearchRequest("md.customer.search", query="5% 折扣"), SCOPE)
    assert [c.key.canonical_code for c in result.candidates] == ["0CUST09"]


def test_inactive_and_nonexistent_codes_distinguished(provider):
    inactive = provider.get_by_key(EntityKey("S4H", "100", "sapnexus:Supplier", "V90000"), SCOPE)
    assert inactive is not None and inactive.status == "inactive"  # case 9
    assert provider.get_by_key(EntityKey("S4H", "100", "sapnexus:Supplier", "V00000"), SCOPE) is None
    # inactive never surfaces as a search candidate even on exact code
    result = provider.search(SearchRequest("md.supplier.search", entity_key="V90000"), SCOPE)
    assert result.candidates == ()


def test_unavailable_is_not_empty_result(pg):
    os.environ["SAP_NEXUS_MD_DSN"] = "dbname=sap_nexus_test host=127.0.0.1 port=59999 connect_timeout=1"
    try:
        with pytest.raises(ProviderError) as excinfo:
            MasterDataProvider.connect()
        assert excinfo.value.kind == "unavailable"  # case 11
    finally:
        os.environ.pop("SAP_NEXUS_MD_DSN", None)


def test_truncation_never_claims_uniqueness(provider):
    result = provider.search(SearchRequest("md.material.search", query="密封圈", limit=1), SCOPE)
    assert result.truncated and result.completeness == "partial-truncated"  # case 12
    assert len(result.candidates) == 1


def test_org_filter_visibility_semantics(provider):
    # Entities WITH extension rows are filtered by them; entities with NO
    # extension rows for the field stay visible (unimported extension is not
    # unavailability). DEMOC-style: C20010 has companyCode=2000, C10001 has
    # 1000; a material without plant rows would pass any plant filter.
    result = provider.search(
        SearchRequest("md.customer.search", query="华远", org_filters={"companyCode": "2000"}), SCOPE
    )
    codes = {c.key.canonical_code for c in result.candidates}
    assert "C20010" in codes            # matching row
    assert "C10001" not in codes        # has rows, none matches 2000
    result = provider.search(
        SearchRequest("md.customer.search", query="华远", org_filters={"companyCode": "1000"}), SCOPE
    )
    codes = {c.key.canonical_code for c in result.candidates}
    assert "C20010" not in codes and "C10001" in codes


def test_org_filter_cannot_widen_trusted_scope(provider):
    narrow = TrustedScope(
        principal="plant-user",
        source_systems=("S4H",),
        clients=("100",),
        org_scopes={"plant": ("1000",)},
    )
    with pytest.raises(ProviderError) as excinfo:
        provider.search(SearchRequest("md.material.search", query="密封圈", org_filters={"plant": "2000"}), narrow)
    assert excinfo.value.kind == "permission-denied"


def test_exact_code_match_kind(provider):
    result = provider.search(SearchRequest("md.material.search", entity_key="demoa1"), SCOPE)
    assert [c.match_kind for c in result.candidates] == ["exact-code"]
    assert result.candidates[0].key.canonical_code == "DEMOA1"  # canonical form preserved
