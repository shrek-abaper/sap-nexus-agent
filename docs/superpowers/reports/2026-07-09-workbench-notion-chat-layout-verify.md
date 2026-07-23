# Verification Report — workbench-notion-chat-layout

| Field | Value |
|---|---|
| Change | `workbench-notion-chat-layout` |
| Workflow | Comet tweak |
| Verify mode | full (delta spec present + 18 tasks > 3 threshold) |
| Date | 2026-07-09 |
| Language | zh-CN |
| Result | PASS |

## 变更概要

将 Workbench 前端从三栏布局（side-nav / stage / copilot）重构为 Notion 式两栏对话布局（side-nav / chat stage）：

- 空态：欢迎语 + 单输入框 + 快捷提问居中。
- 对话态：中间消息流（用户气泡右 / AI 气泡左流式增量）+ 底部固定 composer。
- AI 气泡：reasoning steps 逐个出现 + 流式光标占位 -> narrative 正文。
- 结构化产物（timeline / 人审 / trace / artifacts）折叠在 AI 回复气泡下方，默认收起。
- 多轮消息累积 + Run History 滚动定位切换；每轮独立 run，不向后端传历史。
- 后端 API、SSE 机制、run state machine、redaction、HITL 契约不变。

## 改动文件

修改：
- `frontend/app/globals.css`
- `frontend/src/modules/agent-console/AgentConsole.tsx`
- `frontend/src/modules/agent-console/view-model.ts`
- `docs/runbooks/03-agent-workbench-console.md`
- `docs/runbooks/README.md`

新增：
- `frontend/src/modules/agent-console/chat-types.ts`
- `frontend/src/modules/agent-console/ChatComposer.tsx`
- `frontend/src/modules/agent-console/ChatStream.tsx`
- `frontend/tests/agent-console/summarize-turn.test.ts`
- `frontend/tests/agent-console/chat-bubble-state.test.ts`
- `openspec/changes/workbench-notion-chat-layout/`（proposal/design/specs/tasks + .comet.yaml）

## 验证证据（fresh run，本报告生成前重新执行）

| # | 检查项 | 命令 | 结果 |
|---|---|---|---|
| 1 | tasks.md 全部完成 | `grep -c '\- \[ \]' tasks.md` | 18/18 `[x]`，0 未完成 |
| 2 | 实现符合 design.md 高层决策 | D1-D7 逐项核对 | PASS（两栏/双态/ChatTurn 模型/流式气泡/折叠证据/view-model 不变/组件拆分） |
| 3 | 实现符合 Design Doc | design.md 即设计文档（tweak 无独立 Superpowers Design Doc） | PASS |
| 4 | 能力规格场景全部通过 | delta spec ADDED/MODIFIED scenarios 对照实现 | PASS（纯函数测试 + 类型/build 兜底） |
| 5 | proposal.md 目标已满足 | Notion 两栏/空态/对话态/流式/折叠/多轮/Run History | PASS |
| 6 | delta spec 与 design doc 无矛盾 | MODIFIED timeline/artifacts/HITL 折叠呈现与 D5 一致；Run History scenario 已修正为 scroll-to-highlight | PASS |
| 7 | 关联设计文档可定位 | `openspec/changes/workbench-notion-chat-layout/design.md` 存在且相关 | PASS |

### 命令输出（exit code）

| 命令 | 退出码 | 关键输出 |
|---|---|---|
| `npm --prefix frontend run verify` | 0 | typecheck pass；22 tests pass（6 files）；`Compiled successfully` |
| `openspec validate --all --strict` | 0 | `7 passed, 0 failed` |
| `scripts/verify-agent-callplan-evidence.sh` | 0 | `109 passed, 1 skipped`；eval `7/7` + `13/13` |

### 前端测试明细

- `tests/runtime/redaction.test.ts` — 3 passed
- `tests/runtime/run-state-machine.test.ts` — 7 passed
- `tests/runtime/agent-runtime-adapter.test.ts` — 2 passed
- `tests/agent-console/view-model.test.ts` — 1 passed（既有，未被破坏）
- `tests/agent-console/summarize-turn.test.ts` — 5 passed（新增）
- `tests/agent-console/chat-bubble-state.test.ts` — 4 passed（新增）

合计 22 passed。

## 代码审查

`review_mode: off`，按 comet-verify 规则跳过自动 code review。跳过原因：tweak 轻量流程 + 用户未要求审查。正确性/安全/边界由 spec 场景纯函数测试 + typecheck + build 覆盖。

## 已知偏差与说明

1. **组件 DOM 渲染测试延后**：前端测试栈无 jsdom / testing-library 依赖，spec 的组件渲染场景（空态单输入框、对话态底部 composer、折叠证据展开等）由纯函数测试（`summarizeTurn`、`buildChatBubbleState`）覆盖核心逻辑，组件结构由 typecheck + build 兜底。引入 DOM 测试环境超出本 tweak 范围，列为后续可选改进。
2. **流式为事件粒度**：narrative 在 `narrative_created` 事件到达时一次性出现，视觉上非逐字；通过 reasoning steps 逐个出现 + 运行中光标占位弥补「流式感」。属 design D4 已声明的设计取舍。
3. **多轮无后端上下文**：每轮独立 POST，前端仅累积展示，不向后端传历史；composer hint 已提示。属 Non-Goal 已声明。
4. **代码未提交**：按用户明确选择「暂不提交，保留工作区」，改动留在 main 分支工作区。分支处理 = 保持现状（Option 3）。

## 安全检查

- 无硬编码密钥 / token / 凭据 / 连接串。
- 未引入新依赖（继续 Next.js 15 + React 19）。
- 未触及 SAP WRITE 路径、未暴露 `rfcName` override、未改 redaction。
- `.env` 未被触碰。

## 分支处理

- 环境：normal repo（GIT_DIR == GIT_COMMON），当前分支 `main`。
- 用户选择：Option 3 — 保持现状（保留工作区，稍后处理）。
- `branch_status: handled`。

## 结论

验证通过（PASS）。可推进至 archive 阶段。归档时需：
1. 同步 delta spec 到 `openspec/specs/agent-workbench-console/spec.md`。
2. 将 change 移至 `openspec/changes/archive/2026-07-09-workbench-notion-chat-layout/`。
3. 在 roadmap 补归档条目（带 archive path + 验证证据）。
