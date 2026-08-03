---
comet_change: sap-nexus-governed-context-registry-snapshot
role: technical-design
canonical_spec: openspec
---

# Governed Context & Registry Snapshot 深度设计

> 本文档是 open 阶段 `design.md` 的深度技术细化，不替代或重写它。canonical spec 为 OpenSpec delta（`openspec/changes/sap-nexus-governed-context-registry-snapshot/specs/`）。

## 1. Context

P0B trusted/durable runtime 已归档：principal 在 Node backend 服务端注入并用于 durable Run/Session/Approval 鉴权（cross-principal fail-closed 在 store 层已实现）。S1 提供 `RegistrySnapshot`（四源）与 `build_registry_snapshot`；S2-A/S2-B 提供 `MatchDecision`、`CapabilityCard`、`filter_visible`、`PlanCompiler` dry-run。

代码事实缺口（已核查）：
- `run_query` 不接收 principal；`select_capability` 只消费 `IntentParseResult`。
- `EscalationHandoff.registry_snapshot_id` 恒空串（`getattr` 默认）。
- `filter_visible` 无运行时调用方，且只按 governance 过滤，无 principal 维度。
- `_compile_dry_run_safely` 另行加载 snapshot，`except Exception: return None` 静默降级。
- `discover_cards` 中 `del snapshot`；`CapabilityCard` 无 `registry_snapshot_id`。
- principal 止步 Node durable 鉴权层（`executeRunnerInBackground` 收 `principalId` 仅用于 `run.principalId` 校验，`runner()` 不传 Python）。
- Registry capability 无 `visibilityScope`/role 映射字段（governance 仅 sideEffect/requiresApproval/approvalPolicy/dataClassification/auditRequired；3 个 active capability 全 internal）。

## 2. Goals / Non-Goals

**Goals**：见 open 阶段 design.md（同快照绑定、principal/visibility pre-filter、结构化 fail-closed、CapabilityCard 安全投影、kind 从 snapshot 投影、ApprovalRecord 携带 snapshotId）。

**Non-Goals**：不改召回算法/PlanGraph v2/PlanExecutor/UI；不接 Knowledge/RAG；不执行新 SAP WRITE；不改 matcher 五态算法；不重建身份/状态/审批/事件机制；不实现 approval store 漂移执行校验（RB21）；**不扩 Registry schema（不引入 visibilityScope）**；不扩展 IntentAdapter 签名；不给 CallPlan 加 snapshotId。

## 3. 核心数据结构

### 3.1 TrustedPrincipal（Python 侧新增，与 frontend TS 对齐）

```python
@dataclass(frozen=True)
class TrustedPrincipal:
    principal_id: str
    role: str          # "admin" | "operator" | "viewer"
    data_scope: dict[str, str]  # {"tenantId": "..."}
```

> Python 侧当前无此类型（仅 frontend TS）。新增与 `frontend/src/runtime/principal/types.ts` 字段对齐。`PLACEHOLDER_PRINCIPAL` = `local-user-0001 / operator / {tenantId: default}`。

### 3.2 GovernedContext

```python
@dataclass(frozen=True)
class GovernedContext:
    principal: TrustedPrincipal
    scopes: tuple[str, ...]      # 从 data_scope 派生，当前预留
    snapshot_id: str             # 非空，来自 RegistrySnapshot.snapshot_id
    registry_version: int        # 来自 RegistrySnapshot.snapshot_version
```

### 3.3 SnapshotLease

```python
@dataclass(frozen=True)
class SnapshotLease:
    snapshot: RegistrySnapshot
    sources: SemanticSourceDocuments

    @property
    def snapshot_id(self) -> str: return self.snapshot.snapshot_id

    def assert_same(self, other_snapshot_id: str, stage: str) -> None:
        # 不一致 -> raise SnapshotDriftError（被 orchestrator 捕获转 PlannerFailure）
```

### 3.4 VisibleCapabilitySet

