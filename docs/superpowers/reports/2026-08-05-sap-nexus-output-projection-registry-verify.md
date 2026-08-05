# 验证报告：sap-nexus-output-projection-registry

- 日期：2026-08-05
- 验证模式：`full`
- 工作流：Classic / spec-driven
- 分支：`feature/20260804/sap-nexus-output-projection-registry`
- 已验证 HEAD：`d94c0aba34b110b02b79860fba4bf47cbf197aef`
- 变更范围：`810a00edb70f1910758a16ece3092e26ce3eac5e..d94c0aba34b110b02b79860fba4bf47cbf197aef`

## 结论总览

| 维度 | 结论 | 证据 |
|---|---|---|
| 完整性 | PASS | OpenSpec 任务 40/40；Superpowers 计划 64/64；9/9 个需求与 33/33 个场景均有映射 |
| 正确性 | PASS | 9 个需求都有实现与行为测试证据；最终复审确认 7/7 个问题已解决，且没有新增问题 |
| 一致性 | PASS | proposal、OpenSpec design、两份 delta spec、技术设计、运行时代码与测试一致，无 spec/design drift |
| 项目验证 | PASS | TypeScript 类型检查、Vitest 28/28 文件与 251/251 测试、Next.js 生产构建、Classic OpenSpec strict 20/20 |

## 完整性验证

- `comet classic openspec -- instructions apply --change "sap-nexus-output-projection-registry" --json` 返回 `40/40`、`remaining=0`、`state=all_done`。
- `tasks.md` 与 Superpowers 实施计划均不存在未勾选任务。
- 两个 delta capability 均存在：`output-projection` 与 `read-plan-executor`。
- 关联技术设计文件存在：`docs/superpowers/specs/2026-08-04-sap-nexus-output-projection-registry-design.md`，且其 change 元数据指向当前变更。

## 正确性映射

| 需求 | 实现证据 | 场景与测试证据 | 结论 |
|---|---|---|---|
| 版本化 OutputProjection 注册表 | `frontend/src/runtime/projection/registry.ts` 使用嵌套 Map 保存精确 tuple，并以结构化错误 fail-closed | `registry.test.ts` 覆盖精确解析、未知 id/version、包含 `@` 的标识、tuple 边界与重复注册 | PASS |
| Projection 输入组装 | `assembler.ts` 与 `fact-builder.ts` 只组装成功节点的规范化 facts，并使用 code-unit 顺序与 epoch freshness | `assembler.test.ts`、`fact-builder.test.ts` 覆盖双 READ、非成功排除、缺 builder/trace、数值与 PO identity、非法 freshness、混合字符 id、150,000 facts | PASS |
| 持久化 projection payload 恢复 | `plan-executor.ts` 在权威 `SUCCEEDED` 前持久化完整 payload，并通过合法的 `EXECUTING` 出口恢复 | `plan-executor-recovery.test.ts` 覆盖写入前 fail-closed、写入后恢复、历史缺 payload 降级，以及不重复 Gateway READ | PASS |
| MaterialSupplySnapshot 组合事实束 | `material-supply-snapshot.ts` 产出 facts、元数据、freshness、completeness、lineage、limitations 与 hash，不计算业务派生值 | component Eval 与 projection tests 覆盖双 READ complete snapshot 和 16 字段 lineage | PASS |
| partial/incomplete 策略 | required/optional FactTypes、失败状态、missing facts 与阻塞/非阻塞 limitations 均有显式裁决 | projection matrix 覆盖 required 缺失、optional 缺失、FAILED/TIMED_OUT/CANCELLED 与 `no_fact_builder` | PASS |
| freshness/unit/conflict 确定性 | freshness 按 parsed epoch 比较并保留源字符串；unit/conflict 保留证据，不换算、不选择真值 | 测试覆盖不同 epoch、offset-equivalent instant、单位不兼容、去重与稳定冲突 facts | PASS |
| 确定性 output hash | `hash.ts` 对 normalized facts、version、snapshotId 组成的 canonical envelope 计算 hash | `hash.test.ts` 覆盖 permutation 稳定性、输入变化与变长字段边界碰撞回归 | PASS |
| raw/model 输入隔离 | `ProjectionInput` 仅暴露 `planExecutionRecord` 与规范化 `facts`；projection 无 Gateway/LLM/SAP 依赖 | `assembler.test.ts` 的编译期 `@ts-expect-error` 断言拒绝 raw payload、conversation text 与 model output | PASS |
| Executor 暴露成功节点 fact 输入 | `PlanExecutorResult.succeededNodeResults` 保留 fresh/cache/recovered records，使用当前 `runId`，并允许 nullable Gateway trace | executor 与 recovery suites 覆盖 fresh、cache、existing-success hydration、缺/空 trace，以及旧结果 buckets 语义不变 | PASS |

