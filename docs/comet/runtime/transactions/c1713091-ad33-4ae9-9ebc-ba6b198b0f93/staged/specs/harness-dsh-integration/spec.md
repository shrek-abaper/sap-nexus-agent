## Purpose

定义本期垂直切片中独立 Node 应用 `harness-dsh/`（仓库新顶层目录）作为
DeepSeek Harness 消费方的完整目标行为：dsh 只承担 LLM 调用、T-A-O 循环、会话
记忆与叙事交互；工具调用只能命中本地 TS 客户端包装的**语义工具调用面**（即
`semantic-tool-http-facade` 规定的窄契约），不直连 Java Gateway、不构造
CallPlan、不包含受治理数据的业务逻辑。本规格同时规定版本 pin、profile、
waterfall 边界与跨 harness 一致性验收。

## Requirements

### Requirement: Version pin and change-review of the dsh dependency set

应用 SHALL 在 `harness-dsh/package.json` 精确 pin dsh 包族版本（不允许
`^`/`~`/`latest` 范围标记）；当前 pin 集合与升级评审记录由本 change 的
gap matrix 文档维护。CLI 主包 pin npm `latest` dist-tag 对应版本
（建 change 时为 `@deepseek-ai/dsh@0.1.5-rc.1`；`next` 标签的 rc.2 不采用）；
插件 SDK 包按 npm 各自 latest 逐包 pin（建 change 时 app-boot 为 0.1.0-rc.6、
headless/base 为 0.0.1-rc.1）。dsh 处于 0.1 preview，任何 dsh 包族升级 MUST
作为独立变更评审，禁止在非变更中漂移。

#### Scenario: Lockfile guarantees exact dsh lock state

- **WHEN** 检查 harness-dsh 的 package.json 与 lockfile
- **THEN** 每个 dsh 包族依赖都有精确版本与完整传递锁定
- **AND** 不接受未评审的版本漂移（lockfile 校验脚本通过）

#### Scenario: Version matrix is documented for review

- **WHEN** 查看本 change 的 gap matrix 文档
- **THEN** 含 pin 集合、dist-tag 事实、peer 兼容性确认方式与升级触发条件

### Requirement: Standalone app skeleton and tool contract client

应用 SHALL 为独立 Node 应用（npm 工具链、独立 lockfile，对齐 frontend 的 npm
生态，不引入 pnpm workspace；Node 版本满足 dsh 引擎要求 `^22.19 || >=24`），
通过 dsh 库嵌入方式（`dsh-app-boot` 等）构建，含最简 T-A-O 入口、一个注册到
dsh tool registry 的工具 `diagnose_material_supply`（pre/execute/post waterfall）。
工具 execute SHALL 只做：构造 facade 请求、发 HTTP、校验响应形状；本地校验
MUST NOT 成为唯一校验。

execute 之外的 dsh 插件代码 MUST 只能是形状校验、遥测、展示类确定性代码，
MUST NOT 包含：NL→semanticType 消费逻辑、能力选择/编排、权限判定、审批裁决、
SAP 字段映射、受治理数据缓存（除显式版本化元数据缓存）。

read 的元数据从服务端契约派生并带契约版本；当服务端契约版本不匹配时 MUST
fail-closed 并提示。

#### Scenario: Model-driven single tool round trip

- **WHEN** 用户在 dsh 应用中提出「A100 在 1000 工厂够不够用、在途多少」类问题
- **THEN** 模型经 dsh tool-calling 选择 `diagnose_material_supply`
- **AND** 工具经 facade 拿回 facts/narrative 并由 dsh 呈现，无任何 RFC/binding/凭证字段穿透

#### Scenario: Out-of-closure request is not improvised

- **WHEN** 模型/用户要求闭包外动作（如直接查 Gateway 或写 PR）
- **THEN** 工具层没有第二条调用路径可用；dsh 只能回显 facade 返回的 gap/scope 提示
- **AND** 应用代码中不存在直连 Gateway 的 HTTP 调用面

### Requirement: Dev profile and model endpoint reuse

应用 SHALL 提供单一 dev profile（dsh profile/bundle/`cordis.patch.yml` 三层
配置 + `--dump-config` 可导出审计）；sandbox/live profile 与最低模型能力线
gate（function-calling/JSON Schema ≥98%、accuracy@1 ≥90%）属后续 change，本期
MUST NOT 接 live SAP。模型端点复用仓库既有的 OpenAI-compatible 环境变量配置，
不在代码/日志中输出密钥。

#### Scenario: Config export is reviewable and secret-free

- **WHEN** 以 dev profile 运行 `--dump-config`
- **THEN** 可完整导出生效配置且导出内容不含密钥/token/.env 内容

#### Scenario: No live SAP path exists in this change

- **WHEN** 检查 harness-dsh 代码与配置
- **THEN** 不存在绕过 facade/Gateway 白名单访问 live SAP 的配置项或代码路径



### Requirement: Cross-harness consistency on the golden subset offline

验收 SHALL 新增一套跨 harness 一致性检查：同一组 golden 输入在 dsh 应用与
Python CLI 两条 harness 路径上，对**相同的录制/fixture Gateway 响应**（离线，
不打真实 SAP；C-0 live smoke 是独立后续阶段）产出一致的：resolved 槽位值、
能力链、fact 字段值（投影后），一致率 100%。Golden 子集取自现有
`evals/`（inventory / purchase_order / derived_parameter 及 end-to-end
release 的只读子集），新增 fixture 与 runner 归属 `harness-dsh/tests` 或
`evals/` 下明确位置。叙述文本不要求字面一致；基数归约/freshness 语义差异 MUST
在 gap matrix 中登记为发现项。

#### Scenario: Same fixtures, equal business values

- **WHEN** 用相同 golden 输入与录制 Gateway 响应分别跑 dsh 路径与 Python CLI 路径
- **THEN** 槽位值、capability 链、fact 投影值逐项相等（记录化 diff）
- **AND** 任何不一致使检查失败并输出分歧字段，不允许跳过

#### Scenario: Live SAP is not used by the consistency gate

- **WHEN** 运行跨 harness 一致性检查
- **THEN** 全程无真实 SAP 连接（fixture 模式），检查可在无 SAP 环境复现

### Requirement: Gap matrix artifact drives later extraction

Build 第一步 SHALL 产出差距矩阵文档（change 目录内），把 Notion 方案的
R-0/R-1/R-2/R-3/R-4/C-0/C-0.5/C-1/C-2/C-4…C-7 逐项映射到当前仓库事实
（已落地/部分存在/缺失，附文件路径与证据命令），标注 dsh pin 版本矩阵，并列出
切片过程中新发现的缺口作为后续 change 输入（尤其 Resolve/Plan 权威仍在
Python 进程这一过渡事实）。没有完成差距矩阵不得推进到 dsh 接入实现。

#### Scenario: Audit precedes integration code

- **WHEN** 检查 Build 产物顺序
- **THEN** 差距矩阵先于或同步于首批 harness-dsh 代码存在
- **AND** 每条 R/C 项有状态、证据与归属文件路径
