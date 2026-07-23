# 语义规划基础验证报告

| 字段 | 值 |
|---|---|
| Change | `sap-nexus-semantic-planning-foundation` |
| 阶段 | S1 语义规划基础 |
| 日期 | 2026-07-19 |
| 结论 | **PASS - Comet 完整验证与本地合并已完成；archive 等待单独确认** |
| Snapshot | `sha256:bf0ac12a482d719725bf888feb9d3e10e60e583aa91c999a819a49001ce92092` |

## 范围

- S1 仅实现契约、不可变图、快照以及 GoalSpec/PlanGraph 验证。
- 一项跨契约兼容性修正使现有 executor binding schema 与权威 SAP WRITE
  binding 对齐；它不增加运行时路径，也不把 S1 扩展为执行层。
- 不生成计划，不调用 LLM、Gateway 或 SAP，不修改前端和运行时编排。
- 本次验证不授权 S2 dry-run 执行、S3 只读组合执行、Dynamic Planner
  runtime 或写能力组合。

## 契约证据

| 门禁 | 命令 | 结果 |
|---|---|---|
| 旧 Registry | `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml` | exit `0`；`Registry contract valid: registry/capabilities.yaml` |
| 语义规划 | `.venv/bin/python scripts/validate-semantic-planning-contract.py` | exit `0`；snapshotId `sha256:bf0ac12a482d719725bf888feb9d3e10e60e583aa91c999a819a49001ce92092` |
| Executor Binding 兼容性 | `.venv/bin/python -m pytest agent/tests/test_contract_files.py::test_executor_binding_catalog_with_sap_write_validates agent/tests/test_contract_files.py::test_executor_binding_schema_rejects_unknown_side_effect -v` | PASS；`2 passed in 0.21s` |
| 聚焦测试 | `.venv/bin/python -m pytest agent/tests/test_semantic_planning_contract.py -v` | PASS；`287 passed in 6.78s` |
| 完整证据 | `scripts/verify-agent-callplan-evidence.sh` | fresh exit `0`；`550 passed, 1 skipped in 10.17s`；inventory eval `7/7`；seed eval `13/13`；PR eval `9/9` |
| 合并后 main 证据 | fast-forward merge 后运行 `scripts/verify-agent-callplan-evidence.sh` | exit `0`；`550 passed, 1 skipped in 7.27s`；eval `7/7 + 13/13 + 9/9`；OpenSpec `8/8` |
| OpenSpec 状态 | `openspec status --change sap-nexus-semantic-planning-foundation --json` | exit `0`；`27/27`、`complete` |
| OpenSpec 严格校验 | `openspec validate --all --strict` | exit `0`；`Totals: 8 passed, 0 failed (8 items)` |
| Build Guard | `comet-guard.mjs sap-nexus-semantic-planning-foundation build --apply` | 全部检查 PASS；phase 推进到 `verify` |
| Verify Guard | `comet-guard.mjs sap-nexus-semantic-planning-foundation verify --apply` | 全部检查 PASS；中文报告检查通过；phase 推进到 `archive` |

## 证据原文

聚焦 pytest 最终摘要：

```text
============================= 287 passed in 6.78s ==============================
```

OpenSpec strict 最终摘要：

```text
Totals: 8 passed, 0 failed (8 items)
```

语义契约输出：

```text
Legacy registry contract valid
Semantic planning contract valid: snapshotId=sha256:bf0ac12a482d719725bf888feb9d3e10e60e583aa91c999a819a49001ce92092
```

Executor binding 兼容性聚焦摘要：

```text
test_executor_binding_catalog_with_sap_write_validates PASSED
test_executor_binding_schema_rejects_unknown_side_effect PASSED
============================== 2 passed in 0.21s ===============================
```

完整证据中的 eval 摘要：

```text
Eval passed: 7/7
Eval passed: 13/13
Eval passed: 9/9
```

OpenSpec 在刷新 PostHog telemetry 时输出过 DNS/network 错误。权威的 status
和 strict validation 命令均以 `0` 退出，telemetry 刷新失败不改变校验结果。

## Comet 完整验证

规模评估选择 `verify_mode=full`：27 个 OpenSpec tasks、2 个 delta spec
capabilities 和 42 个变更路径均超过轻量验证阈值。