```python
@dataclass(frozen=True)
class VisibleCapabilitySet:
    cards: tuple[CapabilityCard, ...]   # 已 filter_visible
    snapshot_id: str
    principal_id: str
```

### 3.5 PlannerFailure

```python
@dataclass(frozen=True)
class PlannerFailure:
    error_type: Literal["SNAPSHOT_MISSING", "SNAPSHOT_DRIFT", "PRINCIPAL_MISMATCH",
                        "SOURCE_LOAD_ERROR", "VISIBILITY_DENIED"]
    message: str
    snapshot_id: str | None
    audit_evidence: dict   # {expected_snapshot_id, actual_snapshot_id, principal_id, source_paths, stage}
```

## 4. 数据流（深度）

```text
cli.py
  读 SAP_NEXUS_PRINCIPAL env (JSON) -> TrustedPrincipal  (缺省 -> PLACEHOLDER_PRINCIPAL)
  load_intent_catalog() -> 全 active capability
  filter_visible(catalog, for_execution=False) -> visible catalog  [governance 维度]
  build_intent_adapter(mode, visible_catalog)  [LLM prompt 只含可见 capability]
  run_query(text, gateway, intent_adapter=adapter, principal=principal)

run_query(text, gateway, *, intent_adapter, principal=None, context=None, ...)
  principal = principal or PLACEHOLDER_PRINCIPAL
  # 入口构造 lease（复用 _default_planner_sources + build_registry_snapshot）
  snapshot, sources = load_snapshot()   # 失败 -> PlannerFailure(SOURCE_LOAD_ERROR/SNAPSHOT_MISSING)
  lease = SnapshotLease(snapshot, sources)
  ctx = GovernedContext(principal, scopes, lease.snapshot_id, snapshot.snapshot_version)
  cards = discover_cards(snapshot, sources)   # 绑 snapshot，填 registry_snapshot_id
  visible = VisibleCapabilitySet(filter_visible(cards, for_execution=False),
                                 lease.snapshot_id, principal.principal_id)
  # intent（adapter 已绑 visible catalog，LLM 只见可见 capability）
  parsed = intent_adapter(text, context)
  decision = select_capability(parsed, visible)   # 双保险：过滤 matched_intents 中不可见
       # handoff.registry_snapshot_id = lease.snapshot_id  (非空)
  # ESCALATE
  if ESCALATE_TO_PLANNER:
      lease.assert_same(handoff.registry_snapshot_id, stage="planner")  # 漂移 -> PlannerFailure(SNAPSHOT_DRIFT)
      dry_run = compile_dry_run_from_handoff(handoff, lease.snapshot, sources)  # 消费 lease，不另行加载
  # SELECT 路径：kind 从 card.governance.requires_approval 判定（非 ACTION_CAPABILITY_IDS）
  # approval: create_approval_record(..., registry_snapshot_id=lease.snapshot_id)
  -> AgentOutcome(match_decision, dry_run, planner_failure?)
```

## 5. 实现决策（D1-D7 + Q1-Q7 确认摘要）

| ID | 决策 | 确认 |
|---|---|---|
| D1 | GovernedContext 在 `run_query` 入口构造 | ✓ |
| D2 | principal 载体 = 环境变量 `SAP_NEXUS_PRINCIPAL` JSON | Q2 ✓ |
| D3 | SnapshotLease 持有 + 漂移 fail-closed；planner 消费 lease | Q6 ✓ |
| D4 | `PlannerFailure` 结构化错误（5 种 error_type + audit_evidence） | Q7 ✓ |
| D5 | visibility pre-filter 在 matcher 之前（catalog 加载点 + matcher 双保险） | Q4 ✓ |
| D6 | capability kind 从 snapshot 投影（`governance.requires_approval`） | ✓ |
| D7 | `ApprovalRecord` 加 optional `registry_snapshot_id` | ✓ |
| Q1 | visibility 数据源 = governance + principal 绑定（不扩 Registry schema） | ✓ |
| Q3 | 缺省 principal = PLACEHOLDER_PRINCIPAL | ✓ |
| Q5 | CallPlan 不加 snapshotId（不触及 agent-callplan-evidence spec） | ✓ |

