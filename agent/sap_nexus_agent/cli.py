from __future__ import annotations

import argparse
import json
import sys

from sap_nexus_agent.approval import ApprovalRecord
from sap_nexus_agent.call_plan import CallPlan
from sap_nexus_agent.conversation_context import ConversationContext
from sap_nexus_agent.execution_result import ValidationResult
from sap_nexus_agent.gateway_client import GatewayClient
from sap_nexus_agent.llm_intent import build_intent_adapter
from sap_nexus_agent.orchestrator import continue_action, run_query
from sap_nexus_agent.registry_loader import load_intent_catalog
from sap_nexus_agent.workbench_output import outcome_to_workbench_dict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SAP Nexus Agent query and approval continuation")
    parser.add_argument("query", nargs="?", help="Chinese SAP query")
    parser.add_argument("--gateway-url", default="http://localhost:8080")
    parser.add_argument("--intent-mode", choices=("hybrid", "llm", "rule"), default="hybrid")
    parser.add_argument("--json", action="store_true", help="Print structured JSON for Workbench runtime adapter")
    parser.add_argument(
        "--continue-action",
        action="store_true",
        help="Read a server-owned approval continuation payload from stdin",
    )
    parser.add_argument(
        "--context",
        action="store_true",
        help="Read a ConversationContext JSON payload from stdin for multi-turn continuation",
    )
    args = parser.parse_args(argv)

    gateway = GatewayClient(args.gateway_url)
    if args.continue_action:
        try:
            payload = json.load(sys.stdin)
            outcome = continue_action(
                CallPlan.from_dict(dict(payload["callPlan"])),
                ValidationResult.from_dict(dict(payload["validationResult"])),
                ApprovalRecord.from_dict(dict(payload["approvalRecord"])),
                gateway,
                decision=str(payload["decision"]),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            if args.json:
                print(json.dumps({
                    "status": "failure",
                    "errorType": "INVALID_APPROVAL_PAYLOAD",
                    "message": "Invalid approval continuation payload.",
                }))
            return 2
        if args.json:
            print(json.dumps(outcome_to_workbench_dict(outcome), ensure_ascii=False))
        else:
            print(outcome.response_text or outcome.message or "未生成响应。")
        return 0 if outcome.status in {"success", "rejected"} else 1

    if args.context:
        if not args.query:
            parser.error("query is required unless --continue-action is used")
        try:
            payload = json.load(sys.stdin)
            context = ConversationContext.from_dict(payload)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
            if args.json:
                print(json.dumps({
                    "status": "failure",
                    "errorType": "INVALID_CONTEXT_PAYLOAD",
                    "message": "Invalid conversation context payload.",
                }))
            return 2
        catalog = load_intent_catalog()
        intent_adapter = build_intent_adapter(args.intent_mode, catalog)
        outcome = run_query(
            args.query,
            gateway,
            intent_adapter=intent_adapter,
            context=context,
        )
        if args.json:
            print(json.dumps(outcome_to_workbench_dict(outcome), ensure_ascii=False))
        else:
            print(outcome.response_text or outcome.message or "未生成响应。")
        return 0 if outcome.status in {"success", "clarification", "awaiting_approval"} else 1

    if not args.query:
        parser.error("query is required unless --continue-action is used")

    catalog = load_intent_catalog()
    intent_adapter = build_intent_adapter(args.intent_mode, catalog)
    outcome = run_query(
        args.query,
        gateway,
        intent_adapter=intent_adapter,
    )
    if args.json:
        print(json.dumps(outcome_to_workbench_dict(outcome), ensure_ascii=False))
    else:
        print(outcome.response_text or outcome.message or "未生成响应。")
    return 0 if outcome.status in {"success", "clarification", "awaiting_approval"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
