"""PlanGraph v2 deterministic compiler (semantic-plan-authoring-v2).

Compiles EscalationHandoff + RegistrySnapshot + SemanticSourceDocuments
into a PlanCompileResult carrying a validated PlanGraph v2 with full
parameter provenance (4-source closed set), data/dependency edges, and
READ/WRITE partitions. Deterministic: no LLM, no Gateway/SAP.

Design Doc: docs/superpowers/specs/2026-08-03-sap-nexus-semantic-plan-authoring-v2-design.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sap_nexus_agent.planner.plan_compiler import Gap, Flag

# v2 新增源种类（schema 闭集第 4 种；compiler 本期不产出）。
_SOURCE_KIND_REGISTERED_DEFAULT = "registeredDefault"

# 分区标签（内部使用，不写入 plan_graph）。
_PARTITION_READ = "readPartition"
_PARTITION_ACTION = "actionPartition"


@dataclass(frozen=True)
class PlanCompileResult:
    """v2 dry-run 输出。

    ``plan_graph`` 是 PlanGraph v2 dict（camelCase JSON 形状），校验失败
    时仍返回部分图（不返回 None）。``projection_ref`` / ``rule_set_refs``
    本期空（reserved）。``snapshot_id`` 与 handoff/lease 绑定一致。
    """

    plan_graph: dict[str, Any]
    gaps: list[Gap]
    governance_flags: list[Flag]
    projection_ref: list
    rule_set_refs: list
    snapshot_id: str
    rationale: str
