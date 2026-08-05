# Composite Fact and Output Projection Runbook

## Document Version

| Field | Value |
|---|---|
| Runbook | `17-composite-fact-output-projection` |
| Version | `v0.2.0` |
| Status | `Implemented / Archived` |
| Created / Updated | `2026-08-03 / 2026-08-05` |
| Depends On | Runbook 16 |
| Unblocks | Runbook 18 |

## 1. Goal

实现注册、版本化、确定性的 `ReasoningFact[] -> MaterialSupplySnapshot` 投影，使多 READ 结果形成可追溯的组合业务事实，而不是由 LLM 拼接裸返回。

## 2. Current Baseline

- 原子 capability 已产出 `ExecutionResult`；READ `PlanExecutor` 通过 `succeededNodeResults` 保留构建规范化 `ReasoningFact` 所需的数据。
- `ProjectionInputAssembler`、capability-specific `FactBuilderRegistry` 和版本化 `OutputProjectionRegistry` 已实现。
- `MaterialSupplySnapshot` 已实现 deterministic freshness、completeness、limitations、lineage、conflict preservation 和 output hash；生产 orchestrator / `projectionRef` 接线仍 deferred。

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
npm --prefix frontend run verify
comet classic openspec -- validate --all --strict
git diff --check
```

## 8. Next Start Here

Runbook 17 已通过 `sap-nexus-output-projection-registry` 完成并归档。下一实施入口为 Runbook 18：只消费已注册 projection 产生的可追溯快照，形成 registered RuleSet 驱动的 `RecommendationPlan` 和最多一个 `ActionProposal`；不得顺带接入生产 orchestrator 或执行 SAP WRITE。

## Session Closeout - 2026-08-05

### Completed

- 实现版本化 `OutputProjectionRegistry`、`ProjectionInputAssembler`、capability-specific fact builders 和 `MaterialSupplySnapshot`。
- 扩展 READ `PlanExecutor` 的 projection payload 持久化与 fresh/cache/recovery fact 输入，同时保持原 node ledger/state-machine 语义。
- 将 `output-projection` 与 `read-plan-executor` delta specs 合并到 main specs，并归档到 `openspec/changes/archive/2026-08-05-sap-nexus-output-projection-registry/`。

### Verified

- `npm --prefix frontend run verify`：TypeScript、28/28 Vitest files、251/251 tests、Next.js production build 全部通过。
- `comet classic openspec -- validate --all --strict`：20/20 通过。
- OpenSpec tasks 40/40、Superpowers plan 64/64；final re-review 7/7 findings resolved，新增 Critical/Important/Minor 为 0/0/0。

### Blockers

- 无 Runbook 18 component/Eval 实施 blocker。
- 生产 orchestrator / `projectionRef` 接线仍是明确 deferred 边界，不能把 component projection 描述为 live end-to-end composition。

### Next Start Here

1. 阅读 `docs/runbooks/18-recommendation-decision-plan.md`。
2. 以 `MaterialSupplySnapshot` 的 completeness、limitations 和 lineage 为唯一组合事实输入，冻结 RuleSet registration 与 input sufficiency 契约。
3. 保持 Recommendation/Action proposal 与 Human Approval/Gateway execute 分离。
