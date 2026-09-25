# Outcome

Java Gateway 新增第三类技术执行器 **REST_JSON**：以普通出站 HTTP/JSON 调用运行在
SAP 内部的纯 ABAP rest2rfc SICF 网关（动态反射模式），与 JCO_RFC（JCo 协议）、
ODATA（OData 协议）严格平级。Java Gateway 作为 Agent 连接 SAP 的统一处理网关
（鉴权、审计、validate-before-execute、principal 边界）定位不变。

本次交付：

1. registry schema 与 Java runtime 完整支持 REST_JSON，**元数据驱动、新增 RFC 零
   Java 改动**；
2. rest2rfc 连接配置（base URL / client / user / password）作为 Java Gateway 侧受控
   配置（环境变量 + Gateway properties），不下沉到 agent/前端，不写入 registry；
3. 以已存在的只读能力 `FI.AP.GetOpenItems`（BAPI_AP_ACC_GETOPENITEMS）为垂直切片，
   提供 live 等价性验证工具，逐行比对 SICF JSON 与现有 JCO_RFC 归一化结果；
4. 输出现有 RFC 的迁移评估清单（可迁 REST_JSON / 保留 JCO_RFC / 走 typed 契约）。

# Scope

## Registry / schema

- `schemas/capability.schema.json`：能力侧 `executor.type` 枚举增加 `REST_JSON`；
  REST_JSON 的 executor 块与 JCO_RFC 同构条件必填（`rfcName`、`inputMapping`、
  `outputMapping`）——inputMapping/outputMapping 是 adapter 组装与抽取的唯一映射来源。
- `schemas/executor-binding.schema.json`：已预留 REST_JSON（`systemRef` / `method` /
  `pathTemplate` / `request` / `response` / `auth`），不放宽其禁止明文凭据的约束。
- `registry/executor-bindings.yaml`：新增 AP 垂直切片 REST_JSON binding
  `sap.fi.ap.get-open-items-rest2rfc`（catalog 预置，本变更内不被任何能力引用——
  生产 registry 翻转以 live 等价证据为前提）。
- 不修改 `FI.AP.GetOpenItems` 能力的生产 executor（本变更内仍为 JCO_RFC）。

## Java Gateway（services/gateway）

- 新增 Gradle 模块 `rest`：`@Component("REST_JSON") RestJsonTechnicalAdapter`
  implements `TechnicalAdapter`；`settings.gradle` include，`app` 模块加入依赖。
- adapter 行为：
  - 请求：`POST {baseUrl}{path}?RFC={executor.rfcName}&sap-client={client}`，
    HTTP Basic Auth；请求体由 `executor.inputMapping` 生成，键名使用映射目标 SAP 名
    （大写下划线原样），标量按字符串发送；
  - 响应：rest2rfc 无外层信封，根对象直接平铺 EXPORTING/CHANGING/TABLES 输出，
    外层参数名与内层字段名均小写、NUMC 为字符串、空表为 `[]`；
  - 归一化与 JCo 路径对齐：按 `executor.outputMapping` 抽取输出，行字段名
    SAP 小写名 → camelCase，值一律按文本读取；
  - 业务错误：HTTP 200 时仍检查响应中的 `return` 数组，任一行 `type ∈ {E,A,X}`
    MUST 判为 `SAP_BUSINESS_ERROR`；
  - 传输错误：非 200 响应体为空，错误文本仅在 HTTP reason phrase——MUST 以状态码
    分类（401/403→凭据/授权错误、404→端点或函数未注册、400→INVALID_PARAMETER、
    422→SAP_BUSINESS_ERROR、500→SAP 侧错误、不可达→SAP_COMMUNICATION_ERROR），并将
    reason phrase 作为可审计消息；
  - 结果统一经 `TechnicalRedactor` 脱敏；任何凭据缺失场景 fail-closed，不发出请求。
- `BindingDefinition` / `BindingRegistryLoader` 增加 REST 字段建模（systemRef /
  pathTemplate / request / response / auth），供 adapter 读取。
- 连接配置：新增 `@ConfigurationProperties("sap.gateway.rest2rfc")` 属性类，按
  `systemRef` 解析命名端点（baseUrl/path/client/credentialRef/timeoutMs）；默认值由
  环境变量提供：`SAP_REST2RFC_BASE_URL`、`SAP_REST2RFC_CLIENT`、
  `SAP_REST2RFC_USER`、`SAP_REST2RFC_PASSWORD`，未设置时复用 `SAP_CLIENT` /
  `SAP_USER` / `SAP_PASSWORD`。
