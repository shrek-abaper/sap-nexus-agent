# DSH Message Actions Specification

## Purpose

为 /chat 对话界面提供 DSH 原生的消息级操作（对齐 ontology-dsh
`ui-conversation` 的 MessageIconActions / TurnTailNodeView 与
`ui-message-feedback` 包）：助手消息 turn-tail 行动作行（复制原始
markdown、时钟/耗时、赞/踩 + 备注、branch 分叉）与用户消息复制。
复制语义、可见性规则与 fork 机制均对齐 DSH；分享/导出、消息编辑/
删除/重试不在范围内（DSH 原生亦无）。

## Requirements

### Requirement: Assistant turn-tail action row

每条 settled 的助手消息 SHALL 在内容下方显示 turn-tail 行动作行：
copy / feedback（赞/踩）/ branch 图标按钮常驻；时钟（消息 ts）与
耗时（runMs，秒级）仅在 hover 或 focus-within 时显示；无 hover 设备
常显。流式中或 pending 消息不显示动作行。

- **WHEN** 助手消息处于 pending/streaming
  - **THEN** 不渲染 turn-tail 动作行
- **WHEN** 用户点击 copy
  - **THEN** 剪贴板写入该消息的原始 markdown 源码（助手=text 原文，
    不含工具卡、不含思考 trace），图标变为 ✓ 约 1 秒后恢复
- **WHEN** 复制不可用（clipboard API 失败）
  - **THEN** 静默降级（图标恢复，无错误弹窗）

### Requirement: User message copy and clock

每条用户消息 SHALL 提供 copy 与时钟，仅在 hover/focus-within 时显示。

- **WHEN** 用户点击用户消息的 copy
  - **THEN** 剪贴板写入原始输入文本（与发送内容逐字一致）

### Requirement: Message feedback with note

助手消息 SHALL 支持赞/踩反馈与可选备注：

- rating 为 toggle 语义：点相反的 rating 切换，再点当前 rating 撤回；
- 备注为可展开编辑器（textarea + 保存/取消），保存空备注等于清除
  备注保留评分；
- 反馈持久化到服务端 conversation-store（append-only JSONL 的新
  `kind: "feedback"` 记录，键为 conversationId + messageId），重新
  加载会话或刷新页面后仍然可见；
- 历史向后兼容：旧 JSONL 记录无 feedback kind 时读取不受影响；
  `list()` 的 messageCount MUST 只统计 `kind === "message"` 的记录。

- **WHEN** 用户对一条助手消息点赞
  - **THEN** 图标呈现激活态，重开该会话后仍激活
- **WHEN** 用户再次点击同一 rating
  - **THEN** 反馈被撤回，图标恢复未激活
- **WHEN** 保存一条备注后重新打开会话
  - **THEN** 该消息的赞/踩状态与备注文本均回显

### Requirement: Branch (fork) at a completed turn

每条 settled 助手消息 SHALL 提供 branch 按钮。点击后客户端调用
`POST /api/dsh/conversations/[id]/fork`（body: throughMessageId），
服务端 MUST：

1. 从父 AgentSession 的 `snapshotEvents()` 截取到第 N 个 `turn/end`
   的 balanced completed-turn prefix（N = throughMessageId 之前（含）
   的完整轮次数）；
2. 以新 sessionId 调用 `agents.create`，meta 含 `parentSession` 与
   `isSeeded: true`，`inheritedEventCount` = 前缀长度，`seed` = 前缀；
3. 在 conversation-store 写入新会话 header 与前 N 轮消息副本
   （message id 保留原值，feedback 不复制）；
4. 返回新 conversationId，客户端把新会话加入列表并切换。

父 AgentSession 不在内存（如服务器重启后的历史会话）时 MUST 返回
明确错误（409 或等价），客户端在动作行就地提示"父会话不在内存，
无法分叉"，不产生半成品会话。

- **WHEN** 用户在第 N 轮助手消息点击 branch
  - **THEN** 出现含前 N 轮历史的新会话并自动切换；继续提问时模型
    上下文包含该前缀（fork seed 生效）
- **WHEN** fork 的父会话不在内存
  - **THEN** 返回明确错误且无新会话写入

### Requirement: Data plumbing for timestamps

`ChatMessage` SHALL 支持可选 `ts` 与 `runMs`：发送时记录 `ts`，
final 事件到达时以时间差写入 `runMs`；历史回放保留服务端 `ts`
（不再剥离）。视觉沿用三层 token；图标常驻、时钟/耗时 hover
reveal；动画遵守 prefers-reduced-motion；不引入新依赖。

- **WHEN** 一轮回答完成
  - **THEN** turn-tail 时钟显示消息时间、hover 标签显示耗时（秒）
