# Verification Report - llm-grounded-narration

| Field | Value |
|---|---|
| Change | `llm-grounded-narration` |
| Workflow | Comet full |
| Verify mode | full (15 tasks > 3, 1 delta capability) |
| Date | 2026-07-09 |
| Language | zh-CN |
| Result | PASS |

## 变更概要

narrator 从纯模板拼接重构为 LLM grounded 柔性叙事 + 模板 fallback：

- `llm_client.py` 加 `chat_text`（纯文本，复用 chat_json 错误处理，LlmUnavailable 自吞已修）。
- `narrator.py`：LLM 主路径（`chat_text` + grounding prompt + `redact_sensitive`）+ 模板 fallback（`_template_inventory`/`_template_po` 提取）；`narration_guidance` 按 businessObject 派生指引（InventoryStock/PurchaseOrder/通用）；`_SYSTEM_CONSTRAINT` 严格约束不编造；PO evidence 前置 guard（LLM up/down 行为确定一致）。
- `orchestrator.py` 显式传 capability_id（最小）。
- `conftest.py` autouse fixture 隔离真实 LLM（防 .env 污染单元测试）。

不改 fact builder / registry schema / OData service / 前端 / 意图识别。

## 改动文件

修改：
- `agent/sap_nexus_agent/llm_client.py`（chat_text）
- `agent/sap_nexus_agent/narrator.py`（LLM 主路径 + 指引 + prompt builder + 模板提取 + PO guard）
- `agent/sap_nexus_agent/orchestrator.py`（传 capability_id）
- `agent/tests/test_reasoning_narrator.py`（LLM/fallback/防幻觉/redact/PO guard 测试）
- `agent/tests/test_orchestrator.py`（orchestrator LLM 集成测试）

新增：
- `agent/tests/conftest.py`（LLM 隔离 fixture）

## 验证证据（fresh run）

| # | 检查项 | 结果 |
|---|---|---|
| 1 | tasks.md 全部完成 | 15/15 PASS |
| 2 | 实现符合 design.md D1-D5 | PASS（LLM 主路径+fallback/guidance 派生/chat_text/orchestrator 传 capability/空结果模板） |
| 3 | delta spec 场景覆盖 | PASS（inventory/PO/新能力/fallback/空结果 5 ADDED + 2 MODIFIED） |
| 4 | proposal 目标满足 | PASS（LLM 叙事 + 柔性架构 + 防幻觉） |
| 5 | delta 与 design 无矛盾 | PASS |
| 6 | design doc 可定位 | PASS |
| 7 | 端到端 | LLM 叙事路径由 orchestrator 集成测试覆盖（fake gateway + fake LLM 全链路） |

### 命令输出

| 命令 | 退出码 | 关键输出 |
|---|---|---|
| `pytest agent/tests -q` | 0 | `155 passed, 1 skipped` |
| `eval evals/inventory_availability_cases.yaml` | 0 | `Eval passed: 7/7` |
| `eval evals/purchase_order_cases.json` | 0 | `Eval passed: 3/3` |
| `openspec validate --all --strict` | 0 | `7 passed, 0 failed` |
| `verify-agent-callplan-evidence.sh` | 0 | `155 passed, 1 skipped`；eval 7/7 + 13/13；openspec 7/7 |

## 代码审查（review_mode: standard，build 阶段完成）

reviewer 结论：With fixes。处理：

- **Important #1（已修复）**：PO LLM 路径跳过 evidence 完整性 guard（与 inventory 不对称，LLM up/down 行为非确定）。已加 `_assert_po_evidence_complete` 前置 guard，LLM up/down 行为一致；新增 2 个确定性测试（`test_narrate_po_facts_incomplete_evidence_raises_guard_with_llm_available/unavailable`）。
- **Minor #2（已修复）**：`chat_text` 空 content 的 `LlmUnavailable` 被通用 except 吞掉。已加 `except LlmUnavailable: raise` + 空 content 检查移出 try。
- **Minor #3（跳过）**：测试文件 mid-file import（cosmetic，不影响功能）。

## 端到端确认

LLM 叙事路径由 Task 7 orchestrator 集成测试覆盖（fake gateway + fake LLM 全链路：inventory LLM 叙事、PO LLM 叙事、fallback 全 PASS）。CLI 端到端需 gateway 运行，本次验证时 gateway 未启动；集成测试已证明 LLM 叙事路径正确（LLM 主路径生成自然语言 + fallback 模板 + 防幻觉约束 + redact）。

## 已知偏差

- 端到端 CLI 需 gateway 运行（本次未启动），LLM 叙事路径由集成测试覆盖。
- 代码未提交：按用户「保持现状」选择，改动留在 main 工作区。

## 安全检查

- 无硬编码密钥 / token / 凭据。
- 未引入新依赖。
- 防幻觉：_SYSTEM_CONSTRAINT prompt 约束 + redact_sensitive 过滤 + fallback 模板兜底 + PO evidence 前置 guard。
- 未触及 SAP WRITE 路径、未改 redaction 机制、未改意图识别。

## 分支处理

- 环境：normal repo，当前分支 `main`。
- 用户选择：保持现状（保留工作区，稍后处理）。
- `branch_status: handled`。

## 结论

验证通过（PASS）。可推进至 archive 阶段。