- dispatcher / controller 零改动（Spring bean 名 Map 路由自动生效）。

## 验证资产

- Gateway 单测：新模块 `MockRestServiceServer` 覆盖成功、200+RETURN(E)、400/401/404/
  422/500 空体、不可达、凭据缺失 fail-closed、脱敏；`BindingRegistryLoader` REST 字段
  测试；`app` 模块三路由（JCO_RFC/ODATA/REST_JSON）共存 API slice。
- Python contract：更新 `scripts/validate_registry_contract.py` 的 REST_JSON 规则以匹配
  真实 POST 网关（见 Decisions D6），并补正反例测试。
- live 等价 harness：新增 pytest（默认 skip，`SAP_REST2RFC_LIVE=1` 开启）直接调用
  SICF 端点与 Gateway JCO 路径，对 AP openItems 逐行比对并产出报告；凭据仅从环境变量
  读取。
- 迁移清单：新增文档逐个评估现有 7 能力对应 RFC 的输出形态与迁移归属。

# Non-goals

- 不替换 Java Gateway；语义层/agent/前端不持有 SAP 凭据、不直连 SAP；
- 本变更不翻转任何生产能力到 REST_JSON（FI.AP 翻转是 live 等价证据之后的后续动作）；
- 不接入任何 WRITE 能力；WRITE 的 ApprovalRecord 人工审批门禁不因 executor 改变而放松，
  其既有 controller/ApprovalGuard 检查链不改动；
- 不实现 typed 契约（`/SAP/BC/RESTFUL`）的 Java adapter——typed 仅作为迁移清单中的
  备选路径记录；
- 不改动 frontend、ontology schema、OData 路径；
- 不做批量 RFC 迁移；逐个迁移在本变更之后。

# Acceptance examples

- **AC1（live 等价）**：`SAP_REST2RFC_LIVE=1` 运行等价 harness：同一
  vendor/companyCode/keydate 输入下，SICF rest2rfc 返回的 `lineitems` 经 adapter 归一化
  后与 JCO_RFC 的 `openItems` 行数一致、逐行关键字段（凭证号、公司代码、金额、货币、
  到期日、供应商）值一致；`return` 同样可比对。
- **AC2（离线 adapter 成功路径）**：以契约形态 fixture（envelope-free，小写键、
  NUMC 字符串、空表 `[]`）经 MockRestServiceServer 返回时，adapter 输出
  data.openItems，行键为 camelCase，值为文本。
- **AC3（200 业务错误）**：HTTP 200 但 `return` 含 `type=E` → 结果 failure /
  SAP_BUSINESS_ERROR，消息来自该 return 行。
- **AC4（非 200 空体）**：404（函数未在 ZTIF_GENERAL_CON 注册或 SICF 节点缺失）→
  failure，响应体为空也能据状态码与 reason phrase 给出可审计错误分类。
- **AC5（不可达 / 凭据缺失）**：连接超时/拒绝 → SAP_COMMUNICATION_ERROR；凭据未配置
  → fail-closed 且不产生出站请求。
- **AC6（零 Java 迁移）**：测试中以 registry fixture 声明第二个 RFC 的 capability +
  REST binding，adapter 无需任何代码分支即可正确组装请求并抽取映射输出。
- **AC7（contract）**：REST binding 缺任一必填字段、含禁用明文凭据键、或 method 非
  POST（dynamic 模式）时校验失败；合规 REST binding 与现有全部 registry 内容校验通过。
- **AC8（全量回归）**：agent 全量 pytest、Gateway `./gradlew test`、registry contract、
  evals 全绿；live harness 默认 skip 不影响 CI。

# Constraints and invariants

- 行为等价优先：动态反射有固有取舍（参数须全 DDIC 类型、元数据 TABNAME-FIELDNAME
  形态可能 NOT_SUPPORTED、RAW/XSTRING 不支持、非 200 空体、日志 COMMIT WORK 副作用）；
  输出有损的 RFC 保留 JCO_RFC 或走 typed，不得假设全量无损迁移。
