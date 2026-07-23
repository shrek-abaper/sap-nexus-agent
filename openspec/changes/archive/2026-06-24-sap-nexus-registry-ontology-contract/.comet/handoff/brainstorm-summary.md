# Brainstorm Summary

- Change: sap-nexus-registry-ontology-contract
- Date: 2026-06-24
- Status: confirmed

## 确认的技术方案

采用 staged compatibility split。保留现有 runtime-compatible `registry/capabilities.yaml` 和 Gateway / Agent 读取路径，同时新增 contract-level schema、binding contract、validator、OWL skeleton 和 eval linkage 发布门禁。当前 `JCO_RFC` 必须通过；`ODATA`、`CDS_ADT`、`CDS_ODATA`、`REST_JSON` 只做 schema / fixture readiness，不实现 runtime pilot。

语义能力与技术绑定分层：

```text
Capability Registry = capabilityId / ontologyIri / kind / semantic IO / evidence / governance / eval linkage
Executor Binding Contract = bindingId / type / protocol allowlist / mapping / timeout / retry / sideEffect guard
Gateway Family = allowlisted protocol execution only
```

`REST_JSON` 只作为 SAP-context 外部事实来源的 contract readiness：固定 method、path template、request mapping、response mapping、credentialRef、timeout、retry 和 side-effect guard；禁止任意 URL、method、headers、token、credential value 或 LLM-generated JSON payload。

OWL 只做 offline identity skeleton；validator 检查 Registry `ontologyIri` 可映射到 skeleton identity，不让 Agent / Gateway runtime 加载 OWL。

## 关键取舍与风险

- 选择 staged compatibility split，而不是 hard cutover，避免重构已归档的 Gateway / Agent runtime。
- 优先不新增 PyYAML / jsonschema 依赖；当前 `.venv` 中 `yaml` 和 `jsonschema` 都不存在。validator 使用 stdlib 和项目限定解析/校验逻辑，避免网络依赖和安装漂移。
- 自定义解析器范围有限；通过限定输入形态为本项目 registry / binding fixtures 的 YAML 子集，并用负例测试覆盖风险。
- 短期 `executor` 与 contract `executorBinding` / binding fixtures 可能并存；这是过渡期兼容选择，不代表 Gateway 语义层长期归属。
- REST security drift 风险通过 contract 负例测试缓解：request-owned URL/method/header/token/payload/mapping 必须无效。

## 测试策略

- 新增 registry-focused tests：
  - `MM.Inventory.GetAvailability` 正例通过 contract。
  - identity / governance / sideEffect / approval policy 负例失败。
  - request-owned technical override 负例失败。
  - unsafe `REST_JSON` shape 负例失败。
  - active capability 缺 eval linkage 负例失败。
- 保留并运行现有回归：
  - `scripts/verify-agent-callplan-evidence.sh`
  - `openspec validate --all --strict`
- 新增 validator command 用于 release gate，并在 docs/runbooks/roadmap 中记录。

## Spec Patch

无。当前 delta spec 已覆盖主要验收场景；实现阶段不需要修改 spec，除非后续发现验收场景歧义。
