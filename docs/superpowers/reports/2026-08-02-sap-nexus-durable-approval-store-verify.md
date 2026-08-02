# Verification Report: sap-nexus-durable-approval-store (P0B 项3)

> Change: `sap-nexus-durable-approval-store` | Branch: `feature/20260802/sap-nexus-durable-approval-store` | verify_mode: full | review_mode: standard | Date: 2026-08-02

## 结论

**PASS** - 验证通过，可合并归档。1 个 WARNING（Check 6 spec drift，已按用户 Option A 处理）+ 若干 Minor（build 阶段 reviewer 已接受），0 CRITICAL / 0 IMPORTANT。

## 改动规模

- 任务：19 个 OpenSpec task（4 个 strikethrough deferred-to-verify + 1 个 7.6 validate pass + 14 个实现完成）
- Delta spec：1 capability（`durable-approval-store` ADDED 4 Requirements）
- 变更文件：7 源文件（LeaseOutcome / LeaseInfo / DurableApprovalStore / ApprovalRecordCodec / FileDurableApprovalStore + 2 测试）+ plan/tasks.md + design doc divergence note
- 规模评估：full（任务数 19 > 3，delta spec 1 capability，变更文件 66 > 8）

## 7 项全量验证检查

| # | 检查 | 结果 | 证据 |
|---|---|---|---|
| 1 | tasks.md 全部完成 | PASS | 无 `- [ ]` 未勾选；4 deferred（3.3/5.2/6.2/7.3）转 strikethrough note；7.6 已勾选 |
| 2 | 实现符合 design.md 高层决策 | PASS | D1-D5 / 锁定模型 / 安全契约 / TTL 基准均符合（各 task reviewer 已核） |
| 3 | 实现符合 Design Doc | PASS | `docs/superpowers/specs/2026-08-02-durable-approval-store-design.md` 决策均落实 |
| 4 | 能力规格场景全通过 | PASS | durable 持久化 / cross-restart 恢复 / anti-replay（20 线程并发竞态）/ JSONL 保留 / TTL 场景 -- 118/118 `:core:test` 通过；TTL 场景归属见 Check 6 偏差 2 |
| 5 | proposal.md 目标已满足 | PASS | durable store 替换 InMemory / cross-restart 恢复 / cross-worker anti-replay / JSONL 审计保留 / 4 拒绝场景不变 |
| 6 | delta spec vs design doc 无矛盾 | WARNING -> 已处理 | 2 处矛盾（JSONL/D4 + TTL/ApprovalGuard 层），用户选 Option A：design doc 追加 Implementation Divergence 节（commit `2f2d18f`） |
| 7 | design docs 可定位 | PASS | `docs/superpowers/specs/2026-08-02-durable-approval-store-design.md` 存在且相关 |

## Check 6 Spec Drift 处理（Option A）

用户于 verify 阶段选择 Option A（design doc 加偏差记录）。两处矛盾均实现遵 design doc（正确），delta spec 文本为早期草案遗留：

1. **JSONL 恢复对账**：delta spec「reconciled against the JSONL audit」vs D4「不读 agent JSONL，durable store 内部一致性校验」。实现（`reconcile()`）遵 D4。
2. **TTL 拒绝层**：delta spec「claimForExecution rejects expired」vs design「ApprovalGuard 4 不变量拒绝（先于 claimForExecution，do-not-modify）」。实现（store claimForExecution 仅查 status）遵 design 分层。

偏差详情见 design doc `## Implementation Divergence` 节。

## 测试证据（fresh）

- `services/gateway/gradlew -p services/gateway test`（全模块 core+app+jco+odata）：**BUILD SUCCESSFUL**，176 tests 通过（含 FileDurableApprovalStoreTest 28 + ApprovalRecordCodecTest 3 + 既有 @WebMvcTest 等）
- `npx openspec validate --all --strict`：**15/15 passed, 0 failed**
- `npx openspec list --json`：项3 + 项4 active

## Build 阶段审查摘要

- 7 task 全部经 subagent-driven-development（TDD + standard review）：
  - Task 1（interfaces+codec）：无风险直接验收；2 偏离（instanceof 替 pattern switch Java17；FAIL_ON_UNKNOWN_PROPERTIES=false）
  - Task 2-7：均 per-task reviewer Approved，0 Critical/0 Important，累计 Minor 接受（partial-state-on-failure 可接受 / 过期边界不一致 / reconcile 无锁 startup-only / 等）
- 最终全分支审查（opus）：**Approved**，1 Important（recoverAll/reconcile 未 wire 启动）-> fix agent `@PostConstruct`（commit `8047990`）-> re-review Approved
- build->verify guard：ALL CHECKS PASSED

## 安全契约核验

- WRITE capabilities 不绕过 Human Approval：`claimForExecution` 仅迁移 `approved->executing`，不创建 approval ✅
- `claimForExecution` 幂等：非 approved 返回 empty ✅
- 过期 approval 不可 execute：`ApprovalGuard.check` 校验 `isExpired` 返回 `APPROVAL_EXPIRED`（先于 claimForExecution）✅
- `ApprovalRecord` 不存 SAP credentials（仅 hash+params+approver+timestamps+status）✅
- 无 `BAPI_TRANSACTION_COMMIT`/`ROLLBACK` 新增 ✅
- 路径穿越阻断：`safeName` 校验 `[a-zA-Z0-9_-]+` ✅
- 双执行防护：`claimForExecution` status gate + withFileLock 原子迁移 + 20 线程并发竞态测试 ✅
- `ApprovalGuard`/`ApprovalRecord`/`ApprovalStore`/`CapabilityController` 未修改 ✅

## 分支处理

用户选择：**合并到 main**（FF merge + 删除 feature 分支）。

## Deferred 项（已记录，非阻塞）

- 3.3/5.2（JSONL 对账文本）+ 6.2（claim expiry 归属）+ 7.3（JSONL 审计独立测试）：spec drift 已 Option A 文档化；7.3 独立测试缺失（JSONL 审计未改，5.1 已保）。
- 生产硬化 backlog（非阻塞）：lease multi-worker TOCTOU、CheckpointRef validation、idempotency TTL、reconcile 并发契约注释、corrupted JSON fail-fast 策略、相对数据目录文档。
