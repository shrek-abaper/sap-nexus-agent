# Outcome

让 sap-nexus-agent 前端在视觉语言与 AI 交互范式上对齐 ontology-dsh
（DeepSeek Harness web client，`packages/client/ui-*`）：

- 引入 dsh 的三层 design token 体系（static / alias / specific 语义层，
  `--dsw-*` 风格的 CSS 自定义属性），替代当前 globals.css 中三套并存的
  临时色板（workbench 墨蓝体系 A、chat 手工复刻的 DSH 蓝体系 B、
  plan-evidence 衬线残留体系 C）。
- AI 交互范式对齐 dsh：用户消息右对齐淡蓝气泡；助手消息去气泡、整宽
  markdown；思考过程/工具调用等过程性内容统一收敛为单行 disclosure row
  （默认折叠、点击展开成卡片）；运行状态用品牌色 shimmer 扫光文字而非
  spinner；动效遵守 prefers-reduced-motion。

# Scope

全部界面 + 交互范式重做（Q1 已确认）：

- `/chat` 主对话界面：`DshChat.tsx`、`DshSidebar.tsx`、`ToolCallCard.tsx`、
  `Markdown.tsx`、审批区块（`dsh-approval`）、执行结果卡（`dsh-exec`）
- `/workbench` 控制台：`AgentConsole.tsx`、`ChatStream.tsx`、
  `ChatComposer.tsx`、`HumanApprovalPanel.tsx`、`PlanEvidencePanel.tsx`、
  `RuntimeTimeline.tsx`、`TraceAuditPanel.tsx` 等——布局向 dsh 靠拢，
  思考步骤/审批/证据面板同样改为 disclosure-row 交互范式
- 样式载体：`frontend/app/globals.css`（约 2190 行，唯一样式文件）
  重构为三层 token + 组件区块

# Non-goals

- 不替换前端架构：保持 Next.js 15 + React 19 + 全局 CSS/（或 CSS Modules），
  不引入 dsh 的 cordis slot 插件体系，不整包替换为 `dsh-client-web` 壳
  （npm 上 client UI 包仅 0.0.1-rc.1 早期桩版本，且为 React 18 + cordis
  架构，整体替换等于重写前端，超出"优化界面"的诉求）。
- 不改变任何功能行为：SSE 流式、会话持久化、WRITE 审批门（6 参数、有效期、
  批准/拒绝互斥、防重复提交）、执行结果回流、历史回放等业务逻辑零改动。
- 不改动后端 API 路由、dsh 运行时、语义工具层。
- 不做新的响应式断点设计；保持现有断点行为。
- 界面文案保持中文不变。

# Acceptance examples

- 助手消息以整宽 markdown 渲染，无灰底气泡；用户消息保持右对齐气泡。
- 工具调用默认呈现为单行折叠行（图标 + 工具名 + 单行摘要），点击/回车展开
  为参数与结果卡片；运行中工具行有浅色扫光。
- 等待/运行状态显示品牌蓝渐变 shimmer 文字（如"DeepSeek 思考中…"），
  不再使用旋转 spinner。
- 思考过程面板与工具调用视觉统一为同一 disclosure row 语言。
- /workbench 的思考步骤、审批面板、证据面板同样以 disclosure row 呈现，
  与 /chat 共享同一套 token 与交互语言；plan-evidence 的衬线风格移除。
- 全站只存在一套三层 token（static / alias / specific），组件不硬编码颜色。

# Constraints and invariants

- WRITE 审批卡片功能行为完整保留（参数展示、expiresAt 过期态、互斥按钮、
  pending 禁用重复提交、批准后执行结果回流）。
- 结构化事实卡片、SAP 消息列表（S/W/E/A 着色）等业务语义呈现不丢失。
- `react-markdown` 不启用 rehype-raw 的安全约束不变。
- 所有通过 `npm --prefix frontend run verify`（typecheck + vitest + build）。
- 不提交任何凭据；不改动 `.env*`。

# Decisions

- Q1（2026-10-16 用户确认）：改造范围 = 全部界面 + 交互范式重做。
  /chat 与 /workbench 的布局与交互都向 dsh 靠拢；workbench 的思考步骤、
  审批、证据面板同样改为 disclosure-row 范式；plan-evidence 衬线风格归一。
- Q2（2026-10-16 用户确认）：引入明暗双主题 + 跟随系统。light/dark/system
  三档，body 属性切换 alias 层 token，首屏防闪烁内联脚本；切换入口放在
  侧边栏底部（system → light → dark 循环），默认 system。

# Open questions

（无未决问题；共享理解总结已于 2026-10-16 经用户确认）

# Verification expectations

- `npm --prefix frontend run verify` 全绿（typecheck + vitest + next build）。
- 人工目视核对 /chat 关键路径：空态欢迎页 → 发消息 → 流式回答 →
  工具卡折叠/展开 → WRITE 审批 → 执行结果卡。
- 现有 vitest（stream/state machine/approval/markdown 等）不因样式改动回归。
