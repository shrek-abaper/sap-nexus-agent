# Outcome

将三个 list 类 BAPI 的生产 executor 从 JCO_RFC 迁移到 REST_JSON：

- `FI.AP.GetOpenItems`（BAPI_AP_ACC_GETOPENITEMS）
- `FI.AR.GetOpenItems`（BAPI_AR_ACC_GETOPENITEMS）
- `SD.SalesOrder.GetList`（BAPI_SALESORDER_GETLIST）

迁移后三个能力经 SICF rest2rfc 返回的主事实（openItems / salesOrders）与 JCo 结果
live 等价——该等价在 `add-rest-json-executor` 中已逐行取得证据。

# Scope

## Binding catalog

- `registry/executor-bindings.yaml`：AP 的 REST binding 已预置；新增 AR、SD 两条
  REST_JSON binding（同 AP 形态：systemRef/method/pathTemplate/request/response/auth/
  constraints）。原 JCO_RFC binding 保留（回滚路径与历史证据需要，不删除）。

## Capability registry

三个能力的 `executor` 块改为：

```yaml
executor:
  type: REST_JSON
  rfcName: <BAPI name>
  inputMapping: { ... 与原 JCo 映射完全相同 ... }
  outputMapping: { ... 与原 JCo 映射完全相同 ... }
executorBinding:
  type: REST_JSON
  bindingId: <rest binding id>
```

inputMapping/outputMapping 内容不改变，只改变 executor type 与 bindingId 指向。

## Snapshot / evals

- registry snapshot 因 catalog 与 capabilities 变更产生新 hash；`evals/matcher_cases.yaml`
  14 处 pin 同步更新。

## 验证

- registry contract；Gateway Java tests；agent 全量；8 evals；
- live harness 对三个能力再跑一次确认迁移后等价（AP/AR/SD 同输入）。

# Non-goals

- 不迁移 `MM.Inventory.GetAvailability`（其 RETURN 丢失的差异尚未接受）；
- 不迁移 WRITE / MM.Material；不改动 Java/前端代码（executor 运行时已就位）；
- 不删除旧 JCO binding；不改变任何 inputMapping/outputMapping 语义。

# Acceptance examples

- **AC1（AP live）**：迁移后同一 vendor/companyCode/keydate 经 SICF 的 openItems
  与此前 JCo 行数/字段一致（基准：28,197 行 / 131 字段等价已证）。
- **AC2（AR live）**：同 AP，基准 1,355 行 / 124 字段。
- **AC3（SD live）**：同一 customer/salesOrg/documentDate，基准 5,164 行 / 54 字段。
- **AC4（全量回归）**：contract 通过；gateway/agent 全绿；8 evals 通过；
  snapshot pin 与新 hash 一致。

# Constraints and invariants

- 三个能力的主事实均已有 live 等价证据；SD/MM 类 RETURN 文本缺失的已知取舍不
  影响主事实（SD 的失败分类仍 fail-closed；本迁移不改变错误处理代码）。
- 凭据仍三路共享（SAP_ASHOST/SAP_HTTP_PORT/SAP_CLIENT/USER/PASSWORD），registry
  中不出现连接字面值。
- 纯只读迁移，审批/commit 边界不涉及。

# Decisions

- **D1 迁移范围**：仅主事实等价已 live 证实的三个能力；Inventory 的迁移待
  returnMessages 差异被明确接受后另行立项。
- **D2 旧 JCO binding 保留**：不删除，保证 registry 历史与回滚可读性。
- **D3 mapping 零改动**：inputMapping/outputMapping 内容原样保留到 REST executor
  块，避免映射语义漂移。
- **D4 goal 式授权即最终确认**：依据 /goal「迁移这三个 list 类 BAPI 到 REST_JSON」
  的明确指令，Shape CONFIRM 视为已授权，自主推进 Build→Verify→Archive。

# Open questions

- CONFIRM: 上述范围即共享理解；按 D4 以 goal 授权确认（2026-09-26），推进 Build。

# Verification expectations

- `git status --short`；
- `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml`；
- `./gradlew -p services/gateway --no-daemon test`；
- `.venv/bin/python -m pytest agent/tests -q`；
- 8 evals + live harness（AP/AR/SD）。
