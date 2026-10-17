# Outcome

让 /chat 对话界面具备 DSH 原生的消息级操作（对齐 ontology-dsh
`ui-conversation` 的 MessageIconActions / TurnTailNodeView 与
`ui-message-feedback`）：

- 助手消息 turn-tail 行动作行：复制（原始 markdown 源码）、时钟与耗时
  （hover 显示）、赞/踩 + 备注、branch 分叉；
- 用户消息：复制 + 时钟（hover 显示）；
- 复制内容对齐 DSH 语义：助手=text 块原始 markdown（不含工具卡/思考
  trace），用户=原始输入文本。

# Scope

- 前端 UI：`DshChat.tsx`、新增 `MessageActions.tsx`（dsh-chat 模块）、
  `types.ts`（ChatMessage 增加 ts/runMs/feedback）、globals.css 增加
  `.msg-actions` 样式（沿用统一 token 与 hover-reveal 惯例）
- 服务端：`conversation-store.ts`（feedback 记录类型 + fork 复制）、
  dsh runtime（forkSession：父 session snapshotEvents 截取到第 N 个
  turn/end 作为 seed，agents.create 带 parentSession/isSeeded/
  inheritedEventCount）、API 路由：
  - `POST /api/dsh/conversations/[id]/feedback`（messageId、rating、note）
  - `POST /api/dsh/conversations/[id]/fork`（throughMessageId）
  - `GET /api/dsh/conversations/[id]` 返回消息合并 feedback
- 测试：store/路由/fork 截取逻辑的 vitest

# Non-goals

- 分享/导出会话（DSH 原生也没有）
- TTFT / tokens-per-second 统计（当前 SSE 无数据源）
- 消息级编辑/删除/重试（DSH 原生只在待发队列提供）
- feedback 的跨会话聚合分析或上报
- 服务器重启后历史会话的 fork（父 session 不在内存，按钮给出不可用
  提示；durable agent memory 是独立升级）

# Acceptance examples

- 助手消息 settle 后显示 turn-tail：copy/赞/踩/branch 图标常驻，时钟与
  耗时 hover 才显示；复制得到原始 markdown 源码（不含工具卡与思考
  trace），成功图标变 ✓ 一秒
- 用户消息 hover 显示 copy + 时钟；复制为原始输入文本
- 赞/踩可 toggle（再点撤回）、可附备注并保存；刷新页面或重开会话后
  反馈仍在
- branch 在第 N 轮助手消息点击后：新会话含前 N 轮历史并自动切换；
  继续提问时模型上下文包含前缀（dsh fork seed 生效）；父会话不在
  内存时给出明确不可用错误
- 既有流式、审批、工具卡行为零回归（npm run verify 全绿）

# Constraints and invariants

- 复制文本来自消息原文（projection），不做 DOM 提取
- feedback 记录为 append-only JSONL 新 kind，旧记录向后兼容；list()
  的 messageCount 只统计 kind === "message"
- fork seed 必须是 balanced completed-turn prefix（截取到 turn/end），
  由 dsh session 边界校验；失败即返回错误，不写半成品会话
- 视觉沿用三层 token；图标按钮常驻、时钟/耗时 hover reveal、
  动画遵守 prefers-reduced-motion
- 不引入新依赖

# Decisions

- 用户指示（2026-10-17）："不用一直询问，按照目标完成 DSH 原生支持
  的这几项实施"——目标即上一轮探讨确认的 DSH 原生项：复制/反馈/
  branch；按此共享理解直接推进，不再逐项确认。
- feedback 持久化在 conversation-store（服务端 JSONL），与既有会话
  历史同生命周期；不做 localStorage 版
- branch 采用 dsh 原生 fork（seed + isSeeded），而非客户端复制消息
  的假分叉——保证模型上下文连续
- 运行统计只展示时钟与耗时（runMs 由 send 时间戳与 final 事件差值
  得出）；TTFT/tok-s 无数据源，不做

# Open questions

（无；用户已给定免确认授权，范围即 DSH 原生项）

# Verification expectations

- `npm --prefix frontend run verify` 全绿（typecheck + vitest + build）
- 新增 vitest：feedback store 读写与 toggle/clearNote、list() 不计
  feedback 记录、fork 前缀截取（turn/end 边界）、feedback/fork 路由
- 目视核对 /chat：动作行显示、复制 ✓、赞踩状态、branch 分叉切换
