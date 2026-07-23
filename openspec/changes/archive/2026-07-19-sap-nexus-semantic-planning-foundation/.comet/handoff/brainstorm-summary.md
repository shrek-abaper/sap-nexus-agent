# Brainstorm Summary

- Change: `sap-nexus-semantic-planning-foundation`
- Date: `2026-07-19`

## 确认的技术方案

- 使用 split authority：`capabilities.yaml` 负责 capability IO 与 governance，`fact-types.yaml` 负责 canonical Fact Type，`capability-relations.yaml` 只负责非派生 `dependsOn` / `precondition`，`executor-bindings.yaml` 继续负责技术执行映射。
- `SemanticGraphCompiler` 从 output `factTypeRef` 和 fact-bound input 派生 `producesFactType` / `consumesFactType`，生成递归 immutable 的进程内只读图。
- Capability Registry 从 v1 原子迁移到 v2；所有现有 input 首期均为 `bindingKind=identifier`，三个 primary output 映射到已批准 Fact Types。
- `GoalSpec` 仅支持 `PLAN_ONLY` / `READ_ONLY`；`PlanGraph` 使用 hybrid snapshot，保存语义/治理投影但不包含 RFC、bindingId、URL、credential 或 executor mapping。
- `RegistrySnapshot` 对 capability Registry、executor binding catalog、Fact Type catalog、relation catalog 四源做 deterministic canonical SHA-256。
- S1 只加载、编译和验证 hand-authored fixtures；自然语言、PlanCompiler 属于 S2，Gateway/SAP read composition 属于 S3。

## 关键取舍与风险

- 避免在 relation catalog 重复 derived edges，否则会形成双写权威。
- 首个 material-supply fixture 是两个独立 READ 节点、零 edge，只证明 reachability、snapshot 和 governance，不宣称预测、采购数量、PR 自动创建或 runtime 并行。
- Snapshot S1 只定义 identity，不定义持久化；任何 S3 执行前必须补 content-addressed retention。
- 现有 Registry binding/secret/REST/OWL/eval gate 必须保留，并与新 semantic gate 组合，而不是被重写。
- Registry v2 是 breaking contract migration，必须同步全部 inline fixtures 并用现有 single-capability regression 证明兼容。

## 测试策略

- TDD 顺序：schemas/catalogs -> immutable contracts/loader/snapshot -> graph/contract validation -> Goal reachability -> Plan validation -> combined release gate。
- 覆盖全部 15 个批准错误码，并断言 JSON Pointer path 与 deterministic issue sorting。
- 首个 valid Goal/Plan fixture 验证 inventory + purchase-order 两个 READ capability、typed Goal constraints、Fact outputs、governance projection、snapshotId 和 `edges: []`。
- 运行 schema/registry/semantic/loader focused tests、现有 Agent/eval evidence script、OpenSpec strict validation 和静态 scope scan。

## Spec Patch

无。OpenSpec proposal、design、两份 delta specs 与已批准 Design Doc 一致。