## 6. 模块与文件改动

| 文件 | 改动 |
|---|---|
| `agent/sap_nexus_agent/governed_context.py`（新） | `TrustedPrincipal`、`GovernedContext`、`SnapshotLease`、`VisibleCapabilitySet`、`PlannerFailure`、`PLACEHOLDER_PRINCIPAL` |
| `agent/sap_nexus_agent/orchestrator.py` | `run_query` 增 `principal` 参数；入口构造 lease + ctx + visible；`select_capability` 传 visible；`_compile_dry_run_safely` 消费 lease，失败返 `PlannerFailure`；kind 从 `governance.requires_approval` 判定；`AgentOutcome` 增 `planner_failure` |
| `agent/sap_nexus_agent/capability_selector.py` | `select_capability(parse_result, visible_capability_set)`：过滤 `matched_intents` 中不可见；`handoff.registry_snapshot_id` 从 ctx/lease 填入 |
| `agent/sap_nexus_agent/match_decision.py` | `EscalationHandoff.registry_snapshot_id` 由调用方填入非空（类型保持 str，语义非空） |
| `agent/sap_nexus_agent/visibility.py` | `filter_visible` 接入 matcher 路径（governance 维度，无 role 映射）；增 `filter_catalog` helper |
| `agent/sap_nexus_agent/planner/capability_card.py` | `CapabilityCard` 增 `registry_snapshot_id`；`discover_cards` 绑 snapshot（移除 `del snapshot`），填 `registry_snapshot_id` |
| `agent/sap_nexus_agent/cli.py` | 读 `SAP_NEXUS_PRINCIPAL` env -> `TrustedPrincipal`；`load_intent_catalog` -> `filter_visible` -> `build_intent_adapter`；`run_query` 传 `principal` |
| `agent/sap_nexus_agent/approval.py` | `ApprovalRecord` 增 `registry_snapshot_id: str = ""`；`from_dict`/`to_dict` 兼容；`create_approval_record` 接收 `registry_snapshot_id` |
| `frontend/src/runtime/agent-runtime-adapter.ts` | `executeRunnerInBackground` -> `runner` 传 principal；`runLocalPythonAgent` spawn 时设 `SAP_NEXUS_PRINCIPAL` env |
| `frontend/src/runtime/durable/types.ts` | `ApprovalRecord` 增 `registrySnapshotId` 字段（optional，序列化兼容） |
| 测试 | visibility leakage、cross-principal 决策层、snapshot 漂移、source load 失败、kind 投影、matcher Eval 回归、安全投影 negative test |

## 7. Spec Patch（回写 delta spec）

1. `governed-context-registry-snapshot` spec "Visibility pre-filter before LLM prompt"：`consider both principal visibility (role/data-scope) and governance` -> `consider governance (sideEffect/dataClassification) and bind the principal to the GovernedContext for same-snapshot/audit provenance; role-based capability visibility is deferred until the Registry carries a visibilityScope field`。
2. `governed-context-registry-snapshot` spec "cross-principal 决策层 fail-closed" scenario：调整为 `principal 绑定到 GovernedContext 用于审计与同快照证明；cross-principal 隔离在 durable 层 fail-closed（P0B）；决策层 visibility 基于 governance 维度`。
3. `semantic-match-decision` spec "Visibility pre-filter" MODIFIED：`consider both principal visibility (role/data-scope) and governance` -> `consider governance (sideEffect/dataClassification) and bind the principal to the GovernedContext`。

不触及：conversational-context、agent-callplan-evidence、registry-ontology-contract、durable-approval-store。

## 8. 测试策略

