"""CLI behavior for scripts/build-semantic-release.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/build-semantic-release.py"
ARTIFACT = REPO_ROOT / "ontology/generated/semantic-release.json"

ENV = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "agent")}


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        env=ENV,
        capture_output=True,
        text=True,
    )


def test_build_emits_byte_deterministic_artifact():
    result = _run()
    assert result.returncode == 0, result.stderr
    first = ARTIFACT.read_bytes()
    assert json.loads(first)["schemaVersion"] == 1
    result = _run()
    assert result.returncode == 0, result.stderr
    assert ARTIFACT.read_bytes() == first


def test_check_succeeds_when_in_sync():
    build = _run()
    assert build.returncode == 0, build.stderr
    before = ARTIFACT.stat()
    result = _run("--check")
    after = ARTIFACT.stat()
    assert result.returncode == 0, result.stderr
    assert "in sync" in result.stdout
    assert before.st_size == after.st_size
    assert before.st_mtime_ns == after.st_mtime_ns


def test_check_detects_stale_artifact():
    build = _run()
    assert build.returncode == 0, build.stderr
    original = ARTIFACT.read_bytes()
    try:
        ARTIFACT.write_text(original.decode() + " ", encoding="utf-8")
        result = _run("--check")
        assert result.returncode == 1
        assert "OUT_OF_SYNC" in result.stderr
    finally:
        ARTIFACT.write_bytes(original)


def test_usage_error_exit_code():
    result = _run("--bogus")
    assert result.returncode == 2
