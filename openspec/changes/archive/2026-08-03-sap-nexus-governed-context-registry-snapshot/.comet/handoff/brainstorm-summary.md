# Brainstorm Summary

- Change: sap-nexus-governed-context-registry-snapshot
- Date: 2026-08-03

## 确认的技术方案

**核心数据流**：cli.py 读 `SAP_NEXUS_PRINCIPAL` env（缺省 PLACEHOLDER）-> `load_intent_catalog` -> `filter_visible`（governance 维度）-> `build_intent_adapter(filtered_catalog)` -> `run_query(text, gateway, intent_adapter, principal=...)` -> 入口 `build_registry_snapshot` + `SnapshotLease` + `GovernedContext` -> `VisibleCapabilitySet` -> intent/matcher/planner 全部消费同一 `lease.snapshotId` -> ESCALATE 时 `_compile_dry_run_safely` 消费 lease（不另行加载），漂移/失败返 `PlannerFailure`。

**7 个决策**：
- D1 GovernedContext 在 `run_query` 入口构造（principal env 透传 + snapshot 复用 S1）
- D2 principal 载体 = 环境变量 `SAP_NEXUS_PRINCIPAL`（JSON），Node spawn 设 env，Python cli 读 os.environ
- D3 SnapshotLease 持有 + 漂移 fail-closed；planner 消费 lease.snapshotId，不另行加载
- D4 `PlannerFailure(error_type, message, snapshot_id, audit_evidence)`，error_type ∈ {SNAPSHOT_MISSING, SNAPSHOT_DRIFT, PRINCIPAL_MISMATCH, SOURCE_LOAD_ERROR, VISIBILITY_DENIED}
- D5 visibility pre-filter 在 matcher 之前、catalog 加载点（cli.py）+ matcher 层双保险
- D6 capability kind 从 snapshot 投影（`governance.requires_approval`），替代 `ACTION_CAPABILITY_IDS`
- D7 `ApprovalRecord` 加 optional `registry_snapshot_id`（Node/Java 漂移执行校验留 RB21）

**7 个 Open Questions 全部确认**：
- Q1 visibility 数据源 = governance + principal 绑定（不扩 Registry schema，不引入 visibilityScope）
- Q2 principal 载体 = 环境变量注入
- Q3 缺省 principal = PLACEHOLDER_PRINCIPAL
- Q4 IntentAdapter 签名不扩展（catalog 加载点过滤 + matcher 双保险）
- Q5 CallPlan 不加 snapshotId（不触及 agent-callplan-evidence spec）
- Q6 SnapshotLease 生命周期 = run_query 入口加载，planner 入口校验 handoff.snapshotId == lease.snapshotId
- Q7 PlannerFailure audit_evidence = {expected_snapshot_id, actual_snapshot_id, principal_id, source_paths, stage}

## 关键取舍与风险

- **visibility 当前无 role 映射**：本轮 governance 维度，role-based 留后续（Registry 加 visibilityScope）；契约机制就位，未来加 HIDDEN/visibilityScope 即生效。
- **principal env 注入**：principalId/role 非高敏，env 泄露风险可控；与 `SAP_NEXUS_APPROVAL_TTL_SECONDS` 模式一致。
- **catalog 加载点过滤改变 cli.py**：双保险（catalog 加载点 + matcher 层）；本地 dev（PLACEHOLDER）行为不变。
- **ApprovalRecord 字段扩散 Node**：optional + `.get` 默认空，向后兼容；执行校验留 RB21。
- **snapshot 加载性能**：单次 run 加载一次，SnapshotLease 持有避免重复。

## 测试策略

- visibility leakage = 0：注入 HIDDEN capability fixture，断言不进入 VisibleCapabilitySet / LLM prompt / matcher 决策。
- cross-principal 决策层：注入多 principal env，断言 GovernedContext 绑定正确 principalId；durable 层 cross-principal 隔离回归（P0B）。
- snapshot 漂移：注入不一致 snapshotId，断言 PlannerFailure(SNAPSHOT_DRIFT) + audit_evidence。
- source load 失败：损坏 YAML fixture，断言 PlannerFailure(SOURCE_LOAD_ERROR)。
- capability kind 投影：断言 Action 判定来自 governance.requires_approval（移除 ACTION_CAPABILITY_IDS 后 inventory/PO/PR 路径回归）。
- matcher Eval 6/6 回归 + CapabilityCard 安全投影 negative test。

## Spec Patch

回写 delta spec（仅补充验收场景/修正歧义，不大幅重写）：

1. `governed-context-registry-snapshot` spec "Visibility pre-filter before LLM prompt"：`consider both principal visibility (role/data-scope) and governance` -> `consider governance (sideEffect/dataClassification) and bind principal to GovernedContext for same-snapshot/audit provenance; role-based capability visibility deferred until Registry carries visibilityScope`。
2. `governed-context-registry-snapshot` spec "cross-principal 决策层 fail-closed" scenario：调整为 `principal 绑定到 GovernedContext 用于审计与同快照证明；cross-principal 隔离在 durable 层 fail-closed（P0B）；决策层 visibility 基于 governance 维度`。
3. `semantic-match-decision` spec "Visibility pre-filter" MODIFIED 同步调整 principal 维度措辞（去 role/data-scope，改 governance + principal 绑定）。

不触及：conversational-context、agent-callplan-evidence、registry-ontology-contract、durable-approval-store。
