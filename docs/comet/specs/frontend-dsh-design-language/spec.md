# Frontend DSH Design Language Specification

## Purpose

为 sap-nexus-agent 全部前端界面（`/chat` 主对话界面与 `/workbench` 控制台）
建立统一的设计语言：对齐 ontology-dsh（DeepSeek Harness web client）的三层
design token 体系与 AI 交互范式，消除当前三套并存视觉体系（workbench 墨蓝、
chat 手工复刻 DSH 蓝、plan-evidence 衬线残留）造成的不一致。本能力只规定
视觉与交互呈现，不改变任何业务功能行为（SSE 流式、WRITE 审批门、事实卡片
语义、会话持久化等）。

## Requirements

### Requirement: Single three-layer token system

全站样式 SHALL 使用一套三层 CSS 自定义属性 token 体系，替代现有的多组
临时色板：

- static 层：品牌蓝阶（deepseek 500 = rgb(65,118,230) 附近）、中性偏蓝灰阶、
  语义色阶（success/danger/warn），不带语义命名；
- alias 语义层：bg-base / bg-layer-N、border-l1..l4（l1 为极淡边框）、
  label-primary/secondary/tertiary/caption、interactive-bg-hover、
  state-{error,success,warn}-*、markdown 相关（code-block/inline-code/
  citation）；
- specific 组件层：bubble、sidebar-fill、composer、disclosure-row 等组件级
  token，只引用 alias 层。

组件 MUST NOT 硬编码颜色字面值；plan-evidence 区域的衬线字体（Georgia）
与独立 `--evidence-accent` 局部变量 MUST 移除并归入统一 token。

- **WHEN** 任意组件需要颜色、边框、阴影、圆角
  - **THEN** 引用 alias/specific 层 token，而非字面值或新起局部变量
- **WHEN** 审查 globals.css（或拆分后的样式文件）
  - **THEN** 不存在体系 A（--ink/--teal/--accent）与体系 C（衬线标题、
    --evidence-accent、未定义的 var(--surface)/var(--muted)）残留

### Requirement: Typography and motion tokens

字体栈 SHALL 对齐 dsh：sans 栈显式包含 PingFang SC / Microsoft YaHei；
等宽栈不以裸 monospace 结尾（避免 Windows CJK 回退宋体）。正文 markdown
基准 16px/28px。动效 SHALL 使用统一 easing（cubic-bezier(0.4,0,0.2,1)）
与时长档（0.1s/0.2s/0.3s），且所有动画 MUST 配对的
prefers-reduced-motion 降级。

- **WHEN** 渲染助手 markdown 正文
  - **THEN** 使用 16px/28px 基准字号行高
- **WHEN** 用户系统开启减少动态效果
  - **THEN** shimmer/扫光/淡入等动画退化为静态呈现

### Requirement: Assistant messages render full-width without bubble

助手消息 SHALL 整宽渲染 markdown，无气泡底色与边框；用户消息保持右对齐
淡蓝气泡（max-width 约 82%，大圆角）。消息列最大宽度居中。

- **WHEN** 渲染一条助手回答（含流式）
  - **THEN** 无气泡容器，markdown 直接整宽排版，代码块带复制按钮与
    深色代码底色
- **WHEN** 渲染一条用户消息
  - **THEN** 右对齐淡蓝气泡，圆角约 22px

### Requirement: Process content uses disclosure rows

一切过程性内容（思考过程、工具调用、检索/证据明细、重试/边界通知）
SHALL 收敛为统一的单行 disclosure row 范式：16px 前导图标/状态点 +
标题 + 分隔点 + 单行截断摘要；整行可点击（支持 Enter/Space）展开为卡片；
运行中行体有浅色扫光；默认折叠，运行中/待审批时自动展开，完成后自动
折叠。不再使用旋转 spinner；等待与运行状态 SHALL 以品牌蓝渐变 shimmer
扫光文字呈现（如"DeepSeek 思考中…"）。

- **WHEN** 模型执行工具调用
  - **THEN** 默认显示单行折叠行；点击展开后显示参数、能力链、结果/
    事实栅格、可折叠原始 JSON
- **WHEN** 等待首 token 或工具执行中
  - **THEN** 状态区显示 shimmer 文字，不出现 spinner 图标
- **WHEN** /workbench 渲染思考步骤、审批面板或证据面板
  - **THEN** 与 /chat 使用同一 disclosure row 视觉语言

### Requirement: WRITE approval keeps functional behavior under new skin

WRITE 审批在 disclosure-row/卡片新视觉下 MUST 完整保留既有功能行为：
6 个 PR 参数展示、expiresAt 倒计时/过期态、批准/拒绝互斥、pending 期间
禁用重复提交、批准后执行结果回流（PR 单号与 SAP S/W/E/A 消息着色）。

- **WHEN** 审批卡片处于 pending
  - **THEN** 重复提交被禁用，按钮呈现统一的状态语义色（warn=待审批 /
    success=已批准 / error=已拒绝）
- **WHEN** 批准后执行结果回流
  - **THEN** 结果卡使用统一 state token 呈现成功/失败，PR 单号等宽字体

### Requirement: Workbench layout converges to dsh language

/workbench 控制台 SHALL 复用同一 token 体系与交互范式：顶部栏、侧边导航、
stage 空态 hero、ChatStream 回合卡、HumanApprovalPanel、PlanEvidencePanel、
RuntimeTimeline、TraceAuditPanel 全部归入统一视觉；可保留其信息架构
（控制台布局不必改成 /chat 的对话框式），但颜色、字体、圆角、折叠交互
MUST 与 /chat 一致。

- **WHEN** 用户从 /chat 切换到 /workbench
  - **THEN** 无视觉跳变：同一品牌色、同一字级、同一 disclosure row 语言
- **WHEN** PlanEvidencePanel 渲染证据对象
  - **THEN** 使用 disclosure row/折叠卡与统一 token，无衬线大标题

### Requirement: Light/dark theme with system follow

前端 SHALL 提供 light / dark / system 三档主题，默认 system：

- alias 语义层 token 在暗色下整体重定义（挂 `body[data-theme="dark"]` 或
  等价属性切换）；static 层不变；specific 层只引用 alias 层从而自动跟随。
- 主题偏好 MUST 持久化（localStorage），并在 `<head>` 内联首屏防闪烁脚本：
  首 paint 前读出偏好/system 值并写入 body 属性与 `color-scheme`。
- 切换入口为侧边栏底部的主题按钮（system → light → dark 循环），
  /chat 与 /workbench 均可达。
- 暗色下代码块、shiki 风格语法高亮色、滚动条、阴影 MUST 有对应暗色值。

- **WHEN** 用户未手动选择且系统为暗色
  - **THEN** 首屏直接以暗色渲染，无亮→暗闪烁
- **WHEN** 用户切换主题
  - **THEN** 全站 alias 层即时切换且偏好持久化，刷新后保持
- **WHEN** 审查任意组件
  - **THEN** 不存在绕过 token 的硬编码颜色（否则暗色下会失真）
