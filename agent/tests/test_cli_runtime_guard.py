"""Tests for the CLI last-resort runtime guard.

The Workbench runner spawns ``python -m sap_nexus_agent.cli --json`` and parses
stdout. Any unexpected failure must be emitted as structured JSON, never a raw
traceback - otherwise the frontend reports "did not produce valid Workbench JSON".
"""

from __future__ import annotations

import json

from sap_nexus_agent import cli


def test_json_mode_serializes_unexpected_error(monkeypatch, capsys):
    def boom(_argv):
        raise ConnectionRefusedError("gateway down")

    monkeypatch.setattr(cli, "_main_impl", boom)

    rc = cli.main(["--continue-read", "--json"])
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)

    assert rc == 1
    assert payload["status"] == "failure"
    assert payload["errorType"] == "AGENT_RUNTIME_ERROR"
    assert "gateway down" in payload["message"]


def test_json_flag_detected_among_other_args(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "_main_impl", lambda _argv: (_ for _ in ()).throw(OSError("x"))
    )

    rc = cli.main(
        ["--continue-read", "--gateway-url", "http://x", "--json"]
    )
    payload = json.loads(capsys.readouterr().out.strip())

    assert rc == 1
    assert payload["errorType"] == "AGENT_RUNTIME_ERROR"


def test_non_json_mode_reraises(monkeypatch):
    def boom(_argv):
        raise ConnectionRefusedError("nope")

    monkeypatch.setattr(cli, "_main_impl", boom)

    try:
        cli.main(["--continue-read"])
    except ConnectionRefusedError:
        pass
    else:  # pragma: no cover
        raise AssertionError("non-JSON mode must preserve the traceback")


def test_success_passes_through(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_main_impl", lambda _argv: 0)

    assert cli.main(["--json"]) == 0
    assert capsys.readouterr().out == ""