| 维度 | 结果 | 证据 |
|---|---|---|
| 完整性 | **PASS** | `27/27` OpenSpec tasks 已完成；`9/9` requirements 已发布并实现 |
| 正确性 | **PASS** | `28/28` scenarios 映射到聚焦正反例测试；fresh full evidence 以 `0` 退出 |
| 一致性 | **PASS** | OpenSpec design 与 Superpowers Design Doc 在事实所有权、快照、治理和只验证边界上保持一致 |
| 安全性 | **PASS** | 42 个变更路径中 selector/orchestrator/CallPlan/ReasoningFact/frontend/Java Gateway runtime 路径为 `0` |
| 审查 | **PASS** | Task 7 复审 `0/0/0`；最终 whole-change review 为 `0 Critical / 0 Important / 2 Minor` |

Requirement 到证据的映射：

- Registry v2 schema 与原子运行时兼容性：contract schema 测试、Registry
  validator 测试、Registry loader descriptor 等价性和完整 Agent/eval
  evidence bundle。
- Fact Types/relations 单一所有权及确定性不可变图：producer edge 派生、禁止
  authored derived edge、endpoint、dependency cycle、provenance folding 和
  deep immutability 测试。
- 四源 Registry Snapshot：精确来源、canonical mapping order、array order、
  deterministic digest、内容敏感性和 stale snapshot PlanGraph 测试。
- GoalSpec 可达性与治理：reachable Fact、unknown Fact 与 gap 区分、inactive
  producer gap，以及 READ_ONLY 与 Action 的隔离测试。
- PlanGraph provenance/consistency/projection：有效双节点 pilot、parameter
  source、Fact/data edge、dependency/topology、governance、goal output、
  snapshot 和 technical field rejection matrices。
- 结构化确定性报告与 validation-only 范围：精确 `(path, code, message)`
  排序、全部 15 个批准错误码、caller-authored plan 保持不变、无 authority
  artifact、runtime import scan 及组合 release-gate 测试。

未发现 delta spec 与 design 冲突。Executor binding 的 `sap_write` enum 修正
只是与现有权威 WRITE binding 对齐的兼容性修正，已在下文明确记录，不改变
执行或审批所有权。

最终审查保留以下非阻断后续项：

1. 在 S2 扩大报告使用面之前，将上游 `jsonschema` 英文诊断规范化为项目自有
   的确定性消息。
2. 在 S2/S3 hardening 前，把非法 UTF-8 源解码异常封装为
   `SourceLoadError`；当前路径仍会在发布 graph/snapshot 前 fail closed。
3. 在 S3 只读执行前增加 3+ binding/field 及混合
   dependency/precondition matrices；现有 S1 逻辑不依赖固定基数，未发现生产缺陷。

## Executor Binding 兼容性修正

- `schemas/executor-binding.schema.json` 在
  `constraints.sideEffect.enum` 中加入 `sap_write`，把
  `none | read | write` 调整为 `none | read | write | sap_write`。
- 该修正使 schema 与 `registry/executor-bindings.yaml` 中已有的权威
  `sap.mm.pr.create-draft` WRITE binding 对齐；其约束仍是
  `sideEffect: sap_write`，原有 `none`、`read`、`write` 均保留。
- Fresh focused tests 证明 checked-in binding catalog 可使用 `sap_write`
  通过验证，同时 closed enum 仍拒绝无关值 `destructive`。
- 该 schema 兼容性修正不增加 executor、selector、orchestrator、Gateway 或
  SAP runtime path，也不放松 Human Approval：`MM.PR.CreateDraft` 仍是
  `governance.sideEffect=sap_write`、`requiresApproval=true`、
  `approvalPolicy=human_required` 的 Action；现有 Gateway approval guard 与
  WRITE execution boundary 保持不变。

## S1 契约摘要

- Registry snapshot 确定性覆盖四个已发布来源：
  `registry/capabilities.yaml`、`registry/executor-bindings.yaml`、
  `ontology/fact-types.yaml`、`ontology/capability-relations.yaml`。
- 不可变内存语义图从三个已注册能力导出恰好三条 `producesFactType` edge；
  首个 pilot 的 authored relation catalog 保持为空。
- `ContractValidationReport` 覆盖 source schema、identity、relation、
  dependency 和 immutable graph compilation findings。
- `GoalReachabilityReport` 覆盖 GoalSpec shape、reachability、capability gap
  与 READ_ONLY governance，不调用 planner 或 executor。
- `PlanValidationReport` 覆盖 caller-authored PlanGraph shape、Registry
  projection、parameter provenance、data/dependency edge、topology、
  governance、Goal output 和 snapshot drift，不生成或修复 plan。
