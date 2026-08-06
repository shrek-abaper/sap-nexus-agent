from __future__ import annotations

import argparse
import json
import sys

from sap_nexus_agent.approval import ApprovalRecord
from sap_nexus_agent.call_plan import CallPlan
from sap_nexus_agent.conversation_context import (
    ConversationContext,
    ReadExecutionBinding,
    SelectionExecutionBinding,
)
from sap_nexus_agent.execution_result import ValidationResult
from sap_nexus_agent.gateway_client import GatewayClient
from sap_nexus_agent.llm_intent import build_intent_adapter
from sap_nexus_agent.orchestrator import (
    continue_action,
    continue_batch,
    continue_resolved_read,
    continue_resolved_selection,
    resolve_read_turn,
    run_query,
)
from sap_nexus_agent.registry_loader import load_intent_catalog
from sap_nexus_agent.workbench_output import outcome_to_workbench_dict
from sap_nexus_agent.governed_context import load_principal_from_env
from sap_nexus_agent.visibility import filter_catalog, filter_visible
from sap_nexus_agent.planner.capability_card import discover_cards
from sap_nexus_agent.semantic_planning import build_registry_snapshot, load_semantic_sources
from pathlib import Path


def _resolve_repo_root() -> Path:
    here = Path(__file__).resolve().parents[1]
    for parent in [here, *here.parents]:
        if (parent / "registry" / "capabilities.yaml").exists():
            return parent
    return Path.cwd()