## 一致性与漂移检查

- Proposal 的目标均已实现：注册式确定性 projection、MaterialSupplySnapshot、executor-to-fact assembly、partial/incomplete、lineage/freshness/conflict、确定性 hash 与 component Eval。
- Proposal 的 non-goals 仍保持：没有生产 orchestrator 或 `projectionRef` 接线，没有 Recommendation/Action、采购数量/日期/采购组计算、LLM、Knowledge/RAG、SAP WRITE、Saga 或自动补偿。
- OpenSpec design 的 D1-D5 与运行时一致：TypeScript projection 模块、嵌套 tuple 注册表、cache-first executor payload、组合事实束与 canonical envelope hash。
- Final review 修复按预期改变了 artifact hash；当前 OpenSpec design、delta spec 与技术设计已统一 parsed-epoch freshness、精确 tuple identity、cache-first recovery、code-unit ordering、高基数聚合和 hash framing。
- Executor 仍为九态模型，合法 transition graph 未改变；恢复只使用既有 `EXECUTING -> SUCCEEDED` 与 `EXECUTING -> FAILED`。
- Delta specs 与技术设计之间没有矛盾，不需要进入 Implementation Divergence 决策点。

## Review 证据

- Tasks 1-7 均完成 thorough task review。
- 初次 whole-branch review 发现 5 个 Important 与 2 个 Minor。
- 修复提交 `2ff280f04bb2f4a71b7a4184d9c11deff59f9758` 通过六组 TDD RED/GREEN 修复全部七项，并同步 design/spec。
- Fresh final re-review 结论：7/7 resolved，未解决 Important/Minor 为 0/0，新增 Critical/Important/Minor 为 0/0，可进入 Verify。
- Build phase 已完成同一代码范围的完整 review，因此 Verify 不重复派发代码 reviewer，而专注需求、场景与 drift 验证。

## 当前命令证据

| 命令 | 结果 |
|---|---|
| `npm --prefix frontend run verify` | PASS：typecheck；Vitest 28/28 文件、251/251 测试；Next.js production build；静态页面 6/6 |
| `npm --prefix frontend run build` | PASS；已作为 Build phase 的 command-check 记录 |
| `comet classic openspec -- validate --all --strict` | PASS：20 passed，0 failed |
| `git diff --check 810a00edb70f1910758a16ece3092e26ce3eac5e..HEAD` | PASS：无 whitespace error |
| committed-range scope audit | PASS：39 个预期文件；不含 `.env`、credentials、runtime traces、production orchestrator 或 `projectionRef` wiring |

## 问题分级

### CRITICAL

无。

### WARNING

无。

### SUGGESTION

无。

## 已记录边界

- 生产 orchestrator 集成仍按设计 deferred；当前变更证明 component/Eval 边界，不声称生产接线成熟。
- Idempotency payload 与 ledger 仍是两个独立持久记录；保证范围是 cache-first ordering 加 fail-closed restart recovery，不宣称跨存储原子事务。
- 历史 pre-change `SUCCEEDED` 若缺完整 payload，会保留成功状态、遗漏不可恢复的 projection record，并且不会被自动重新执行。

## 最终评估

Full verification 的完整性、正确性与一致性检查均通过。实现符合 9 个 delta requirements 和 33 个 scenarios，与已确认设计一致，可以进入 archive confirmation。
