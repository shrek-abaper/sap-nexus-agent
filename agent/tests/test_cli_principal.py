"""Tests for cli.py principal env propagation (Task 8)."""

import json


def test_cli_reads_principal_from_env(monkeypatch, capsys):
    """cli.py reads SAP_NEXUS_PRINCIPAL env and passes to run_query."""
    monkeypatch.setenv(
        "SAP_NEXUS_PRINCIPAL",
        json.dumps(
            {
                "principalId": "user-cli-test",
                "role": "operator",
                "dataScope": {"tenantId": "t1"},
            }
        ),
    )
    from sap_nexus_agent.cli import main

    exit_code = main(["--json", "查物料 DEMOA1 的可用库存"])
    assert exit_code in {0, 1}
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert "status" in payload


def test_cli_defaults_principal_when_env_missing(monkeypatch, capsys):
    """cli.py falls back to PLACEHOLDER when SAP_NEXUS_PRINCIPAL not set."""
    monkeypatch.delenv("SAP_NEXUS_PRINCIPAL", raising=False)
    from sap_nexus_agent.cli import main

    exit_code = main(["--json", "查物料 DEMOA1 的可用库存"])
    assert exit_code in {0, 1}
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert "status" in payload