- 凭据只存在于环境变量与 Gateway 受控配置；registry、evals、文档中 MUST NOT 出现
  真实凭据；错误输出统一经 TechnicalRedactor。
- READ 能力绝不调用 BAPI_TRANSACTION_COMMIT/ROLLBACK（既有 JCo 边界不因新 executor
  弱化）；adapter 本身 MUST NOT 发出任何事务控制调用。
- 遵循既有节奏：spike/垂直切片先行、全量测试与 evals 全绿再收敛。

# Decisions

- **D1 平级定位**：REST_JSON 是 Java Gateway 的出站技术适配器，不改变 Gateway
  统一入口职责，也不绕过 validate / audit / approval 任一环节。
- **D2 切片不翻转生产**：本变更只在 binding catalog 预置 REST binding；能力生产
  executor 保持 JCO_RFC，直到 live 等价证据成立后再做翻转，避免无证据改变用户可见行为。
- **D3 映射来源**：复用能力 executor 块的 inputMapping/outputMapping（逻辑名↔SAP
  参数名），不为 REST 再造一套映射语言；request/response binding 字段仅承载契约形态
  元数据（参数类别提示与字段结构提示），不承载凭据与原始 URL。
- **D4 新 Gradle 模块 `rest`**：与 jco/odata 模块布局一致，避免把 SAP 出站逻辑混入
  odata 模块（odata 模块语义是本机 Python 反代）。
- **D5 systemRef/credentialRef 解析**：Gateway properties 维护按 systemRef 命名的端点
  目录，默认单端点由 `SAP_REST2RFC_*` 环境变量给出，credentialRef 经环境变量解析；
  registry 只写引用名，不写连接字面值。
- **D6 修正 Python contract 校验器**：现有 `_validate_rest_json_binding` 是 2026-06
  按"假设 GET 的通用 REST 契约"写的（Function 必须 GET），与真实 ABAP dynamic 网关
  只支持 POST 冲突；改为：Function REST_JSON binding MUST `method: POST`，保留
  read-only、禁明文凭据/原始 url/headers/payload 等全部既有禁令。
- **D7 live harness 直连比对**：等价证据在"SICF 实际 JSON ↔ Gateway JCO 归一化"层面
  取得（pytest + 环境变量凭据）；adapter 对真实报文形态的离线正确性由契约 fixture
  保证，无需启动双 Gateway 实例。
- **D8 goal 式授权即最终确认**：本 brief 的共享理解总结按用户 goal 指令
  （"非必要不要中途找我确认"）视为已获事前授权，Shape→Build 的 CONFIRM 以 goal
  prompt 为确认依据。
- **D9 三路共享 SAP 配置**（用户 2026-09-25 确认）：JCO_RFC / ODATA / REST_JSON
  共用同一套 host、client、user、password；JCo 以 `SAP_SYSNR` 寻址（非 HTTP），
  OData 与 SICF 共用 ICM `SAP_HTTP_PORT`、仅路径不同；REST_JSON endpoint 缺省由
  `SAP_ASHOST + SAP_HTTP_PORT` 派生，`SAP_REST2RFC_*` 仅作可选覆盖。

# Open questions

- CONFIRM: 上述 Outcome/Scope/Non-goals/Acceptance/Decisions 即共享理解；已按 D8
  依据 goal 式授权确认（2026-09-25），推进 Build。
- 环境事实（非阻塞，已查明）：live SAP 凭据当前不可用——`.env` 与 OS keyring 中
  jz.zhang 的密码均返回 401（密码自 2026-09-20 实测后已变更），DPAPI/Windows
  Credential Manager 无存储；AC1 live 证据须在凭据刷新后补取。另：调查中产生了
  若干次 401 失败登录，可能计入 SAP 登录失败计数。

# Verification expectations

- `git status --short`（变更前后）；
- registry contract：`scripts/validate-registry-contract.py`（以仓库实际命令名为准）；
- Gateway：`cd services/gateway && ./gradlew --no-daemon test`；
- Agent 全量：`.venv/bin/python -m pytest agent/tests`；
- evals / call-plan 证据：`scripts/verify-agent-callplan-evidence.sh`；
- live 等价 harness：默认 skip；凭据具备时以 `SAP_REST2RFC_LIVE=1` 运行并附报告；
  未运行时在 verification.md 的 Skipped checks 中如实记录原因。