- 测试期间，首个 PlanGraph fixture 绑定 fresh Registry snapshot，并保持两个
  READ `Function` nodes 与 `edges: []`。

## 边界证据

- Whole-branch 审查使用固定 Git 对象范围
  `7a1832a1328e7783e295cd9e9da21a80a01e4fc2..944924b8e1175174a08395c7ab9c91bc5ba31bf3`，
  不依赖已经删除的 feature branch 名称。
- 42 个唯一变更路径分组为：semantic contract implementation `6`；schemas
  `7`；published catalogs/Registry `3`；Agent tests/fixtures `6`；
  release-gate scripts `3`；design/plan/report/runbook/roadmap docs `6`；
  OpenSpec/Comet artifacts `11`。Schema 分组明确包含
  `schemas/executor-binding.schema.json` 及上文记录的 `sap_write` 修正。
- Whole-branch 范围不存在 forbidden runtime path：selector、orchestrator、
  CallPlan、ReasoningFact、Gateway、SAP executor 和 frontend runtime 文件均未
  变更；technical architecture 文件也未变更。
- 针对 selector、orchestrator、CallPlan、reasoning、Gateway 和 frontend
  路径的 scoped diff 检查结果为 `0` 个变更。
- `agent/sap_nexus_agent/semantic_planning/` 之外没有模块导入新 package；
  import scan 只包含标准库、`yaml`、`jsonschema` 和内部 semantic-contract
  模块。
- Dependency manifests 没有 OpenHarness、Neo4j 或 GraphDB runtime dependency。
  OpenHarness 仍是设计参考，graph 仍是不可变的进程内派生索引。
- Fixture 断言输出 `Pilot fixture boundary valid: 2 READ nodes, 0 edges`。
- 当前产品 runtime 仍只执行 single-capability CallPlan。批准的
  `ESCALATE_TO_PLANNER` record-and-explain policy 仍是 multi-capability goal
  的边界；S3 独立实施和验证前，本 change 不增加自动 composition path。

## 架构对照

S1 实现与批准的 technical architecture 保持一致：

- LLM output 仍是 advisory；S1 不增加 natural-language GoalSpec 或
  PlanDraft generation。
- Registry identifiers 与 deterministic validation 仍是权威。
- Gateway 仍只解析已注册的 `capabilityId -> bindingId`；Planner、ontology
  query 或 semantic mapping 均未移动到 Gateway。
- Graph data 是由已发布文件和 Registry snapshot 支撑的 derived read-only
  index，不是新的 execution authority 或 database dependency。
- READ_ONLY plan 拒绝 Action；validation 不产生 approval 或 SAP execution
  artifact。

未发现需要修复实现的架构不一致。Technical architecture 已检查并按 Task 7
inspect-only 边界保持不变；其 composition maturity table 与 section 5.4 仍将
foundation 标为 `Next Design`，这些 lifecycle labels 相对当前已验证的 S1 状态
已经陈旧。本 change 不修改该文件；当前 lifecycle truth 由 implementation
roadmap、runbook 和本验证报告承载，而 technical architecture 继续作为
execution authority、registered capability、deterministic validation、
immutable graph、Gateway 和 Human Approval invariants 的权威说明。

## 剩余范围

- S2：natural language -> GoalSpec candidate、PlanDraft、deterministic
  PlanCompiler 和 dry-run preview；S2 不得调用 Gateway 或 SAP。
- S3：执行已批准 PlanGraph 的 read-only composition，并为
  `MaterialSupplySnapshot` 聚合 per-Fact lineage。
- 当前 runtime 仍是 single-capability；S3 通过独立 design、eval、review 和
  verification 前不启用 multi-capability execution。
- Dynamic Planner runtime、graph database runtime、OpenHarness runtime、
  write composition、recommendation generation 和 automatic publication 均不在
  本 change 范围内。

## 收尾状态

- S1 implementation evidence 与 Comet full verification 均为 PASS。
- OpenSpec tasks 为 `27/27`；Comet phase 为 `archive`，verify mode 为 `full`，
  `verify_result=pass`，`verified_at=2026-07-19`。
- `main` 已从 `7a1832a` fast-forward 到已验证实现提交 `944924b`；合并后
  evidence bundle 以 `0` 退出，因此 Comet `branch_status` 为 `handled`。
- Feature branch `feature/20260719/sap-nexus-semantic-planning-foundation` 已删除。
- OpenSpec change 仍处于 active 且未 archive。
- Archive 是 verify guard 通过后的独立显式确认点；实际 archive 目录存在前不
  发布 archive link。
