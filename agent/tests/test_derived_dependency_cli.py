"""The derived data dependency view's CLI and `runtime/` artifact (T2 task 3.5).

Invariant 3's reading instrument, so the tests here are about two things and
nothing else: that the artifact carries **full provenance** (a reader must be
able to recompute every edge from it), and that an **empty** view is reported as
empty rather than as an error.

The CLI is loaded both ways on purpose. `_load_cli_module` gives the unit tests
a handle to monkeypatch the loader, while the subprocess test proves the real
command works from a clean interpreter — a module-level `sys.path` mistake is
invisible to the first and fatal to the second.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import subprocess
import sys
import uuid
from pathlib import Path

from positive_control import positive_control_documents
from sap_nexus_agent.semantic_planning.derivation import (
    DerivationDiagnostic,
    DerivedDataEdge,
)
from sap_nexus_agent.semantic_planning.loader import (
    SourceLoadError,
    load_semantic_sources,
)
from sap_nexus_agent.semantic_planning.snapshot import build_registry_snapshot

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = REPO_ROOT / "scripts" / "derive-data-dependencies.py"
GOVERNED_DIRECTORIES = ("registry", "ontology")


def _load_cli_module():
    module_name = f"_derive_cli_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, CLI_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    original_sys_path = sys.path[:]
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = original_sys_path
    return module


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


def _governed_file_digest() -> dict[str, str]:
    digests: dict[str, str] = {}
    for directory in GOVERNED_DIRECTORIES:
        for path in sorted((REPO_ROOT / directory).rglob("*")):
            if path.is_file():
                digests[str(path.relative_to(REPO_ROOT))] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
    assert digests, "found no governed files — the comparison would be vacuous"
    return digests


# ---- 3.5.3: the empty view is a success ----


def test_the_cli_reports_the_empty_view_as_empty_and_exits_zero(tmp_path):
    """Emptiness is a legitimate state, not a failure.

    No shipped input declares `satisfiableByFactType` yet, so today's real
    answer is zero edges. Task 3.7 records that result, and it can only be
    recorded if the command that produces it succeeds.
    """
    output = tmp_path / "view.json"
    completed = subprocess.run(
        [sys.executable, str(CLI_PATH), str(output)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert "derived 0 edge(s), 0 relation(s), 0 diagnostic(s)" in completed.stdout
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["edges"] == []
    assert artifact["diagnostics"] == []
    assert artifact["relations"] == []


def test_the_artifact_binds_the_view_to_the_snapshot_it_came_from(tmp_path):
    """A derived view is only meaningful against one registry state, and the
    upstream nodes it enables are inputs to defect D4's approval subject. An
    artifact that cannot name its snapshot could not serve as that evidence."""
    output = tmp_path / "view.json"
    assert _load_cli_module().main([str(output)]) == 0
    artifact = json.loads(output.read_text(encoding="utf-8"))
    expected = build_registry_snapshot(load_semantic_sources(REPO_ROOT)).snapshot_id
    assert artifact["snapshotId"] == expected
    assert artifact["artifact"] == "derived-data-dependencies"
    assert artifact["version"] == 1


# ---- 3.5.1: full provenance per edge and per diagnostic ----


def test_the_artifact_carries_every_provenance_field_of_an_edge(tmp_path, monkeypatch):
    """Locked as field-set equality against the dataclass.

    A new provenance field on `DerivedDataEdge` that the artifact silently
    dropped would make the view unrecomputable by a reader — which is the whole
    claim invariant 3 rests on. So this fails when the two drift apart, rather
    than checking a hand-listed set that would go stale with them.
    """
    cli = _load_cli_module()
    monkeypatch.setattr(
        cli, "load_semantic_sources", lambda _root: positive_control_documents()
    )
    output = tmp_path / "view.json"
    assert cli.main([str(output)]) == 0
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["edges"], "positive control derived nothing — key set is vacuous"
    expected = {
        _camel(field.name) for field in dataclasses.fields(DerivedDataEdge)
    } | {"relationId"}
    assert set(artifact["edges"][0]) == expected


def test_the_artifact_carries_every_field_of_a_diagnostic(tmp_path, monkeypatch):
    """The same lock on the diagnostic side. `candidates` is the field that
    matters most: a diagnostic that reported the tie without naming the tied
    sources would leave the registry author nothing to act on."""
    cli = _load_cli_module()
    monkeypatch.setattr(
        cli, "load_semantic_sources", lambda _root: positive_control_documents()
    )
    output = tmp_path / "view.json"
    assert cli.main([str(output)]) == 0
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["diagnostics"], "positive control reported none — key set vacuous"
    assert set(artifact["diagnostics"][0]) == {
        _camel(field.name) for field in dataclasses.fields(DerivationDiagnostic)
    }
    assert artifact["diagnostics"][0]["candidates"]


def test_the_printed_summary_names_the_candidates_of_every_diagnostic(monkeypatch):
    """Printed in full rather than counted. A count tells a reader that a
    decision is pending; only the candidates tell them what to decide."""
    cli = _load_cli_module()
    monkeypatch.setattr(
        cli, "load_semantic_sources", lambda _root: positive_control_documents()
    )
    artifact = cli.build_artifact(REPO_ROOT)
    summary = cli.format_summary(artifact)
    for diagnostic in artifact["diagnostics"]:
        assert diagnostic["kind"] in summary
        assert diagnostic["consumerInputName"] in summary
        for candidate in diagnostic["candidates"]:
            assert candidate in summary
    for edge in artifact["edges"]:
        assert edge["producerCapabilityId"] in summary
        assert edge["factFieldName"] in summary


def test_the_rendered_relations_are_in_the_artifact_beside_the_edges(monkeypatch):
    """Both, not one. The edges are the provenance a reader recomputes from; the
    relations are the shape `plan_compiler_v2` consumes. Dropping either would
    make the artifact unusable for one of its two readers."""
    cli = _load_cli_module()
    monkeypatch.setattr(
        cli, "load_semantic_sources", lambda _root: positive_control_documents()
    )
    artifact = cli.build_artifact(REPO_ROOT)
    assert artifact["relations"]
    assert {relation["origin"] for relation in artifact["relations"]} == {"derived"}
    assert {relation["relationId"] for relation in artifact["relations"]} <= {
        edge["relationId"] for edge in artifact["edges"]
    }


# ---- the artifact is a report, never a registry write ----


def test_the_cli_writes_under_runtime_and_never_into_registry_or_ontology(tmp_path):
    """Invariant 3, checked by content rather than by intent.

    The registry is the execution boundary. A derived view written back into it
    would turn a report into authored governance — exactly the "make the file
    look non-empty" move the invariant forbids. Compared as file digests so a
    write that preserved mtime would still be caught.
    """
    cli = _load_cli_module()
    assert cli.DEFAULT_OUTPUT.parts[0] == "runtime"
    before = _governed_file_digest()
    assert cli.main([str(tmp_path / "view.json")]) == 0
    assert _governed_file_digest() == before


def test_the_default_output_path_is_gitignored():
    """The artifact is regenerated, not reviewed. Committing it would invite a
    diff review of a *derived* file, which is how a stale derived view becomes
    a claim someone trusts."""
    completed = subprocess.run(
        ["git", "check-ignore", str(_load_cli_module().DEFAULT_OUTPUT)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, (
        f"{_load_cli_module().DEFAULT_OUTPUT} is not gitignored: {completed.stdout}"
    )


# ---- failure modes follow the established script pattern ----


def test_too_many_arguments_is_a_usage_error(capsys):
    assert _load_cli_module().main(["a", "b"]) == 2
    assert "Usage: derive-data-dependencies.py" in capsys.readouterr().err


def test_a_source_load_error_exits_one_with_the_reason_on_stderr(
    monkeypatch, capsys, tmp_path
):
    """Exit 1 and a named path, matching
    `scripts/validate-semantic-planning-contract.py`. A load failure must not be
    reported as an empty view — "nothing derived" and "nothing read" are
    different facts."""
    cli = _load_cli_module()

    def _raise(_root):
        raise SourceLoadError(path="ontology/fact-types.yaml", message="boom")

    monkeypatch.setattr(cli, "load_semantic_sources", _raise)
    output = tmp_path / "view.json"
    assert cli.main([str(output)]) == 1
    assert "SCHEMA_INVALID ontology/fact-types.yaml: boom" in capsys.readouterr().err
    assert not output.exists(), "wrote an artifact for a view it could not read"


def test_the_artifact_is_byte_identical_across_runs(tmp_path):
    """The artifact is a diffable record. Nondeterministic key or list order
    would make every regeneration look like a change."""
    cli = _load_cli_module()
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    assert cli.main([str(first)]) == 0
    assert cli.main([str(second)]) == 0
    assert first.read_bytes() == second.read_bytes()
