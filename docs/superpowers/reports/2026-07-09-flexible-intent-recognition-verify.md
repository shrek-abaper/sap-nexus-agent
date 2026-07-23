# Verification Report - flexible-intent-recognition

| Field | Value |
|---|---|
| Change | `flexible-intent-recognition` |
| Workflow | Comet full |
| Verify mode | full (20 tasks > 3, 1 delta capability) |
| Date | 2026-07-09 |
| Language | zh-CN |
| Result | PASS |

## 变更概要

将 Agent 意图识别从「库存-only 写死」重构为「从 registry active capability 动态派生闭集」的柔性识别：

- 新增 `registry_loader.py`：从 `registry/capabilities.yaml` 读 active capability 派生 `IntentCatalog`（capability 闭集 + 描述符）。
- 重构 `llm_intent.py`：LLM prompt 动态注入所有 active capability 的 capabilityId+description+inputs，LLM 直接选 capabilityId（不经 intent 名中转），闭集校验 + required 参数校验 + OData/RFC 检测；fallback 从 `parse_inventory_intent` 改 `parse_intent`（支持 PO）；别名表扩展含 PO。
- `intent.py`：`IntentParseResult` 加 `capability_id` 字段；`capability_selector.py` 优先用 capability_id。
- `cli.py`：入口改 `run_query` + catalog 注入；rule 模式也改 `parse_intent`（三路径一致）。
- `agent/pyproject.toml`：加 pyyaml 依赖。

不改 registry schema、下游 fact/narrator/gateway、前端事件流。

## 改动文件

修改：
- `agent/sap_nexus_agent/intent.py`、`capability_selector.py`、`llm_intent.py`、`cli.py`、`pyproject.toml`
- `agent/tests/test_llm_intent.py`、`test_orchestrator.py`
- `docs/superpowers/specs/2026-07-09-flexible-intent-recognition-design.md`（§9 review 发现）

新增：
- `agent/sap_nexus_agent/registry_loader.py`
- `agent/tests/test_registry_loader.py`
- `docs/superpowers/specs/2026-07-09-flexible-intent-recognition-design.md`
- `docs/superpowers/plans/2026-07-09-flexible-intent-recognition.md`
- `openspec/changes/flexible-intent-recognition/`（proposal/design/specs/tasks + .comet.yaml）

## 验证证据（fresh run，本报告生成前重新执行）

| # | 检查项 | 命令 | 结果 |
|---|---|---|---|
| 1 | tasks.md 全部完成 | 20/20 `[x]` | PASS |
| 2 | 实现符合 design.md 高层决策 | D1-D6 逐项核对 | PASS（registry 派生闭集/LLM 选 capabilityId/闭集校验/fallback parse_intent/CLI run_query/别名扩展） |
| 3 | 实现符合 Design Doc | design doc 即技术设计，review 发现记入 §9 | PASS |
| 4 | 能力规格场景全部通过 | delta spec 6 scenarios 对照实现+测试 | PASS |
| 5 | proposal.md 目标已满足 | 柔性识别 + PO 可达 + 新增能力自动支持 | PASS |
| 6 | delta spec 与 design doc 无矛盾 | §9 Implementation Divergence 记录 review 发现，无矛盾 | PASS |
| 7 | 关联设计文档可定位 | design doc 存在且相关 | PASS |

### 命令输出（exit code）

| 命令 | 退出码 | 关键输出 |
|---|---|---|
| `PYTHONPATH=agent .venv/bin/python -m pytest agent/tests -q` | 0 | `129 passed, 1 skipped` |
| `PYTHONPATH=agent .venv/bin/python -m sap_nexus_agent.eval evals/purchase_order_cases.json` | 0 | `Eval passed: 3/3` |
| `.venv/bin/python scripts/validate_registry_contract.py registry/capabilities.yaml` | 0 | 通过（registry schema 未改） |
| `openspec validate --all --strict` | 0 | `7 passed, 0 failed` |
| `scripts/verify-agent-callplan-evidence.sh` | 0 | `129 passed, 1 skipped`；eval `7/7` + `13/13`；openspec 7/7 |
| CLI `查询采购订单DEMOPO1 --json` | - | `callPlan.capabilityId=MM.PurchaseOrder.GetList`, `parameters={poNumber: DEMOPO1}` |

