# DSH Workbench Runtime Specification

## Purpose

Workbench 的对话运行时唯一由 in-process DeepSeek Harness 承担：Next 服务端持有
dsh core（真实模型 function-calling 选择语义工具），浏览器使用新建的 dsh 对话
视图。harness 不做编排/治理/执行；每个工具调用进入服务端受治理的语义工具层。

## Requirements

### Requirement: Single in-process dsh runtime in the Next server

系统 SHALL 在 Next 服务端以模块级 `globalThis` 单例持有一个 dsh Cordis Context
（dev HMR 复用、不重复创建 agent/凭证），复用 harness-dsh 已 pin 的
spine/runner（0.1.5-rc.1），禁止把 dsh 包打进浏览器 bundle。

- **WHEN** Next dev server 因 HMR 重载模块
  - **THEN** 已存在的 dsh Context/会话被复用，不产生第二个 Context 或凭证泄漏
- **WHEN** 浏览器加载任意页面
  - **THEN** 客户端 bundle 不含 `@deepseek-ai/*` 包（server-only 边界）
- **WHEN** 服务端启动且未配置模型凭证
  - **THEN** READ/WRITE 工具与对话仍可装配，真实模型调用以明确错误失败
    （fail-closed），不回退到编造数据

### Requirement: Real DeepSeek model via server-side credentials

dsh LLM adapter SHALL 使用服务端环境变量配置的 OpenAI-compatible/DeepSeek
function-calling 模型；密钥永不下发浏览器、不写入配置文件、不入日志。

- **WHEN** 发起一次 dsh 对话
  - **THEN** 模型 provider/baseURL/model/apiKey 全部来自服务端 env，浏览器请求不含密钥
- **WHEN** 工具被模型选中
  - **THEN** 该工具是受治理语义工具之一，模型不能直接提供 RFC/URL/凭证

### Requirement: Conversation lifecycle API

系统 SHALL 提供 dsh 会话的 HTTP API：创建/继续会话、发送消息、读取助手输出与
工具调用过程；每会话对应一个 dsh agent（可复用 sessionId）。

- **WHEN** 客户端 POST 一条用户消息
  - **THEN** 服务端在对应 dsh agent 上 followup 并等待 whenIdle，返回最终助手文本与结构化工具结果
- **WHEN** 同一 conversationId 连续发送两条消息
  - **THEN** 第二次能看到第一次的上下文（dsh session 记忆生效）

### Requirement: WRITE approval is server-adjudicated

dsh 不裁决审批。propose_replenishment 工具 SHALL 在服务端生成 proposal 后返回
`awaiting_approval` 与审批句柄；UI 据此渲染卡片；人类决定只经服务端审批路由。

- **WHEN** 补货建议满足 recommendation 规则
  - **THEN** 工具结果含 approvalId/runId/expiresAt 与 6 个 PR 参数，
    且本轮不发生任何 SAP 写
- **WHEN** 用户在卡片上批准
  - **THEN** 浏览器 POST 既有 `/api/agent-runs/[runId]/approval`
    `{approvalId, decision:"approve"}`，随后网关 approve+execute 由服务端后台完成
- **WHEN** 用户拒绝或审批过期
  - **THEN** 不产生写，dsh 在下一轮向用户陈述拒绝/过期，不编造 PR 号

### Requirement: Model capability gate stays enforced

接入 Workbench 不降低模型能力门槛；自动化测试用 MockAdapter，真实模型 smoke 手动。

- **WHEN** 运行自动化测试
  - **THEN** 不访问 api.deepseek.com、不需要 key（MockAdapter 脚本驱动）
- **WHEN** 真实模型 function-calling 错误选择工具或参数
  - **THEN** 服务端契约/治理 fail-closed，错误可呈现，不产生越权调用
