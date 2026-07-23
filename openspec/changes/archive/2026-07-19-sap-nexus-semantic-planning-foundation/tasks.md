## 1. Registry v2 与语义 schemas

- [x] 1.1 先添加 Registry v2、Fact Type catalog 和 relation catalog 的失败 contract tests
- [x] 1.2 原子迁移 `registry/capabilities.yaml` 到 version 2，为全部 input 增加 `bindingKind`，为三个 primary output 增加已批准 `factTypeRef`
- [x] 1.3 创建 `ontology/fact-types.yaml`、`ontology/capability-relations.yaml` 及五份 semantic planning JSON Schemas
- [x] 1.4 同步现有 inline capability fixtures 到 v2，并通过全部 contract schema 正反例

## 2. Immutable contracts、loader 与 Registry Snapshot

- [x] 2.1 先添加四源 loader、canonical JSON 和 deterministic snapshot 的失败测试
- [x] 2.2 创建 `semantic_planning` package 的 immutable report/source/snapshot value objects 与安全 YAML loader
- [x] 2.3 实现四源 canonical SHA-256 snapshot manifest，并通过格式稳定、array order 和内容敏感测试

## 3. Semantic graph 与 contract validation

- [x] 3.1 先添加 derived producer edges、deep immutability、structured issue sorting 和 invalid source tests
- [x] 3.2 实现 `SemanticGraphCompiler`，从 capability IO 派生 producer/consumer edges，并加入 authored dependency/precondition edges
- [x] 3.3 实现 source version、unique ID、Fact reference、binding reference、relation endpoint 和 dependency-cycle validation
- [x] 3.4 扩展现有 Registry validator 的 v2 IO invariants，完整保留 binding/secret/REST/OWL/eval checks

## 4. GoalSpec reachability

- [x] 4.1 创建 material-supply Goal fixture，并先添加 reachable/unknown/gap/governance 失败测试
- [x] 4.2 实现 GoalSpec shape、typed constraint、published Fact、active producer 和 execution-mode validation
- [x] 4.3 证明 `UNKNOWN_FACT_TYPE`、`CAPABILITY_GAP` 与 `GOVERNANCE_VIOLATION` 语义互不混淆

## 5. PlanGraph validation

- [x] 5.1 创建双 READ 节点、零 edge 的 material-supply Plan fixture，并先添加 fail-closed matrix
- [x] 5.2 实现 snapshot/goal identity、registered node、compiler projection、parameter provenance 和 governance validation
- [x] 5.3 实现 data/dependency edge、Fact compatibility、topological order 和 Goal output validation
- [x] 5.4 覆盖全部批准错误码，并证明 technical executor override 被拒绝且 validator 不生成或执行 PlanGraph

## 6. 组合 release gate 与兼容性回归

- [x] 6.1 创建组合旧 Registry gate 与新 semantic gate 的 `validate-semantic-planning-contract.py`
- [x] 6.2 将组合 CLI 接入 `verify-agent-callplan-evidence.sh`，不删除现有 Agent/eval/OpenSpec commands
- [x] 6.3 运行 focused schema/registry/semantic/loader tests，并证明三个 active capability runtime descriptor 不变
- [x] 6.4 运行完整 evidence script 和静态边界扫描，确认没有 LLM/Gateway/SAP/frontend/runtime scope leakage

## 7. Evidence、文档与 Comet closeout

- [x] 7.1 创建 verification report，记录真实 CLI、pytest、evidence 和 OpenSpec 输出
- [x] 7.2 同步 runbook 10、runbook index 和 implementation roadmap，将下一阶段设置为 S2 planner dry-run
- [x] 7.3 运行 `git diff --check`、`openspec validate --all --strict`、完整 evidence script 和 scoped status 检查
- [x] 7.4 完成 task review 与 final whole-change review，处理所有 Critical/Important findings
- [x] 7.5 经用户确认后执行 Comet verify/archive；未经明确要求不 commit
