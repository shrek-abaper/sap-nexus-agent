# Brainstorm Summary

- Change: sap-nexus-agent-callplan-evidence
- Date: 2026-06-20

## 确认的技术方案

采用标准库优先的 deterministic Agent slice：

- 使用规则 parser 识别中文库存可用量意图，并抽取 `material`、`plant`、可选 `unit`。
- 使用 Registry closed-set selector，只允许 `MM.Inventory.GetAvailability`，不允许 Agent 生成或覆盖 `rfcName`。
- 缺 `material` 或 `plant` 时返回中文澄清，并保证 Gateway validate / execute 调用次数为 0。
- Agent 在 Gateway validate 前生成 CallPlan，包含 Agent 侧 `traceId`、capability、kind、parameters、validation policy、creator、approval requirement。
- Gateway 当前会生成自己的 validate / execute `traceId`；Agent 将 CallPlan 的 `traceId` 作为 `agentTraceId`，将 Gateway 返回的 `traceId` 作为 `gatewayTraceId` 写入 evidence，避免修改已归档 Gateway 契约。
- Gateway client 只调用 capability-level `/capabilities/{capabilityId}/validate` 和 `/capabilities/{capabilityId}/execute`，请求体只发送 `parameters`。
- `ExecutionResult` 先转换为 `ReasoningFact`，Narrator 只消费 facts，不直接消费裸 Gateway/SAP response。
- Fast tests 和 eval 默认用 fake Gateway client；live Gateway smoke 仅作为本地 Gateway 和 SAP env 可用时的额外验证。

## 关键取舍与风险

- 先不用 LLM：降低 hallucination 和 prompt 依赖风险；代价是中文 parser 覆盖面有限，通过 eval 扩展缓解。
- 先不新增 HTTP/schema 外部依赖：避免网络安装和 bootstrap 复杂度；代价是 HTTP client 代码稍啰嗦。
- 不修改 Gateway/Registry：保持已归档 `capability-registry-gateway` contract 稳定；代价是 Agent/Gateway traceId 需要双字段关联。
- Runtime evidence 可本地生成但不提交：满足 replay 设计，同时避免敏感或 bulky trace 进入 git。

## 测试策略

- `agent/tests/` 覆盖 parser、missing params、selector、CallPlan、Gateway ordering、ExecutionResult adapter、ReasoningFact、Narrator guard。
- `evals/inventory_availability_cases.yaml` 覆盖 happy path、缺参、非法参数、未知意图、Gateway failure、敏感信息 guard。
- 默认验证命令：`python -m pytest agent/tests`、`python -m sap_nexus_agent.eval evals/inventory_availability_cases.yaml`、`openspec validate --all --strict`。
- live Gateway smoke 是可选验证，不阻塞 fast tests。

## Spec Patch

无。当前 OpenSpec delta spec 已覆盖必要验收场景；`agentTraceId` / `gatewayTraceId` 关联属于设计实现决策，不改变需求范围。