### 端到端确认

CLI 直测「查询采购订单DEMOPO1」：
- `callPlan.capabilityId = MM.PurchaseOrder.GetList` ✓
- `parameters = {poNumber: DEMOPO1}` ✓
- 不再返回 `当前仅支持已注册的只读能力...`（unsupported）✓
- 原始 bug 已修复：意图识别正确选 PO + 提取 poNumber + 进入 Gateway 执行

## 代码审查（review_mode: standard，build 阶段完成）

reviewer subagent 审查结论：With fixes。发现并处理：

- **Important #1（已修复）**：unhashable capabilityId safe-fail 回归--`frozenset` 成员检查对 list-valued capabilityId 抛 TypeError 不被捕获。已加 `isinstance(capability_id, str)` 守卫 + 测试 `test_parse_with_llm_handles_unhashable_capability_id_without_crash`。
- **Important #2（跟进项，超出本 change 范围）**：PO fact builder 不处理真实 OData 嵌套 items 结构（`reasoning_fact.py`，本 change 未改）。此前 CLI 到不了 PO 故未暴露；本 change 让 PO 可达后暴露，端到端返回 NARRATIVE_GUARD_ERROR。意图识别层正确，此为下游独立 bug。记入 design doc §9，不阻塞归档。
- **Minor #1（已修）**：删除 test_llm_intent.py 未用的 `parse_intent` import。
- **Minor #4（已加）**：新增 `test_parse_with_llm_rejects_all_capability_ids_when_catalog_empty` 空 catalog safe-fail 测试。

## 已知偏差与跟进项

1. **PO fact builder 嵌套 items（跟进项）**：`build_purchase_order_facts` 从 PO header 读 plant/material/orderQuantity，真实 OData 嵌套在 `items[]`。本 change 暴露此既有 bug。跟进：展开 items[] 逐行建 fact + FakePoGatewayClient 测试数据改真实嵌套。不阻塞本 change。
2. **流式为事件粒度**：narrative 在 narrative_created 事件到达时一次性出现（非逐字）。属既有设计，本 change 未涉及。
3. **代码未提交**：按用户明确选择「保持现状」，改动留在 main 工作区。分支处理 = 保持现状（Option 3）。
4. **workbench rule 模式行为变化**：`build_intent_adapter("rule")` 从 `parse_inventory_intent` 改 `parse_intent`，workbench rule 模式现可路由 PO（正向改进，design doc §9 已记录）。

## 安全检查

- 无硬编码密钥 / token / 凭据 / 连接串。
- 新增 pyyaml 依赖（标准库，无安全风险）。
- 闭集校验防止任意 capability 执行；OData/RFC 注入检测保留（双层防御）；未注册参数丢弃。
- 未触及 SAP WRITE 路径、未改 redaction、未暴露 rfcName override。
- `.env` 未被触碰（LLM 配置在前序对话已就绪）。

## 分支处理

- 环境：normal repo（GIT_DIR == GIT_COMMON），当前分支 `main`。
- 用户选择：Option 3 - 保持现状（保留工作区，稍后处理）。
- `branch_status: handled`。

## 结论

验证通过（PASS）。可推进至 archive 阶段。归档时需：
1. 同步 delta spec 到 `openspec/specs/capability-registry-gateway/spec.md`。
2. 将 change 移至 `openspec/changes/archive/2026-07-09-flexible-intent-recognition/`。
3. 跟进项（PO fact builder 嵌套 items）建议作为独立 change 处理。
