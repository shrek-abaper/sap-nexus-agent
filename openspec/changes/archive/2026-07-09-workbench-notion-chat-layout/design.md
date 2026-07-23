## Context

当前 Workbench 控制台（`frontend/src/modules/agent-console/AgentConsole.tsx` + `frontend/app/globals.css`）为三栏布局：

- 左 `side-nav`（240px）：导航 + Run History + 用户信息。
- 中 `stage`：空态为 `home-hero`（居中欢迎语 + hero 输入框 + 快捷提问）；运行态为 `result-stack`（结果卡片 + timeline + 人审 + trace + detail groups）。
- 右 `copilot`（340px）：AI Copilot reasoning trace + AI 结论气泡 + 第二个输入框。

后端已具备 SSE 流式：`runAgent()` 通过 `EventSource` 订阅 `/api/agent-runs/[runId]/stream`，`applyRunEvent` 增量更新 `AgentRunSnapshot`，`buildWorkbenchViewModel` 派生 `result` / `reasoningSteps` / `detailGroups` / `artifacts`。现有测试 `tests/agent-console/view-model.test.ts` 仅覆盖 `view-model.ts` 纯函数，不涉及布局。

目标：重构为 Notion AI 式两栏对话布局。底层行为契约（SSE 提交、状态机、timeline、redaction、HITL、本地验证）与后端 API 不变，仅调整前端呈现与组织方式。

## Goals / Non-Goals

**Goals:**
- 左侧菜单保留，中间区域改为单栏对话视图，移除右侧 `copilot` 侧栏。
- 空态：欢迎语 + 单个输入框 + 快捷提问居中。
- 对话态：中间顶部为消息流（用户气泡靠右、AI 气泡靠左流式增量渲染），底部为固定输入框（composer）。
- 结构化工作台产物（timeline / 人审 / trace / detail artifacts）折叠在对应 AI 回复气泡下方，默认收起，展开后复用现有组件。
- 前端多轮消息累积：消息流保留多轮历史，左侧 Run History 项与历史对话对应并可切换。
- 复用现有 SSE 机制与 `view-model` 派生，不改后端。
- 保持 `view-model.ts` 纯函数行为不变，现有 `view-model.test.ts` 继续通过。

**Non-Goals:**
- 不改后端 API、Agent Runtime Adapter、redaction、run-state-machine。
- 不引入新依赖（继续 Next.js 15 + React 19）。
- 不实现真正的多轮上下文传递（每次 run 仍独立 POST，前端仅累积展示历史消息，不向后端传历史）。
- 不改 dark mode / 国际化 / 响应式断点策略（保持现有移动端降级思路，按需微调）。
- 不改 `side-nav` 导航项与结构。

## Decisions

### D1: 两栏布局，移除 copilot 侧栏

保留 `.app-shell`（flex column, 100vh）+ `.topbar`。`.workspace` 从三栏改两栏：`.side-nav`（240px）+ `.stage`（flex:1）。删除 `.copilot` 及其全部子样式。对话消息流与 AI 回复合并进 `.stage`。

**为何不移除 side-nav**：Notion 式保留左侧菜单，符合用户明确要求「左侧是菜单栏」。

### D2: stage 双态切换 - 空态居中 vs 对话态消息流+底部 composer

- 空态（无任何 run）：`stage--home`，居中渲染 `.home-hero`（欢迎语 + 输入框 + 快捷提问），复用现有样式与 `fade-up` 动画。
- 对话态（≥1 轮 run）：`stage--chat`，`flex column`：顶部 `.chat-stream`（flex:1, overflow-y:auto）渲染消息流；底部 `.chat-composer`（flex-shrink:0）固定输入框。首次提交时输入框从居中 hero 平滑过渡到底部 composer（通过状态切换 + CSS 动画，不要求复杂位移动画，状态切换即可）。

**为何不保留 hero 输入框**：用户明确要求「输入对话后，对话框位于下方」，故对话态只保留底部 composer，避免两处输入。

### D3: 多轮消息状态模型

新增前端状态：`ChatTurn[]`，每个 turn = 一轮 run 的消息组：

```
type ChatTurn = {
  runId: string;
  query: string;          // 用户气泡内容
  snapshot: AgentRunSnapshot | null;  // 该轮 run 的快照，驱动 AI 气泡与折叠证据
  isRunning: boolean;
};
```

- 当前轮：`turns[turns.length-1]`，其 snapshot 实时由 SSE 更新。
- Run History 项：从 `turns` 派生（label 取 query 摘要，small 取 state）；点击历史项切换「当前查看轮」（只读展示该轮 snapshot 派生的消息，底部 composer 仍用于发起新轮）。
- 新发查询：`turns.push(newTurn)`，复用 `runAgent` 逻辑但作用于当前 turn 的 snapshot。

**为何 turn 内嵌 snapshot 而非单独存 events**：复用 `buildWorkbenchViewModel(snapshot)` 直接派生该轮的 result/reasoning/artifacts，零改动 view-model。

