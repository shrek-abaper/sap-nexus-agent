# REST JSON Execution

## Purpose

为 Java Gateway 提供第三类技术执行路径 REST_JSON：以同步出站 HTTP/JSON 调用运行在
SAP 内部的纯 ABAP rest2rfc SICF 动态网关，由 registry 元数据驱动地组装 RFC 输入、
执行调用并归一化输出，使其与现有 JCO_RFC 路径的用户可见结果等价。Gateway 统一
处理鉴权、审计、validate-before-execute 的定位不因该执行器改变。

## Requirements

### Requirement: 平级技术适配器

系统 SHALL 以名为 `REST_JSON` 的 `TechnicalAdapter` 实现处理执行请求，并经现有
Spring bean 名 Map 分发自动生效；dispatcher 与 controller MUST NOT 为该执行器增加
硬编码分支。不支持该执行器的旧部署 MUST 继续以 `UNSUPPORTED_EXECUTOR` fail-closed。

### Requirement: registry 元数据驱动的请求组装

adapter SHALL 从能力 `executor` 块读取 `rfcName`、`inputMapping`，从绑定目录读取
`systemRef`、`pathTemplate`、`method`、`request` 契约元数据。对 dynamic 模式系统
SHALL 仅使用 HTTP POST，请求 URL 为
`{baseUrl}{pathTemplate}?RFC={rfcName}&sap-client={client}`，并以 HTTP Basic Auth
认证。请求体根为 JSON object，键名为 inputMapping 目标 SAP 参数名（大写、下划线
原样），标量值 MUST 按字符串发送；未提供的可选参数 MUST NOT 出现在请求体中。

### Requirement: 与 JCO_RFC 对齐的输出归一化

rest2rfc 成功响应无外层信封：根对象平铺输出参数，外层参数名与内层结构字段名均为
小写，NUMC 输出为字符串，空表为 `[]`。adapter SHALL 按能力 `outputMapping` 抽取
逻辑输出，行字段名 MUST 由 SAP 小写名转换为 camelCase，所有值 MUST 按文本读取，
使输出数据形态与现有 JCO_RFC 通用只读执行器一致。

### Requirement: 业务错误与传输错误分类

即便 HTTP 状态为 200，adapter SHALL 检查响应中的 `return` 参数，任一行
`type ∈ {E, A, X}` MUST 判定为 `SAP_BUSINESS_ERROR`。对非 200 响应（响应体为空、
错误文本仅在 reason phrase），系统 SHALL 按状态码分类：400→`INVALID_PARAMETER`，
401/403→凭据/授权错误，404→端点或函数未注册，422→`SAP_BUSINESS_ERROR`，
500→SAP 侧执行错误，连接超时或拒绝→`SAP_COMMUNICATION_ERROR`；reason phrase MUST
作为可审计错误消息保留。

### Requirement: Gateway 侧受控连接配置

rest2rfc 端点连接配置 SHALL 作为 Gateway 受控配置存在：按 binding 的 `systemRef`
解析命名端点（baseUrl、path、client），凭据按 `auth.credentialRef` 经环境变量
解析。三路（JCO_RFC/ODATA/REST_JSON）MUST 共用同一套 host、client、user、password；
REST_JSON 端点 baseUrl SHALL 缺省由共享 `SAP_ASHOST` 与 `SAP_HTTP_PORT` 派生，
`SAP_REST2RFC_*` 仅作可选覆盖。registry、agent、前端 MUST NOT 持有连接字面值或
SAP 凭据；凭据缺失时 adapter MUST fail-closed 且不产生出站请求。

### Requirement: 结果脱敏与只读边界

adapter 返回结果 SHALL 统一经现有技术脱敏器处理，使任何意外回传的敏感字段被遮蔽。
adapter MUST NOT 调用或间接触发任何事务控制函数；只读能力的 READ/WRITE 边界与
WRITE 能力的 ApprovalRecord 人工审批门禁 MUST NOT 因执行器类型改变而放松。

## Non-goals

- 替换 Java Gateway 或让语义层/前端直连 SAP；
- 本变更内翻转生产能力 executor、接入 WRITE 能力；
- typed 契约（/SAP/BC/RESTFUL）adapter、批量迁移、frontend 与 ontology 变更。
