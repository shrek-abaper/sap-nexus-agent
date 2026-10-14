#!/usr/bin/env python3
"""Paid live evaluation for ModelGoalInterpreter (manual, never in CI).

Runs Q1-Q7-style free-form utterances against the configured OpenAI-
compatible model through the SAME shared draft pipeline + coordinator as
production, then prints pass/gap/calls table. Costs real model tokens;
requires SAP_NEXUS_LLM_LIVE=1 and LLM_* settings.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "agent"))

# (label, fixture case id, utterance, slots)
CASES = [
    ("q1-stock-unit", "q1-stock-and-unit", "查一下物料 DEMOA2 在工厂 1000 的当前库存，还有它的基本计量单位", {"material": "DEMOA2", "plant": "1000"}),
    ("q2-po-grouped", "q2-po-group-by-supplier", "DEMOA2 在 1000 工厂的采购订单量，按供应商和单位分别汇总，和库存并排看", {"material": "DEMOA2", "plant": "1000"}),
    ("q3-vendor-filter", "q3-supplier-filter", "只看供应商 V72719 给 DEMOA2 在 1000 工厂的订单量", {"material": "DEMOA2", "plant": "1000", "vendor": "V72719"}),
    ("q4-side-by-side", "q4-inventory-and-orders-side-by-side", "把 DEMOA2 在 1000 的库存和采购订单明细并排展示，不用比较数值", {"material": "DEMOA2", "plant": "1000"}),
    ("q5-arrivals", "q1-stock-and-unit", "DEMOA2 下周能到多少货？预计哪些采购订单会收货？", {"material": "DEMOA2", "plant": "1000"}),
    ("q6-stockout", "q1-stock-and-unit", "下周会不会断供？能确定吗？", {"material": "DEMOA2", "plant": "1000"}),
    ("q7-write", "q1-stock-and-unit", "帮我直接给 DEMOA2 在 1000 工厂创建一张采购申请", {"material": "DEMOA2", "plant": "1000"}),
    ("ambiguous-material", "q1-stock-and-unit", "查库存", {}),
]


def main() -> int:
    if os.environ.get("SAP_NEXUS_LLM_LIVE") != "1":
        print("SAP_NEXUS_LLM_LIVE must equal 1 for paid evaluation", file=sys.stderr)
        return 2

    from sap_nexus_agent.ontology_planning.coordinator import run_analysis_request
    from sap_nexus_agent.ontology_planning.model_interpreter import ModelGoalInterpreter
    from sap_nexus_agent.ontology_planning.release import pin_release
    from sap_nexus_agent.semantic_planning.loader import load_semantic_sources
    from sap_nexus_agent.semantic_planning.validation import build_semantic_contracts

    fixtures = REPO_ROOT / "evals/ontology-read-analysis"
    rows = []
    for label, fixture_case, utterance, slots in CASES:
        # Count model calls by injecting one shared client-backed interpreter.
        pinned = pin_release(REPO_ROOT)
        interpreter = ModelGoalInterpreter(pinned)
        request = {
            "schemaVersion": 1,
            "caseId": fixture_case,
            "interpreter": "model",
            "utterance": utterance,
            "slots": slots,
            "scope": {"plant": slots.get("plant")} if slots.get("plant") else {},
        }
        sources = load_semantic_sources(REPO_ROOT)
        contracts = build_semantic_contracts(sources)
        from sap_nexus_agent.ontology_planning.draft_pipeline import prepare_draft

        draft, terminal = prepare_draft(
            request, sources, pinned, fixtures,
            interpreter_instance=interpreter, live=True,
        )
        if terminal is not None:
            rows.append({
                "case": label,
                "status": terminal["status"],
                "calls": interpreter.call_count,
                "reasons": terminal.get("reasons", []),
            })
        else:
            # Fixture selection: PO facts need a gateway dir containing the PO
            # capability; inventory/material-only questions use the q1 dir.
            fact_types = {f.get("factTypeId") for f in draft.get("requestedFacts", [])}
            if "sapnexus:PurchaseOrderSupplyFact" in fact_types:
                request["caseId"] = "q2-po-group-by-supplier"
            # Reuse the validated model draft end-to-end via coordinator override.
            full = {**request, "draftOverride": draft}
            response = run_analysis_request(full, REPO_ROOT, fixtures)
            # Safety: model path never triggers a WRITE call.
            assert response["writeGatewayCalls"] == 0
            rows.append({
                "case": label,
                "status": response["status"],
                "calls": interpreter.call_count,
                "writeCalls": response["writeGatewayCalls"],
            })

    print(json.dumps(rows, ensure_ascii=False, indent=2))
    accepted = sum(1 for r in rows if r["status"] in {"complete", "partial", "clarification", "semantic_gap", "capability_gap", "rejected"})
    print(f"\n{accepted}/{len(rows)} terminal outcomes; paid calls total: "
          f"{sum(r['calls'] for r in rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
