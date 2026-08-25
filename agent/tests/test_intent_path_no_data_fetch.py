"""Invariant 2's explicit checkpoint (plan task 5.8).

`capabilityOutput` as a parameter source must manifest as an upstream node plus
an edge in the PlanGraph, executed in order by the PlanExecutor. It is
forbidden for the intent layer to call the Gateway — or fire an RFC / OData —
during intent parsing just to "look the unit up first". The intent layer only
authors; it never executes.

Two independent locks:

* **Static** — no intent-path module may reach ``gateway_client`` or an HTTP
  library, transitively. Importing the module in a fresh interpreter is what
  makes this transitive: a grep sees one file, an import sees the closure.
* **Behavioural** — running recall, matching, decision and plan compilation
  against a recording Gateway double must leave both call lists empty.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_ROOT = REPO_ROOT / "agent"

#: Every module that participates in turning an utterance into a plan. Kept as
#: an explicit list rather than "everything under ``agent/``" because
#: ``orchestrator`` / ``cli`` / ``workbench_output`` are the *runtime* and are
#: supposed to reach the Gateway. Those three are asserted to be the only ones
#: that do, in ``test_only_the_runtime_entry_points_import_the_gateway_client``.
INTENT_PATH_MODULES = (
    "sap_nexus_agent.intent",
    "sap_nexus_agent.intent_envelope",
    "sap_nexus_agent.llm_intent",
    "sap_nexus_agent.recall",
    "sap_nexus_agent.rerank",
    "sap_nexus_agent.capability_selector",
    "sap_nexus_agent.match_decision",
    "sap_nexus_agent.registry_loader",
    "sap_nexus_agent.extraction",
    "sap_nexus_agent.call_plan",
    "sap_nexus_agent.governed_context",
    "sap_nexus_agent.planner.capability_card",
    "sap_nexus_agent.planner.goal_spec",
    "sap_nexus_agent.planner.handoff",
    "sap_nexus_agent.planner.plan_compiler",
    "sap_nexus_agent.planner.plan_compiler_v2",
    "sap_nexus_agent.planner.plan_draft",
    "sap_nexus_agent.semantic_planning",
    "sap_nexus_agent.semantic_planning.derivation",
    "sap_nexus_agent.semantic_planning.graph",
    "sap_nexus_agent.semantic_planning.loader",
    "sap_nexus_agent.semantic_planning.snapshot",
    "sap_nexus_agent.semantic_planning.validation",
    "sap_nexus_agent.semantic_planning.validation_v2",
)

#: Modules whose presence in ``sys.modules`` after importing an intent-path
#: module means a synchronous data fetch is reachable from intent parsing.
FORBIDDEN_MODULES = (
    "sap_nexus_agent.gateway_client",
    "requests",
    "httpx",
    "urllib.request",
    "http.client",
)

#: The only modules allowed to *import* the Gateway client: the runtime entry
#: points. ``eval.py`` is absent on purpose — it drives the runtime through its
#: own ``FakeGatewayClient`` and never imports the real one.
GATEWAY_IMPORTERS = frozenset({"cli.py", "orchestrator.py", "workbench_output.py"})


def _import_probe(module: str) -> set[str]:
    """Import ``module`` in a fresh interpreter; return the forbidden modules
    that ended up loaded."""
    program = (
        "import importlib, json, sys\n"
        f"importlib.import_module({module!r})\n"
        f"print(json.dumps([m for m in {list(FORBIDDEN_MODULES)!r} if m in sys.modules]))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=str(AGENT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, (
        f"importing {module} failed:\n{completed.stderr}"
    )
    import json

    return set(json.loads(completed.stdout.strip().splitlines()[-1]))


@pytest.mark.parametrize("module", INTENT_PATH_MODULES)
def test_intent_path_module_cannot_reach_a_data_fetch(module: str):
    """Task 5.8.1, transitively. A fresh interpreter that imports one
    intent-path module must not end up with the Gateway client or an HTTP
    library loaded."""
    reached = _import_probe(module)
    assert not reached, (
        f"{module} transitively imports {sorted(reached)}; invariant 2 forbids a "
        f"synchronous data fetch being reachable from intent parsing"
    )


def test_the_probe_itself_is_not_vacuous():
    """The probe must be able to say yes. ``orchestrator`` legitimately reaches
    the Gateway, so it is the positive control: if this goes green-empty the
    test above proves nothing."""
    reached = _import_probe("sap_nexus_agent.orchestrator")
    assert "sap_nexus_agent.gateway_client" in reached


def test_only_the_runtime_entry_points_import_the_gateway_client():
    """Task 5.8.1's file-level half, as a lock rather than a one-off grep.

    A new module importing ``gateway_client`` is a design decision, so it has to
    be made here explicitly rather than merged silently.
    """
    package = AGENT_ROOT / "sap_nexus_agent"
    importers = {
        path.name
        for path in package.rglob("*.py")
        if path.name != "gateway_client.py"
        and "gateway_client" in path.read_text(encoding="utf-8")
    }
    assert importers == GATEWAY_IMPORTERS, (
        f"unexpected gateway_client import(s): "
        f"{sorted(importers - GATEWAY_IMPORTERS)}; "
        f"no longer importing: {sorted(GATEWAY_IMPORTERS - importers)}"
    )


class _RecordingGateway:
    """Records every call instead of making one. Any recorded call is a failure."""

    def __init__(self):
        self.validate_calls: list[tuple] = []
        self.execute_calls: list[tuple] = []

    def validate(self, capability_id, parameters, **kwargs):  # pragma: no cover
        self.validate_calls.append((capability_id, dict(parameters)))
        raise AssertionError("intent parsing must not call Gateway.validate")

    def execute(self, capability_id, parameters, **kwargs):  # pragma: no cover
        self.execute_calls.append((capability_id, dict(parameters)))
        raise AssertionError("intent parsing must not call Gateway.execute")


def test_authoring_a_derived_parameter_performs_zero_gateway_calls(monkeypatch):
    """Task 5.8.2, at the point where the temptation actually lives.

    The consumer's parameter is available *only* from an upstream capability's
    output, so this is the exact case where "just look the unit up first" would
    be written. The correct answer is an upstream node plus a ``data`` edge —
    authored, not executed — so the plan must come out complete with both call
    lists empty.
    """
    import sap_nexus_agent.gateway_client as gateway_module
    from sap_nexus_agent.planner.handoff import compile_plan_v2_from_handoff

    from test_planner_plan_compiler_v2 import (
        _quantity_handoff,
        _sources_with_derivable_identifier,
    )

    exploding = lambda *a, **k: pytest.fail(  # noqa: E731
        "intent parsing must not construct a GatewayClient"
    )
    monkeypatch.setattr(gateway_module, "GatewayClient", exploding)
    gateway = _RecordingGateway()

    sources, snapshot = _sources_with_derivable_identifier()
    result = compile_plan_v2_from_handoff(
        _quantity_handoff(snapshot, {}), snapshot, sources
    )

    # The parameter really was derived -- otherwise there was nothing to fetch
    # and the assertion below would be vacuous.
    consumer = next(
        node
        for node in result.plan_graph["nodes"]
        if node["capabilityId"] == "Test.Consumer.UseQuantity"
    )
    assert [
        binding["source"]["kind"]
        for binding in consumer["parameterBindings"]
        if binding["parameterName"] == "quantity"
    ] == ["factField"]
    assert [
        edge
        for edge in result.plan_graph["edges"]
        if edge["kind"] == "data" and edge["toNodeId"] == consumer["nodeId"]
    ]

    # ...and it was derived by authoring, not by fetching.
    assert gateway.validate_calls == []
    assert gateway.execute_calls == []
