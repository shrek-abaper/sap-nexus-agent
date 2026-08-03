# Composite Fact and Output Projection Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `17-composite-fact-output-projection` |
| Version | `v0.1.0` |
| Status | `Planned` |
| Created / Updated | `2026-08-03` |
| Depends On | Runbook 16 |
| Unblocks | Runbook 18 |

## 1. Goal

实现注册、版本化、确定性的 `ReasoningFact[] -> MaterialSupplySnapshot` 投影，使多 READ 结果形成可追溯的组合业务事实，而不是由 LLM 拼接裸返回。

## 2. Current Baseline

- 原子 capability 已产出 `ExecutionResult` 和 `ReasoningFact`。
- 技术架构已定义 freshness、completeness、limitations 和 lineage 边界。
- 当前没有 runtime `OutputProjection`，也没有 `MaterialSupplySnapshot` 的 partial/incomplete 执行契约。

## 3. Contracts and Data Flow

```text
PlanExecutionRecord + successful ReasoningFact[]
-> registered OutputProjection@version
-> MaterialSupplySnapshot
   { asOf, sourceFreshness, completeness, facts, lineage,
     missingFacts, failedNodes, limitations }
```

projection 必须声明 required/optional input Fact Types、output schema、时间口径和 partial policy。每个输出字段可追溯到 fact/evidence；跨节点 `asOf` 不一致时保留各自时间并产生 limitation。

## 4. Scope and Non-goals

- Scope：projection registry/schema/validator、MaterialSupplySnapshot、partial/incomplete policy、lineage、projection Eval。
- Non-goal：不计算采购数量/日期/采购组、不调用 LLM、不形成 Action、不接 Knowledge/RAG。

## 5. Safety Boundaries

- 缺少 required fact、节点失败/超时/取消时不得标记 `complete`。
- projection 不能读取 raw Gateway payload、conversation text 或 model output，只读取 normalized facts 和 ledger metadata。
- 数值、单位和时间转换必须由版本化确定性规则完成。

## 6. Acceptance Criteria

- 双 READ 成功输出 complete snapshot，字段 lineage 完整率 100%。
- 单节点失败输出 partial/incomplete、missing facts 和 limitation。
- freshness mismatch、单位不兼容、重复/冲突 fact 有确定性处理和 bad case。
- 相同输入、projection version 和 snapshot 产生相同输出 hash。

## 7. Verification

```bash
.venv/bin/python -m pytest agent/tests -q
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
```

## 8. Next Start Here

先冻结 `MaterialSupplySnapshot` JSON Schema 和 projection registration contract，再实现 projection。完成后 Runbook 18 才可基于该快照形成建议。
