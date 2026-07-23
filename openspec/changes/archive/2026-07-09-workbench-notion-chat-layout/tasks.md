## 1. 前端类型与状态模型

- [x] 1.1 在 `frontend/src/modules/agent-console/` 下新增 `chat-types.ts`，定义 `ChatTurn`（runId、query、snapshot、isRunning）与「当前查看轮」相关类型。
- [x] 1.2 在 `view-model.ts` 新增轻量派生 `summarizeTurn(turn)`（query 摘要 + state），供 Run History 使用；保持既有 `buildWorkbenchViewModel` 等导出行为不变。

## 2. 组件拆分与对话渲染

- [x] 2.1 新增 `ChatComposer.tsx`：底部固定输入框（受控 textarea + 发送按钮 + disabled 态），接收 `value` / `onChange` / `onSubmit` / `isRunning` props。
- [x] 2.2 新增 `ChatStream.tsx`：渲染 `ChatTurn[]` 消息流--每轮用户气泡（右）+ AI 气泡（左），AI 气泡内按 `buildWorkbenchViewModel(turn.snapshot)` 渲染 reasoning steps（增量）与 narrative（运行中占位光标，narrative 到达后正文）。
- [x] 2.3 在 `ChatStream` 的 AI 气泡下方实现折叠「查看过程证据」区（`<details>`，默认收起），展开后复用 `RuntimeTimeline` / `HumanApprovalPanel` / `TraceAuditPanel` / `ArtifactJson` + `view.detailGroups` 渲染该轮产物。
- [x] 2.4 重构 `AgentConsole.tsx`：移除 `copilot` aside；`stage` 改双态（`stage--home` 空态居中 / `stage--chat` 对话态）；管理 `ChatTurn[]` 与当前查看轮；`runAgent` 作用于当前 turn 的 snapshot；组合 `ChatStream` / `ChatComposer`。

## 3. 样式调整

- [x] 3.1 在 `frontend/app/globals.css` 移除 `.copilot*` 全部样式；`.workspace` 从三栏改两栏（`.side-nav` + `.stage`）。
- [x] 3.2 新增 `.stage--chat`（flex column）、`.chat-stream`（flex:1, overflow-y:auto）、`.chat-composer`（flex-shrink:0, 固定底部）样式；复用并保留 `.home-hero` / `.result-card` / `.panel` / `.timeline` / `.artifact-*` / `.detail-group` / `.reasoning-*` / `.bubble` 样式。
- [x] 3.3 新增 AI 气泡流式光标（纯 CSS `::after` 闪烁动画）与消息气泡淡入动画。
- [x] 3.4 更新移动端 `@media` 断点：移除原 `.copilot` 全宽降级逻辑，简化为单栏对话流适配。

## 4. Run History 与多轮切换

- [x] 4.1 `side-nav` 的 Run History 从 `ChatTurn[]` 派生（label = `summarizeTurn`，small = state），点击历史项切换当前查看轮（只读展示该轮消息与证据）。
- [x] 4.2 确认新查询始终追加新 turn（独立 run，不向后端传历史），底部 composer 在查看历史轮时仍发起新轮。

## 5. 测试

- [x] 5.1 新增 `tests/agent-console/chat-types.test.ts`（或 view-model 派生测试）：验证 `summarizeTurn` 行为；确认 `buildWorkbenchViewModel` 既有测试仍通过。
- [x] 5.2 新增对话布局测试：空态单输入框、对话态底部 composer、消息流多轮累积、AI 气泡流式占位与 narrative 切换、折叠证据区展开渲染 timeline/artifacts、Run History 切换查看轮。
- [x] 5.3 运行 `npm --prefix frontend run verify`（typecheck + vitest + build）通过。

## 6. 验证与归档准备

- [x] 6.1 运行 `openspec validate --all --strict` 通过。
- [x] 6.2 运行 `scripts/verify-agent-callplan-evidence.sh` 通过。
- [x] 6.3 更新 runbook / roadmap / wiki 进度（如有前端 UI 相关条目）。
