# Brainstorm Summary

- Change: sap-nexus-agent-workbench-console
- Date: 2026-06-20

## 确认的技术方案

采用 Next.js App Router + React + TypeScript 的本地优先内部 Agent Workbench Console。前端按 Modular Monolith 拆分 `frontend/src/modules/*` 和 `frontend/src/runtime/*`，通过 Agent Runtime Adapter 启动和观察现有 read-only Python Agent 链路，使用 SSE 输出有序 `AgentRunEvent`，并以 deterministic fake/local adapter 支撑无 SAP/LLM credentials 的测试。

核心边界：

- UI 只提交 natural language query，不接触 Java Gateway URL、SAP destination、raw RFC、`.env` 或 LLM key。
- `Agent Runtime Adapter` 负责 run 创建、event 生成、artifact normalization 和 redaction。
- `POST /api/agent-runs` 创建 run，`GET /api/agent-runs/[runId]/stream` 输出 SSE event stream。
- HITL 只做状态骨架：read-only `MM.Inventory.GetAvailability` 显示 `approval_not_required`，预留未来 approval states，但不执行写入。

## 关键取舍与风险

- SSE 优先而非 WebSocket，匹配第一版单向观察 Agent run timeline 的需求；WebSocket 留到未来双向审批、取消、多轮输入或协作。
- Adapter 先封装 Python Agent/假运行事件，不新增生产 Agent 服务，避免重复实现 CallPlan/Gateway/JCo 链路。
- Next.js API routes 可能模糊 frontend/backend 边界；缓解方式是在 `agent-runtime-adapter.ts` 中集中执行边界和 redaction，并禁止 UI/Gateway 直连。
- Artifact panels 可能泄漏敏感信息；缓解方式是在 adapter 边界统一 redaction，并对 password/token/destination/raw LLM patterns 写测试。
- Workbench 容易范围膨胀到审批、Recommendation 或 Write Action；本 change 只保留 HITL 状态骨架，不做真实审批和写 SAP。

## 测试策略

使用 TypeScript unit tests 覆盖 `AgentRunEvent` contract、run state machine、HITL states、redaction guard 和 fake adapter event order。Frontend verification 至少包含 typecheck/build 或项目可用的最小 Next.js 验证命令。回归门禁保留 `scripts/verify-agent-callplan-evidence.sh` 与 `openspec validate --all --strict`。

所有测试默认不依赖 SAP credentials、LLM credentials、raw live LLM responses 或 generated runtime traces。

## Spec Patch

无。当前未发现必须回写 delta spec 的缺口；现有 `agent-workbench-console` spec 已覆盖 run submission、SSE、timeline、artifact panels、redaction、HITL skeleton 与 verification。
