## Why

当前 Workbench 控制台是三栏式（左侧导航 / 中间 stage / 右侧 copilot 对话），输入框分散在 hero 与 copilot 两处，对话与结构化产物分离，不符合 Notion AI 式的「中间单栏对话 + 底部输入 + 流式回复」交互范式。需要重构为 Notion 风格两栏布局：左侧菜单保留，中间区域为对话流（空态时欢迎语与输入框居中，发起对话后输入框下移到底部固定，Agent 反馈按对话气泡流式渲染到中间），降低认知负担并统一输入入口。

## What Changes

- **BREAKING**（仅前端布局语义）: 移除右侧 `copilot` 侧栏，将对话消息流与 AI 回复合并到中间 `stage` 区域，形成单栏对话视图。
- 空态：中间区域居中展示欢迎语、单个输入框、快捷提问；输入框为唯一对话入口。
- 对话态：中间区域顶部为消息流（用户气泡靠右、AI 气泡靠左并流式增量渲染），底部为固定输入框（composer），输入框在发起对话后从居中位置过渡到底部固定。
- AI 回复气泡内流式渲染：reasoning steps 逐个出现，最终 narrative 中文结论逐字/逐段流式呈现，复用现有 SSE 事件流机制（`EventSource` + `applyRunEvent`），不修改后端 API。
- 原结构化工作台产物（Runtime Timeline / 人审状态 / Trace / 详细产物 JSON）改为**折叠**在对应 AI 回复气泡下方（「查看过程证据」区，默认收起，展开后复用现有 `RuntimeTimeline` / `HumanApprovalPanel` / `TraceAuditPanel` / `ArtifactJson` 组件）。
- 支持前端多轮消息累积：消息流保留多轮历史消息；左侧 Run History 项与历史对话对应，点击可切换查看不同 run 的对话。
- 左侧导航（`side-nav`）保留，结构不变。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `agent-workbench-console`: 前端控制台从三栏工作台改为 Notion 风格两栏对话布局——空态居中输入、对话态底部固定输入 + 中间流式消息流、结构化产物折叠于 AI 回复气泡下方、支持多轮历史消息累积与 Run History 切换。底层行为契约（SSE 提交、状态机、timeline、redaction、HITL、本地验证）不变，仅调整其呈现与组织方式。

## Impact

- 前端代码：
  - `frontend/src/modules/agent-console/AgentConsole.tsx` - 移除 `copilot` aside，重构 `stage` 为对话布局，输入框统一为底部 composer，新增多轮消息状态管理。
  - `frontend/app/globals.css` - 移除三栏布局样式，新增 chat 消息流、底部 composer、流式光标、AI 气泡内折叠证据区样式。
  - 可能新增 `frontend/src/modules/agent-console/` 下的 `ChatStream.tsx` / `ChatComposer.tsx` 等子组件以拆分消息流与输入框（视实现而定）。
  - `view-model.ts` - 基本复用，可能微调以适配对话气泡渲染（如每轮 run 一个消息组）。
- 后端 API：无改动，复用 `/api/agent-runs` 与 `/api/agent-runs/[runId]/stream`。
- 依赖：无新增（继续使用 Next.js 15 + React 19）。
- 测试：新增/更新前端对话布局相关测试（消息流渲染、流式输出、折叠证据区、多轮累积、Run History 切换），保持 `npm run verify` 通过。
- 验证：`openspec validate --all --strict` 与 `scripts/verify-agent-callplan-evidence.sh` 仍需通过。