- **visibility leakage = 0**：fixture 注入 `visibility=HIDDEN` 的 capability，断言不进入 `VisibleCapabilitySet`、不进入 LLM prompt（catalog 过滤后不含）、不进入 matcher `matched_intents`。
- **cross-principal 决策层**：注入 `SAP_NEXUS_PRINCIPAL` env 多 principal，断言 `GovernedContext.principal_id` 正确；durable 层 cross-principal 隔离回归（P0B 既有测试）。
- **snapshot 漂移**：构造 `handoff.registry_snapshot_id != lease.snapshot_id`，断言 `PlannerFailure(SNAPSHOT_DRIFT)` + `audit_evidence.{expected_snapshot_id, actual_snapshot_id}`。
- **source load 失败**：损坏 YAML fixture，断言 `PlannerFailure(SOURCE_LOAD_ERROR)` + `audit_evidence.source_paths`。
- **capability kind 投影**：断言 Action 判定来自 `governance.requires_approval`；移除 `ACTION_CAPABILITY_IDS` 后 inventory/PO/PR 三路径回归。
- **matcher Eval 6/6 回归**：五态决策不回退；`CapabilityCard` 安全投影 negative test（断言不含 rfcName/serviceUrl/credentialRef/rawSql/executorBinding）。
- **ApprovalRecord**：`registry_snapshot_id` 非空且等于 `GovernedContext.snapshotId`；`from_dict`/`to_dict` 向后兼容（旧 payload 无字段时默认空）。

## 9. 风险与取舍

- **[visibility 无 role 映射]** -> 本轮 governance 维度；role-based 留后续（Registry 加 visibilityScope）；契约机制就位。
- **[principal env 注入]** -> principalId/role 非高敏，env 泄露可控；与 `SAP_NEXUS_APPROVAL_TTL_SECONDS` 模式一致。
- **[catalog 加载点过滤]** -> 双保险（catalog + matcher）；本地 dev（PLACEHOLDER）行为不变。
- **[ApprovalRecord 字段扩散 Node]** -> optional + `.get` 默认空；执行校验留 RB21。
- **[snapshot 加载性能]** -> 单次加载，SnapshotLease 持有。

## 10. 边界条件

- `SAP_NEXUS_PRINCIPAL` env JSON malformed -> 回退 PLACEHOLDER_PRINCIPAL（本地 dev 容错）或 PRINCIPAL_MISMATCH（共享环境严格）-- 本轮取回退 PLACEHOLDER + 日志告警。
- `build_registry_snapshot` 返回空 snapshot_id -> `PlannerFailure(SNAPSHOT_MISSING)`。
- `filter_visible` 返回空集（principal 无可见能力）-> `PlannerFailure(VISIBILITY_DENIED)`。
- LLM 返回不可见 capability（catalog 过滤后理论不应发生）-> matcher 层双保险过滤；若仍出现，REJECT。
- ESCALATE 时 `handoff=None` -> 不触发 planner，保持现有 match_decision 输出。

## 11. 迁移计划

1. 新增 `governed_context.py`（数据结构 + PLACEHOLDER）。
2. `run_query` 增 `principal` 参数（默认 None -> PLACEHOLDER）；入口构造 lease/ctx/visible。
3. `select_capability` 接 visible；`handoff.registry_snapshot_id` 从 lease 填入。
4. `discover_cards` 绑 snapshot + `CapabilityCard.registry_snapshot_id`；`_compile_dry_run_safely` 消费 lease，失败返 `PlannerFailure`。
5. `filter_visible` 接入 matcher 路径 + `filter_catalog` helper。
6. `ApprovalRecord` 加 `registry_snapshot_id`；`create_approval_record` 填入。
7. `cli.py` 读 env + 过滤 catalog + 传 principal；`agent-runtime-adapter.ts` 透传 principal env。
8. 回归测试 + `openspec validate --all --strict` + `pytest agent/tests` + `verify-agent-callplan-evidence.sh` + `npm --prefix frontend run verify`。

**回滚**：新参数默认 None / 字段 optional，旧调用路径行为不变；可按文件 revert。
