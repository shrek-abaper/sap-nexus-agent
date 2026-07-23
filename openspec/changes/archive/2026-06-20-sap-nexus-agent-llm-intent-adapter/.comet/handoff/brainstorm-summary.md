# Brainstorm Summary

- Change: sap-nexus-agent-llm-intent-adapter
- Date: 2026-06-20

## 确认的技术方案

用户确认采用 `hybrid` 默认模式：Agent 优先调用真实 OpenAI-compatible LLM intent adapter；当 LLM 配置缺失、网络失败、超时、返回 malformed JSON 或输出不可信时，自动降级到现有规则解析。LLM 配置沿用参考项目 `cbu-brain-agent/.env` 的变量形状：`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL_NAME`、`LLM_MAX_RETRIES`、`LLM_TIMEOUT_INTENT`。真实密钥只允许在本地 `.env` 或进程环境中存在，不提交、不打印。

## 关键取舍与风险

- LLM 只做意图理解和参数抽取候选，不执行 SAP、不生成 `rfcName`、不计算库存数量。
- LLM 输出必须经过确定性 guard：只允许 `MM.Inventory.GetAvailability`，缺 `material` 或 `plant` 必须澄清，任何 `rfcName` 或未知 capability 都不能驱动 Gateway 调用。
- 新增 `openai` 与 `python-dotenv` 依赖，用户已确认允许。
- 正常测试不依赖真实模型网络；live smoke 必须显式开启，避免 CI 和本地无 key 场景失败。

## 测试策略

- TDD：先写 fake LLM tests，确认当前代码因缺少 LLM adapter / intent mode 失败，再实现最小代码。
- 单元测试覆盖 LLM happy path、缺参澄清、hybrid fallback、malformed JSON、unknown capability、`rfcName` guard。
- 现有 `scripts/verify-agent-callplan-evidence.sh` 必须继续通过。
- 可选 live test 使用 `SAP_NEXUS_LLM_LIVE=1` gating，并只断言结构化输出，不打印密钥或完整模型响应。

## Spec Patch

已在 `openspec/changes/sap-nexus-agent-llm-intent-adapter/specs/agent-callplan-evidence/spec.md` 修改 `agent-callplan-evidence`：增加 LLM-assisted intent parsing、hybrid fallback、closed-set selection guard、missing parameter clarification 和 gated live smoke 需求。
