"""Paired evaluation gate core (EvoOntology-inspired gated versioning).

Runs the identical offline eval suites against a Parent and a Candidate
registry, aggregates the §10.1 SLI counts, and fails on any negative SLI
delta. Only ``registry/*.yaml`` is version-varied; code and suites are shared.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any

from sap_nexus_agent.eval import SLI_NAMES

REGISTRY_FILES = (
    "registry/capabilities.yaml",
    "registry/semantic-types.yaml",
    "registry/executor-bindings.yaml",
)

DEFAULT_SUITES = (
    "evals/inventory_availability_cases.yaml",
    "evals/eval_harness_seed_cases.json",
    "evals/pr_create_cases.json",
    "evals/matcher_cases.yaml",
    "evals/dry_run_cases.yaml",
    "evals/derived_parameter_cases.yaml",
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return _sha256(path.read_bytes())


def git_commit(repo_root: Path, ref: str) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", ref],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def materialize_registry(ref: str, repo_root: Path, dest_root: Path) -> dict[str, str]:
    """Extract ``registry/*.yaml`` at ``ref`` into ``dest_root``; per-file sha256."""
    files: dict[str, str] = {}
    for rel in REGISTRY_FILES:
        proc = subprocess.run(
            ["git", "show", f"{ref}:{rel}"],
            cwd=repo_root,
            capture_output=True,
        )
        if proc.returncode != 0:
            # File did not exist at that ref; absence is a valid state.
            continue
        target = dest_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(proc.stdout)
        files[rel] = _sha256(proc.stdout)
    return files


def worktree_registry_files(repo_root: Path) -> dict[str, str]:
    return {
        rel: sha256_file(repo_root / rel)
        for rel in REGISTRY_FILES
        if (repo_root / rel).exists()
    }


def run_suite_metrics(repo_root: Path, suite_rel: str, agent_root: str | None) -> dict[str, Any]:
    env = dict(os.environ)
    if agent_root:
        env["SAP_NEXUS_AGENT_ROOT"] = agent_root
    else:
        env.pop("SAP_NEXUS_AGENT_ROOT", None)
    proc = subprocess.run(
        [sys.executable, "-m", "sap_nexus_agent.eval", suite_rel, "--metrics"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"metrics run failed for {suite_rel}:\n{proc.stderr or proc.stdout}"
        )
    return json.loads(proc.stdout)


def aggregate(metrics_payloads: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {
        name: {"passed": 0, "total": 0} for name in SLI_NAMES
    }
    for payload in metrics_payloads:
        for sli, observed in payload["sli"].items():
            entry = counts.setdefault(sli, {"passed": 0, "total": 0})
            entry["passed"] += observed["passed"]
            entry["total"] += observed["total"]
    return counts


def _rate(counts: dict[str, int]) -> float:
    return counts["passed"] / counts["total"] if counts["total"] else 0.0


def compare_sli(
    parent: dict[str, dict[str, int]],
    candidate: dict[str, dict[str, int]],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    result: dict[str, dict[str, Any]] = {}
    regressed: list[str] = []
    for name in SLI_NAMES:
        p = parent.get(name, {"passed": 0, "total": 0})
        c = candidate.get(name, {"passed": 0, "total": 0})
        entry: dict[str, Any] = {
            "parent": {"passed": p["passed"], "total": p["total"], "rate": _rate(p)},
            "candidate": {"passed": c["passed"], "total": c["total"], "rate": _rate(c)},
        }
        if p["total"] == 0 or c["total"] == 0:
            entry["delta"] = None
            entry["regressed"] = False
            entry["reason"] = "zero denominator"
        elif p["total"] != c["total"]:
            entry["delta"] = entry["candidate"]["rate"] - entry["parent"]["rate"]
            entry["regressed"] = True
            entry["reason"] = "denominator mismatch"
            regressed.append(name)
        else:
            delta = entry["candidate"]["rate"] - entry["parent"]["rate"]
            entry["delta"] = delta
            entry["regressed"] = delta < 0
            entry["reason"] = None
            if delta < 0:
                regressed.append(name)
        result[name] = entry
    return result, regressed


def suite_set_hash(repo_root: Path, suites: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for rel in suites:
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update((repo_root / rel).read_bytes())
    return digest.hexdigest()


def run_paired(
    *,
    repo_root: Path,
    parent_ref: str = "HEAD",
    candidate_ref: str | None = None,
    suites: tuple[str, ...] = DEFAULT_SUITES,
    output_dir: Path | None = None,
) -> tuple[dict[str, Any], Path]:
    repo_root = Path(repo_root)
    parent_root = Path(tempfile.mkdtemp(prefix="paired-eval-parent-"))
    parent_commit = git_commit(repo_root, parent_ref)
    parent_files = materialize_registry(parent_ref, repo_root, parent_root)
    candidate_root: Path | None = None
    try:
        if candidate_ref:
            candidate_root = Path(tempfile.mkdtemp(prefix="paired-eval-candidate-"))
            candidate_commit = git_commit(repo_root, candidate_ref)
            candidate_files = materialize_registry(candidate_ref, repo_root, candidate_root)
            candidate_label = candidate_ref
        else:
            candidate_commit = git_commit(repo_root, "HEAD")
            candidate_files = worktree_registry_files(repo_root)
            candidate_label = "worktree"

        started_at = datetime.now(timezone.utc).isoformat()
        parent_metrics = [
            run_suite_metrics(repo_root, rel, str(parent_root)) for rel in suites
        ]
        candidate_metrics = [
            run_suite_metrics(
                repo_root, rel, str(candidate_root) if candidate_root else None
            )
            for rel in suites
        ]
        completed_at = datetime.now(timezone.utc).isoformat()
    finally:
        if candidate_root is not None:
            shutil.rmtree(candidate_root, ignore_errors=True)

    parent_counts = aggregate(parent_metrics)
    candidate_counts = aggregate(candidate_metrics)
    sli, regressed = compare_sli(parent_counts, candidate_counts)
    report: dict[str, Any] = {
        "schema": "sap-nexus.paired-eval-report.v1",
        "startedAt": started_at,
        "completedAt": completed_at,
        "suites": [Path(rel).stem for rel in suites],
        "suiteSetHash": suite_set_hash(repo_root, suites),
        "parent": {"ref": parent_ref, "commit": parent_commit, "files": parent_files},
        "candidate": {
            "ref": candidate_label,
            "commit": candidate_commit,
            "files": candidate_files,
        },
        "sli": sli,
        "decision": "FAIL" if regressed else "PASS",
        "regressedSlis": regressed,
    }

    output_dir = Path(output_dir) if output_dir else repo_root / "runtime/evals/results"
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_started = started_at.replace(":", "-")
    report_path = output_dir / f"paired-eval-{safe_started}.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report, report_path
