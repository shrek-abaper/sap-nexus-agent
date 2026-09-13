"""Replenishment proposal orchestration: READ supply -> deterministic gap ->
WRITE proposal (or no proposal when supply is sufficient)."""

from sap_nexus_agent.execution_result import ExecutionResult, ValidationResult
from sap_nexus_agent.intent import IntentParseResult
from sap_nexus_agent.match_decision import MatchedIntent
from sap_nexus_agent.orchestrator import run_query

PR_PARAMS = {
    "material": "P0254684AF",
    "plant": "5260",
    "quantity": "10",
    "unit": "EA",
    "delivery_date": "2026-09-30",
    "purchasing_group": "601",
}


def _adapter(parameters=None):
    params = parameters or PR_PARAMS

    def _adapter(_text, _context=None):
        return IntentParseResult(
            intent=None,
            parameters=dict(params),
            missing_parameters=[],
            capability_id="MM.PR.CreateDraft",
            matched_intents=[MatchedIntent("MM.PR.CreateDraft", dict(params), [])],
        )

    return _adapter


class _Gateway:
    def __init__(self, lines=None, *, inventory_fails=False, unit="EA"):
        self.lines = lines or []
        self.inventory_fails = inventory_fails
        self.unit = unit
        self.validate_calls = []
        self.execute_calls = []

    def validate(self, capability_id, parameters):
        self.validate_calls.append((capability_id, parameters))
        return ValidationResult(
            trace_id=f"tv-{len(self.validate_calls)}",
            capability_id=capability_id,
            success=True,
            error_type="NONE",
            messages=[],
        )

    def execute(self, capability_id, parameters, approval_id=None):
        self.execute_calls.append((capability_id, parameters))
        if capability_id == "MM.Inventory.GetAvailability":
            if self.inventory_fails:
                return ExecutionResult(
                    trace_id="gw-inv-fail",
                    capability_id=capability_id,
                    success=False,
                    executor={"type": "JCO_RFC", "rfcName": "BAPI_MATERIAL_STOCK_REQ_LIST"},
                    return_messages=[],
                    data={},
                    duration_ms=1,
                    error_type="SAP_BUSINESS_ERROR",
                )
            total = sum((line.get("availQty1") or 0) for line in self.lines)
            return ExecutionResult(
                trace_id="gw-inv",
                capability_id=capability_id,
                success=True,
                executor={"type": "JCO_RFC", "rfcName": "BAPI_MATERIAL_STOCK_REQ_LIST"},
                return_messages=[],
                data={
                    "availableQuantity": total,
                    "unit": self.unit,
                    "mrpElementLines": self.lines,
                },
                duration_ms=1,
                error_type="NONE",
            )
        raise AssertionError(f"unexpected WRITE execute for {capability_id}")


def _line(ind, qty, date):
    return {"mrpElementInd": ind, "availQty1": qty, "date": date}


def test_proposal_reads_supply_and_orders_only_the_gap():
    gateway = _Gateway([
        _line("WB", 2, "2026-09-13"),
        _line("BE", 3, "2026-08-12"),
    ])
    outcome = run_query("补货", gateway, intent_adapter=_adapter())

    assert outcome.status == "awaiting_approval"
    assert outcome.approval_record is not None
    assert outcome.approval_record.parameters["quantity"] == "5"
    assert [c[0] for c in gateway.execute_calls] == ["MM.Inventory.GetAvailability"]
    assert "缺口：5 EA" in (outcome.response_text or "")
    # The supply fact is attached as proposal evidence.
    assert outcome.facts and len(outcome.facts) == 1


def test_late_in_transit_is_excluded_from_supply():
    gateway = _Gateway([
        _line("WB", 2, "2026-09-13"),
        _line("BE", 3, "2026-10-15"),
    ])
    outcome = run_query("补货", gateway, intent_adapter=_adapter())

    assert outcome.approval_record.parameters["quantity"] == "8"
    assert "未计入" in (outcome.response_text or "")


def test_zero_gap_creates_no_approval_and_reports_sufficient():
    gateway = _Gateway([
        _line("WB", 1, "2026-09-13"),
        _line("BA", 3, "2026-09-30"),
        _line("BA", 13, "2026-09-30"),
    ])
    outcome = run_query("补货", gateway, intent_adapter=_adapter())

    assert outcome.status == "success"
    assert outcome.approval_record is None
    assert "无需补货" in (outcome.response_text or "")
    # Only the READ happened; no WRITE-related approval/execution.
    assert [c[0] for c in gateway.execute_calls] == ["MM.Inventory.GetAvailability"]
    assert outcome.facts and len(outcome.facts) == 1


def test_inventory_read_failure_fails_closed_without_approval():
    gateway = _Gateway(inventory_fails=True)
    outcome = run_query("补货", gateway, intent_adapter=_adapter())

    assert outcome.status == "failure"
    assert outcome.approval_record is None
    assert [c[0] for c in gateway.execute_calls] == ["MM.Inventory.GetAvailability"]


def test_unit_mismatch_fails_closed():
    gateway = _Gateway([_line("WB", 2, "2026-09-13")], unit="KG")
    outcome = run_query("补货", gateway, intent_adapter=_adapter())

    assert outcome.status == "failure"
    assert outcome.approval_record is None
    assert "单位" in (outcome.response_text or "")