def _build_adapter_and_principal(intent_mode: str):
    """Load catalog, filter visible, build adapter.

    Returns ``(intent_adapter, principal, snapshot, sources)``. On snapshot
    load failure, falls back to unfiltered catalog (local dev tolerance).
    """
    principal = load_principal_from_env()
    catalog = load_intent_catalog()
    snapshot = None
    sources = None
    try:
        repo_root = _resolve_repo_root()
        sources = load_semantic_sources(repo_root)
        snapshot = build_registry_snapshot(sources)
        cards = discover_cards(snapshot, sources)
        visible_cards = filter_visible(cards, for_execution=False)
        catalog = filter_catalog(catalog, visible_cards)
    except Exception as exc:
        # Snapshot load failed: fall back to unfiltered catalog but let
        # run_query re-load the snapshot (fail-closed PlannerFailure on
        # persistent failure). matcher visibility filter is defense-in-depth.
        import logging

        logging.getLogger(__name__).warning(
            "snapshot load failed in cli; falling back to unfiltered catalog: %s", exc
        )
        snapshot = None
        sources = None
    intent_adapter = build_intent_adapter(intent_mode, catalog)
    return intent_adapter, principal, snapshot, sources


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
        "--continue-batch",
        action="store_true",
        help="Read a batch continuation payload (callPlan + combinations) from stdin",
    )
    parser.add_argument(
        "--context",
        action="store_true",
        help="Read a ConversationContext JSON payload from stdin for multi-turn continuation",
    )
    parser.add_argument(
        "--resolve-read-turn",
        action="store_true",
        help="Resolve a server-owned READ turn without constructing a Gateway client",
    )
    parser.add_argument(
        "--continue-read",
        action="store_true",
        help="Continue one server-owned, persisted READ resolution",
    )
    parser.add_argument(
        "--continue-selection",
        action="store_true",
        help="Continue one server-owned non-READ selection without parsing again",
    )
    parser.add_argument("--turn-id", help="Server-owned conversation turn identifier")
    args = parser.parse_args(argv)

    if args.resolve_read_turn:
        if not args.query:
            parser.error("query is required for --resolve-read-turn")
        if not args.turn_id:
            parser.error("--turn-id is required for --resolve-read-turn")
        try:
            payload = json.load(sys.stdin)
            if not isinstance(payload, dict):
                raise ValueError("context must be an object")
            context = ConversationContext.from_dict(payload)
            intent_adapter, principal, snapshot, sources = _build_adapter_and_principal(
                args.intent_mode
            )
            if snapshot is None or sources is None:
                raise ValueError("Registry snapshot is unavailable")
            outcome = resolve_read_turn(
                args.query,
                context=context,
                intent_adapter=intent_adapter,
                principal=principal,
                snapshot=snapshot,
                sources=sources,
                turn_id=args.turn_id,
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
            if args.json:
                print(json.dumps({
                    "status": "failure",
                    "errorType": "INVALID_CONTEXT_PAYLOAD",
                    "message": "Invalid authoritative READ context payload.",
                }))
            return 2
        if args.json:
            print(json.dumps(outcome_to_workbench_dict(outcome), ensure_ascii=False))
        else:
            print(outcome.response_text or outcome.message or "未生成响应。")
        return 0 if outcome.status in {
            "resolved_read", "resolved_selection", "clarification", "match_decision"
        } else 1

    if args.continue_read:
        try:
            payload = json.load(sys.stdin)
            if not isinstance(payload, dict):
                raise ValueError("continuation must be an object")
            call_plan = CallPlan.from_dict(dict(payload["callPlan"]))
            binding = ReadExecutionBinding.from_dict(dict(payload["binding"]))
            from sap_nexus_agent.read_context import ConversationReadState

            persisted_state = ConversationReadState.from_dict(
                dict(payload["persistedReadState"])
            )
            if not binding.validates(call_plan, persisted_state):
                raise ValueError("READ execution binding mismatch")
            principal = load_principal_from_env()
            repo_root = _resolve_repo_root()
            sources = load_semantic_sources(repo_root)
            snapshot = build_registry_snapshot(sources)
            if (
                binding.principal_id != principal.principal_id
                or binding.registry_snapshot_id != snapshot.snapshot_id
            ):
                raise ValueError("READ execution authority drift")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
            if args.json:
                print(json.dumps({
                    "status": "failure",
                    "errorType": "READ_EXECUTION_BINDING_MISMATCH",
                    "message": "Invalid or stale READ execution binding.",
                }))
            return 2
        gateway = GatewayClient(args.gateway_url)
        outcome = continue_resolved_read(
            call_plan,
            binding,
            gateway,
            persisted_state=persisted_state,
            principal=principal,
            snapshot=snapshot,
            sources=sources,
        )
        if args.json:
            print(json.dumps(outcome_to_workbench_dict(outcome), ensure_ascii=False))
        else:
            print(outcome.response_text or outcome.message or "未生成响应。")
        return 0 if outcome.status == "success" else 1

    if args.continue_selection:
        try:
            payload = json.load(sys.stdin)
            if not isinstance(payload, dict):
                raise ValueError("continuation must be an object")
            call_plan = CallPlan.from_dict(dict(payload["callPlan"]))
            binding = SelectionExecutionBinding.from_dict(dict(payload["binding"]))
            principal = load_principal_from_env()
            repo_root = _resolve_repo_root()
            sources = load_semantic_sources(repo_root)
            snapshot = build_registry_snapshot(sources)
            if (
                binding.principal_id != principal.principal_id
                or binding.registry_snapshot_id != snapshot.snapshot_id
            ):
                raise ValueError("selection authority drift")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
            if args.json:
                print(json.dumps({
                    "status": "failure",
                    "errorType": "SELECTION_EXECUTION_BINDING_MISMATCH",
                    "message": "Invalid or stale selection binding.",
                }))
            return 2
        gateway = GatewayClient(args.gateway_url)
        outcome = continue_resolved_selection(
            call_plan,
            binding,
            gateway,
            principal=principal,
            snapshot=snapshot,
            sources=sources,
        )
        if args.json:
            print(json.dumps(outcome_to_workbench_dict(outcome), ensure_ascii=False))
        else:
            print(outcome.response_text or outcome.message or "未生成响应。")
        return 0 if outcome.status == "awaiting_approval" else 1

    if args.continue_action:
        gateway = GatewayClient(args.gateway_url)
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

    if args.continue_batch:
        gateway = GatewayClient(args.gateway_url)
        try:
            payload = json.load(sys.stdin)
            outcome = continue_batch(
                CallPlan.from_dict(dict(payload["callPlan"])),
                [dict(c) for c in payload["combinations"]],
                gateway,
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            if args.json:
                print(json.dumps({
                    "status": "failure",
                    "errorType": "INVALID_BATCH_PAYLOAD",
                    "message": "Invalid batch continuation payload.",
                }))
            return 2
        if args.json:
            print(json.dumps(outcome_to_workbench_dict(outcome), ensure_ascii=False))
        else:
            print(outcome.response_text or outcome.message or "未生成响应。")
        return 0 if outcome.status == "success" else 1

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
        gateway = GatewayClient(args.gateway_url)
        intent_adapter, principal, snapshot, sources = _build_adapter_and_principal(args.intent_mode)
        outcome = run_query(
            args.query,
            gateway,
            intent_adapter=intent_adapter,
            context=context,
            principal=principal,
            snapshot=snapshot,
            sources=sources,
        )
        if args.json:
            print(json.dumps(outcome_to_workbench_dict(outcome), ensure_ascii=False))
        else:
            print(outcome.response_text or outcome.message or "未生成响应。")
        return 0 if outcome.status in {"success", "clarification", "awaiting_approval"} else 1

    if not args.query:
        parser.error("query is required unless --continue-action is used")

    intent_adapter, principal, snapshot, sources = _build_adapter_and_principal(args.intent_mode)
    gateway = GatewayClient(args.gateway_url)
    outcome = run_query(
        args.query,
        gateway,
        intent_adapter=intent_adapter,
        principal=principal,
        snapshot=snapshot,
        sources=sources,
    )
    if args.json:
        print(json.dumps(outcome_to_workbench_dict(outcome), ensure_ascii=False))
    else:
        print(outcome.response_text or outcome.message or "未生成响应。")
    return 0 if outcome.status in {"success", "clarification", "awaiting_approval"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