### D4: AI 气泡流式渲染

AI 气泡分两部分，均由当前 turn 的 `view`（`buildWorkbenchViewModel(turn.snapshot)`）驱动，随 SSE 增量更新自然「流式」出现（无需逐字定时器）：

1. **reasoning steps**：`view.reasoningSteps` 逐个渲染，新事件到达即新增一行（复用 `.reasoning-card` / `.reasoning-step` 样式，标记 current/done/failed）。
2. **narrative 结论**：`view.result.body`（来自 narrative artifact）。运行中时显示「正在推理…」占位 + 流式光标；narrative 到达后显示正文。光标用纯 CSS `::after` 闪烁动画。

**为何用增量出现而非逐字 typewriter**：现有 SSE 是事件粒度（非字符流），逐字模拟需额外定时器且与真实数据脱节；增量出现更贴合事件语义、实现简单、无新状态。若后续后端支持 narrative 分片事件，可平滑升级。

### D5: 产物折叠在 AI 回复下方

AI 气泡下方放一个 `<details>`「查看过程证据」（默认 `open=false`），展开后渲染该轮的：Runtime Timeline、Human Approval、Trace Audit、详细产物 groups（复用现有 `RuntimeTimeline` / `HumanApprovalPanel` / `TraceAuditPanel` / `ArtifactJson` + `view.detailGroups`）。

**为何折叠而非常驻**：用户选择「折叠在 AI 回复下方」。Notion 风格以对话回复为主、证据可追溯，折叠降低视觉噪声，同时保留工作台的全部过程证据能力（满足现有 spec 的 timeline/artifacts 需求）。

### D6: view-model 保持不变

`view-model.ts` 纯函数行为不变，现有测试继续通过。对话渲染层在其之上消费 `view.result` / `view.reasoningSteps` / `view.detailGroups` / `view.artifacts`。如需「每轮摘要」可新增轻量派生函数（如 `summarizeTurn`），不修改既有导出。

### D7: 组件拆分

在 `frontend/src/modules/agent-console/` 下新增：
- `ChatStream.tsx`：渲染 `ChatTurn[]` 消息流（用户气泡 + AI 气泡 + 折叠证据）。
- `ChatComposer.tsx`：底部固定输入框（textarea + 发送按钮），受控。
- `AgentConsole.tsx`：编排 `side-nav` + `stage`（双态）+ 多轮状态 + `runAgent`，组合 `ChatStream` / `ChatComposer`。

**为何拆分**：`AgentConsole` 当前单文件 280 行已含三栏逻辑，重构后多轮状态与消息流复杂度上升，拆分便于维护与测试，符合既有模块化目录约定（`src/modules/*`）。

## Risks / Trade-offs

- **[多轮消息无后端上下文]** -> 前端仅累积展示，每次 run 独立 POST 不带历史；在 composer placeholder 或帮助文案中说明「每轮独立查询」，避免用户误以为 Agent 记住上下文。属预期行为，Non-Goal 已声明。
- **[流式为事件粒度非字符流]** -> narrative 在 `narrative_created` 事件到达时一次性出现，视觉上非逐字。通过 reasoning steps 逐个出现 + 运行中占位光标弥补「流式感」。后续可平滑升级为分片事件。
- **[Run History 切换只读历史轮]** -> 切换到历史轮时底部 composer 仍发起新轮（追加），不「继续」历史轮对话。符合每次独立 run 的后端模型。
- **[CSS 重构范围]** -> 移除 `.copilot*` 并新增 `.chat-*` 类，需同步更新移动端 `@media` 断点（原 `.copilot` 在 ≤960px 转底部全宽，重构后对话流本身即单栏，断点逻辑简化）。注意保留 `.side-nav`、`.home-hero`、`.result-card`、`.panel`、`.timeline`、`.artifact-*`、`.detail-group` 等仍被复用的样式。
- **[view-model 测试兼容]** -> D6 保证纯函数不变；新增的对话状态/组件测试独立编写，不触碰既有测试。
- **[未提交改动协议]** -> 按 tweak build 阶段的 `dirty-worktree` 协议处理；本 change 改动均在前端 workspace 内。

## Migration Plan

纯前端重构，无数据迁移、无后端部署：

1. 实现 D7 组件拆分 + D2/D3/D4/D5 渲染逻辑 + CSS 调整。
2. 新增对话布局测试（消息流渲染、空态/对话态切换、流式占位、折叠证据、多轮累积、Run History 切换）。
3. `npm run verify`（typecheck + vitest + build）通过。
4. `openspec validate --all --strict` + `scripts/verify-agent-callplan-evidence.sh` 通过。
5. 归档 change。

**回滚**：`git revert` 前端改动即可，无副作用。

## Open Questions

无。两个关键分叉点（产物折叠 vs 独立面板 vs 仅文字；多轮 vs 单轮）已由用户确认：折叠在 AI 回复下方 + 前端累积多轮。
