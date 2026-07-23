---
change: sap-nexus-sandbox-write-vertical-slice
design-doc: docs/superpowers/specs/2026-07-16-sap-nexus-sandbox-write-vertical-slice-design.md
base-ref: bf74a249602ca57fbb532caca47fd6b04e140032
---

# SAP Nexus Sandbox Write Vertical Slice 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通 SAP Nexus Agent 首个 WRITE/Approval 闭环——以 `BAPI_PR_CREATE` 为首个 Action capability,建立 approval 守卫、commit/rollback 守卫、READ/WRITE 隔离硬边界,覆盖写入失败回归。

**Architecture:** Agent(Python)生成 Action CallPlan + ApprovalRecord -> Gateway(Java)execute 入口 approval 守卫 fail-closed -> JCoCapabilityExecutor write 分支执行 BAPI_PR_CREATE + 内部强制 commit/rollback -> ActionResult(PR号+commit状态+traceId) -> Agent(executed) -> Narrator。commit/rollback 归属 Gateway 内部,Agent/外部不触发;approval 守卫在 SAP 调用前。

**Tech Stack:** Java 17 + Spring Boot(Gateway)、JCo 3.x(BAPI 调用)、Python 3.11(Agent)、JSON Schema 2020-12(契约)、pytest(Agent 测试)、JUnit 5(Gateway 测试)、YAML(registry/eval)。

## Global Constraints

- **READ/WRITE 隔离**:`Function` 永不 commit/rollback;`Action` 必经 approval 守卫才 commit。
- **commit/rollback 在 Gateway 内部强制**(`JcoCapabilityExecutor` write 分支),Agent/外部不触发;参考 STO create 模式:`BAPI_TRANSACTION_COMMIT`(WAIT=X) + 失败 `BAPI_TRANSACTION_ROLLBACK` + `JCoContext.end`。
- **approval 守卫在 Gateway execute 入口、SAP 调用前 fail-closed**:APPROVAL_REQUIRED/APPROVAL_EXPIRED/APPROVAL_VERSION_MISMATCH/APPROVAL_DUPLICATE。
- **ApprovalRecord 存储**:JSONL trace 权威 + Markdown HITL 派生渲染。
- **approval TTL 默认 600s**(可配置 `SAP_NEXUS_APPROVAL_TTL_SECONDS`)。
- **MM.PR.CreateDraft**:7 inputs(5 必填 material/plant/quantity/unit/delivery_date + acct_assgn_cat 可选默认空=直采 + cost_center 条件必填 acct_assgn_cat="K" 时),output prNumber(PRITEMEXP.PREQ_NO)/returnMessages。
- **间采薄纵切先只支持 acct_assgn_cat="K"**。
- **敏感数据守卫**:`.env`/SAP 凭据/destination/token 不进 trace/响应/日志;`ActionResult` 与 trace 只记参数摘要、PR 号、commit 状态、错误类型。
- **仅 sandbox/dev client**,禁止生产 client;禁止 release/post/commit-heavy action。
- **不改现有 2 个 read capability 行为**(回归保护)。
- 参考现有 `InventoryAvailabilityExecutor` 的 BAPI 调用/RETURN 提取/sanitize 模式,write 分支复用其 import 应用与 RETURN 提取逻辑。

## 文件结构总览

### 新增文件

| 路径 | 职责 |
|---|---|
| `schemas/approval-record.schema.json` | ApprovalRecord 契约(approvalId/参数快照 hash/审批人/状态/TTL) |
| `schemas/action-result.schema.json` | ActionResult 契约(prNumber/commitStatus/returnMessages/duration/traceId/errorType) |
| `ontology/mm-purchaserequisition.owl` | PurchaseRequisition 本体类 + MM_PR_CreateDraft individual |
| `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/ApprovalRecord.java` | approval 记录 record 类型 |
| `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/ApprovalStore.java` | approval 存储接口(JSONL 权威 + 进程内索引) |
| `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/InMemoryApprovalStore.java` | 进程内实现(单实例 duplicate 防护) |
| `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/ApprovalGuard.java` | 守卫:存在性/过期/版本/duplicate(fail-closed) |
| `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/ApprovalErrorType.java` | APPROVAL_REQUIRED/EXPIRED/VERSION_MISMATCH/DUPLICATE 枚举 |
| `services/gateway/jco/src/main/java/com/sapnexus/gateway/jco/PrCreateDraftExecutor.java` | BAPI_PR_CREATE 执行 + commit/rollback 守卫 |
| `services/gateway/core/src/main/java/com/sapnexus/gateway/result/ActionResult.java` | write 结果 record(prNumber/commitStatus/duration/traceId) |
| `services/gateway/core/src/main/java/com/sapnexus/gateway/result/CommitStatus.java` | committed/rolled_back/none 枚举 |
| `agent/sap_nexus_agent/approval.py` | approval 状态机 + 参数快照 hash + JSONL 落盘 |
| `agent/sap_nexus_agent/action_result.py` | 解析 Gateway write 返回 |
| `agent/sap_nexus_agent/pr_intent.py` | PR create intent 解析(缺参澄清/条件必填) |
| `evals/pr_create_cases.json` | 9 个写入回归 case |
| `agent/tests/test_approval.py` | approval 状态机单元测试 |
| `agent/tests/test_pr_intent.py` | PR intent 单元测试 |
| `agent/tests/test_action_result.py` | ActionResult 解析测试 |
| `agent/tests/test_orchestrator_write.py` | orchestrator write 路径测试 |
| `services/gateway/core/src/test/java/com/sapnexus/gateway/approval/ApprovalGuardTest.java` | 守卫四种拒绝场景测试 |
| `services/gateway/jco/src/test/java/com/sapnexus/gateway/jco/PrCreateDraftExecutorTest.java` | commit/rollback 时序测试(mock destination) |
| `services/gateway/app/src/test/java/com/sapnexus/gateway/api/CapabilityWriteExecutionApiTest.java` | execute 入口 approval 守卫集成测试 |
| `docs/runbooks/11-sandbox-write-vertical-slice.md` | session closeout runbook |

### 修改文件

| 路径 | 改动 |
|---|---|
| `schemas/capability.schema.json` | governance.sideEffect 增加 `sap_write` enum 值;Action 分支强制 `sideEffect=sap_write` |
| `schemas/execution-result.schema.json` | errorType 增加 APPROVAL_* 与 SAP_COMMIT_ERROR 枚举 |
| `registry/capabilities.yaml` | 新增 `MM.PR.CreateDraft` capability |
| `registry/executor-bindings.yaml` | 新增 `sap.mm.pr.create-draft` JCO_RFC binding |
| `services/gateway/core/src/main/java/com/sapnexus/gateway/result/ErrorType.java` | 增加 APPROVAL_REQUIRED/EXPIRED/VERSION_MISMATCH/DUPLICATE、SAP_COMMIT_ERROR |
| `services/gateway/core/src/main/java/com/sapnexus/gateway/registry/SideEffect.java` | 增加 `sap_write` 枚举值 |
| `services/gateway/core/src/main/java/com/sapnexus/gateway/api/CapabilityController.java` | execute 入口插入 approval 守卫(Action only);返回 ActionResult for write |
| `services/gateway/core/src/main/java/com/sapnexus/gateway/execution/TechnicalExecutionRequest.java` | 增加 approvalRecord 字段 |
| `services/gateway/jco/src/main/java/com/sapnexus/gateway/jco/JcoCapabilityExecutor.java` | 接口不变(保持向后兼容),write 由新 PrCreateDraftExecutor 实现 |
| `services/gateway/core/src/main/java/com/sapnexus/gateway/execution/JcoRfcTechnicalAdapter.java` | 按 capabilityId 路由到对应 executor(Inventory vs PR) |
| `agent/sap_nexus_agent/call_plan.py` | `create_call_plan` 支持 kind=Action + requires_approval=true |
| `agent/sap_nexus_agent/capability_selector.py` | INTENT_TO_CAPABILITY 增加 `pr_create` 映射 |
| `agent/sap_nexus_agent/intent.py` | parse_intent 增加 PR create 关键词分支(或由 pr_intent.py 独立) |
| `agent/sap_nexus_agent/orchestrator.py` | run_query 增加 Action 路由:缺参澄清/approval 状态机/execute/narrate |
| `agent/sap_nexus_agent/gateway_client.py` | execute 传递 approvalRecord;解析 ActionResult |
| `scripts/verify-agent-callplan-evidence.sh` | 增加 pr_create_cases.json 回归行 |
| `docs/runbooks/README.md` | 索引追加 runbook 11 |
| `docs/wiki/sap-nexus-agent-implementation-roadmap.md` | §17.3 / row 10 进度标记 |

---

## Task 1: ApprovalRecord 与 ActionResult schema 契约

**Files:**
- Create: `schemas/approval-record.schema.json`
- Create: `schemas/action-result.schema.json`
- Modify: `schemas/capability.schema.json:191`(governance.sideEffect enum)
- Modify: `schemas/execution-result.schema.json:52-63`(errorType enum)
- Test: `agent/tests/test_contract_files.py`(现有契约测试,追加断言)

**Interfaces:**
- Produces: `ApprovalRecord` JSON schema(approvalId/parameterSnapshotHash/approver/approvedAt/expiresAt/status)
- Produces: `ActionResult` JSON schema(prNumber/commitStatus/returnMessages/durationMs/traceId/errorType)
- Produces: `capability.schema.json` 中 `sideEffect` enum 增加 `sap_write`;Action 分支 `allOf` 强制 `sideEffect=sap_write`

- [x] **Step 1: 写 ApprovalRecord schema**

Create `schemas/approval-record.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://sap-nexus-agent.local/schemas/approval-record.schema.json",
  "title": "SAP Nexus ApprovalRecord",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "approvalId",
    "capabilityId",
    "parameterSnapshotHash",
    "parameters",
    "approver",
    "approvedAt",
    "expiresAt",
    "status"
  ],
  "properties": {
    "approvalId": { "type": "string", "minLength": 1 },
    "capabilityId": { "type": "string", "minLength": 1 },
    "parameterSnapshotHash": { "type": "string", "minLength": 1 },
    "parameters": {
      "type": "object",
      "additionalProperties": { "type": "string" },
      "minProperties": 1
    },
    "approver": { "type": "string", "minLength": 1 },
    "approvedAt": { "type": "string", "format": "date-time" },
    "expiresAt": { "type": "string", "format": "date-time" },
    "status": { "type": "string", "enum": ["pending", "approved", "executed", "rejected"] }
  }
}
```

- [x] **Step 2: 写 ActionResult schema**

Create `schemas/action-result.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://sap-nexus-agent.local/schemas/action-result.schema.json",
  "title": "SAP Nexus ActionResult",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "traceId",
    "capabilityId",
    "success",
    "prNumber",
    "commitStatus",
    "returnMessages",
    "durationMs",
    "errorType"
  ],
  "properties": {
    "traceId": { "type": "string", "minLength": 1 },
    "capabilityId": { "type": "string", "minLength": 1 },
    "success": { "type": "boolean" },
    "prNumber": { "type": "string" },
    "commitStatus": { "type": "string", "enum": ["committed", "rolled_back", "none"] },
    "returnMessages": {
      "type": "array",
      "items": { "$ref": "#/$defs/sapReturnMessage" }
    },
    "durationMs": { "type": "integer", "minimum": 0 },
    "errorType": {
      "type": "string",
      "enum": [
        "NONE",
        "APPROVAL_REQUIRED",
        "APPROVAL_EXPIRED",
        "APPROVAL_VERSION_MISMATCH",
        "APPROVAL_DUPLICATE",
        "SAP_BUSINESS_ERROR",
        "SAP_COMMIT_ERROR",
        "SAP_AUTH_ERROR",
        "SAP_COMMUNICATION_ERROR",
        "NORMALIZATION_ERROR"
      ]
    }
  },
  "$defs": {
    "sapReturnMessage": {
      "type": "object",
      "additionalProperties": false,
      "required": ["type", "message"],
      "properties": {
        "type": { "type": "string", "minLength": 1 },
        "id": { "type": "string" },
        "number": { "type": "string" },
        "message": { "type": "string" },
        "field": { "type": "string" }
      }
    }
  }
}
```

- [x] **Step 3: 扩展 capability.schema.json governance.sideEffect**

在 `schemas/capability.schema.json` 的 `governance` 定义中(第 191 行附近),将:

```json
"sideEffect": { "type": "string", "enum": ["none", "read", "write"] },
```

改为:

```json
"sideEffect": { "type": "string", "enum": ["none", "read", "write", "sap_write"] },
```

并在 Action `allOf` 分支(第 86-101 行附近)增加 `sideEffect` 约束,将:

```json
{
  "if": {
    "properties": { "kind": { "const": "Action" } },
    "required": ["kind"]
  },
  "then": {
    "properties": {
      "governance": {
        "properties": {
          "requiresApproval": { "const": true },
          "approvalPolicy": { "const": "human_required" }
        }
      }
    }
  }
}
```

改为:

```json
{
  "if": {
    "properties": { "kind": { "const": "Action" } },
    "required": ["kind"]
  },
  "then": {
    "properties": {
      "governance": {
        "properties": {
          "sideEffect": { "const": "sap_write" },
          "requiresApproval": { "const": true },
          "approvalPolicy": { "const": "human_required" }
        }
      }
    }
  }
}
```

- [x] **Step 4: 扩展 execution-result.schema.json errorType**

在 `schemas/execution-result.schema.json` 的 `errorType` enum(第 52-63 行)增加 approval 与 commit 错误类型,将 enum 数组改为:

```json
"enum": [
  "NONE",
  "CAPABILITY_NOT_FOUND",
  "CAPABILITY_DISABLED",
  "MISSING_PARAMETER",
  "INVALID_PARAMETER",
  "APPROVAL_REQUIRED",
  "APPROVAL_EXPIRED",
  "APPROVAL_VERSION_MISMATCH",
  "APPROVAL_DUPLICATE",
  "SAP_BUSINESS_ERROR",
  "SAP_COMMIT_ERROR",
  "SAP_AUTH_ERROR",
  "SAP_COMMUNICATION_ERROR",
  "NORMALIZATION_ERROR"
]
```

- [x] **Step 5: 写失败测试——验证新 schema 校验 ApprovalRecord**

在 `agent/tests/test_contract_files.py` 追加(如文件已有 jsonschema 加载模式则复用):

```python
import json
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_schema(name: str) -> dict:
    with open(REPO_ROOT / "schemas" / name, encoding="utf-8") as f:
        return json.load(f)


def test_approval_record_schema_accepts_valid_record():
    schema = _load_schema("approval-record.schema.json")
    record = {
        "approvalId": "appr-001",
        "capabilityId": "MM.PR.CreateDraft",
        "parameterSnapshotHash": "sha256:abc123",
        "parameters": {"material": "M001", "plant": "1000"},
        "approver": "user@example.com",
        "approvedAt": "2026-07-16T10:00:00Z",
        "expiresAt": "2026-07-16T10:10:00Z",
        "status": "approved",
    }
    jsonschema.validate(record, schema)


def test_approval_record_schema_rejects_missing_hash():
    schema = _load_schema("approval-record.schema.json")
    record = {
        "approvalId": "appr-001",
        "capabilityId": "MM.PR.CreateDraft",
        "parameters": {"material": "M001"},
        "approver": "user@example.com",
        "approvedAt": "2026-07-16T10:00:00Z",
        "expiresAt": "2026-07-16T10:10:00Z",
        "status": "approved",
    }
    try:
        jsonschema.validate(record, schema)
        assert False, "should reject missing parameterSnapshotHash"
    except jsonschema.ValidationError:
        pass


def test_action_result_schema_accepts_success():
    schema = _load_schema("action-result.schema.json")
    result = {
        "traceId": "trace-001",
        "capabilityId": "MM.PR.CreateDraft",
        "success": True,
        "prNumber": "0010001234",
        "commitStatus": "committed",
        "returnMessages": [],
        "durationMs": 150,
        "errorType": "NONE",
    }
    jsonschema.validate(result, schema)


def test_action_result_schema_accepts_approval_reject():
    schema = _load_schema("action-result.schema.json")
    result = {
        "traceId": "trace-002",
        "capabilityId": "MM.PR.CreateDraft",
        "success": False,
        "prNumber": "",
        "commitStatus": "none",
        "returnMessages": [],
        "durationMs": 5,
        "errorType": "APPROVAL_REQUIRED",
    }
    jsonschema.validate(result, schema)


def test_capability_schema_action_requires_sap_write():
    schema = _load_schema("capability.schema.json")
    action_cap = {
        "version": 1,
        "capabilities": [
            {
                "capabilityId": "MM.PR.CreateDraft",
                "name": "PR Create",
                "description": "create PR",
                "status": "active",
                "kind": "Action",
                "domain": "MM",
                "businessObject": "PurchaseRequisition",
                "ontologyIri": "sapnexus:MM_PR_CreateDraft",
                "semanticType": "sapnexus:PurchaseRequisitionCreateAction",
                "inputs": [{"name": "material", "semanticType": "sapnexus:MaterialNumber", "required": True, "type": "string", "sapParameter": "MATERIAL"}],
                "outputs": [{"name": "prNumber", "semanticType": "sapnexus:PrNumber", "type": "string", "evidenceRole": "primaryFact"}],
                "executor": {"type": "JCO_RFC", "rfcName": "BAPI_PR_CREATE", "inputMapping": {"material": "PRITEM.MATERIAL"}, "outputMapping": {"prNumber": "PRITEMEXP.PREQ_NO"}},
                "executorBinding": {"type": "JCO_RFC", "bindingId": "sap.mm.pr.create-draft"},
                "evalLinkage": {"evalFile": "evals/pr_create_cases.json", "caseIds": ["pr-create-success-direct"]},
                "governance": {"sideEffect": "sap_write", "requiresApproval": True, "approvalPolicy": "human_required", "dataClassification": "internal", "auditRequired": True},
            }
        ],
    }
    jsonschema.validate(action_cap, schema)


def test_capability_schema_action_with_wrong_side_effect_rejected():
    schema = _load_schema("capability.schema.json")
    action_cap = {
        "version": 1,
        "capabilities": [
            {
                "capabilityId": "MM.PR.CreateDraft",
                "name": "PR Create",
                "description": "create PR",
                "status": "active",
                "kind": "Action",
                "domain": "MM",
                "businessObject": "PurchaseRequisition",
                "ontologyIri": "sapnexus:MM_PR_CreateDraft",
                "semanticType": "sapnexus:PurchaseRequisitionCreateAction",
                "inputs": [{"name": "material", "semanticType": "sapnexus:MaterialNumber", "required": True, "type": "string", "sapParameter": "MATERIAL"}],
                "outputs": [{"name": "prNumber", "semanticType": "sapnexus:PrNumber", "type": "string", "evidenceRole": "primaryFact"}],
                "executor": {"type": "JCO_RFC", "rfcName": "BAPI_PR_CREATE", "inputMapping": {"material": "PRITEM.MATERIAL"}, "outputMapping": {"prNumber": "PRITEMEXP.PREQ_NO"}},
                "executorBinding": {"type": "JCO_RFC", "bindingId": "sap.mm.pr.create-draft"},
                "evalLinkage": {"evalFile": "evals/pr_create_cases.json", "caseIds": ["pr-create-success-direct"]},
                "governance": {"sideEffect": "none", "requiresApproval": True, "approvalPolicy": "human_required", "dataClassification": "internal", "auditRequired": True},
            }
        ],
    }
    try:
        jsonschema.validate(action_cap, schema)
        assert False, "Action with sideEffect=none should be rejected"
    except jsonschema.ValidationError:
        pass
```

- [x] **Step 6: 运行测试确认失败**

Run: `.venv/bin/python -m pytest agent/tests/test_contract_files.py -v -k "approval_record or action_result or capability_schema_action"`
Expected: FAIL(schema 文件已创建但 capability.schema.json 的 Action allOf 尚未生效或测试已通过——若 Step 3 已完成则应 PASS;若先写测试再改 schema 则 FAIL)

- [x] **Step 7: 运行测试确认通过**

Run: `.venv/bin/python -m pytest agent/tests/test_contract_files.py -v -k "approval_record or action_result or capability_schema_action"`
Expected: PASS

- [x] **Step 8: 验证现有 2 个 read capability 仍通过增强后 schema**

Run: `.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v`
Expected: PASS(现有 Function capability 不受 sideEffect enum 扩展影响)

- [x] **Step 9: Commit**

```bash
git add schemas/approval-record.schema.json schemas/action-result.schema.json schemas/capability.schema.json schemas/execution-result.schema.json agent/tests/test_contract_files.py
git commit -m "feat(schema): add ApprovalRecord/ActionResult schemas, extend capability sideEffect with sap_write"
```

---

## Task 2: Registry 注册 MM.PR.CreateDraft capability

**Files:**
- Create: `ontology/mm-purchaserequisition.owl`
- Modify: `registry/executor-bindings.yaml`(追加 binding)
- Modify: `registry/capabilities.yaml`(追加 capability)
- Test: `agent/tests/test_registry_contract.py`(现有,确认新 capability 通过)

**Interfaces:**
- Produces: `MM.PR.CreateDraft` capability 定义(kind=Action, sideEffect=sap_write, requiresApproval=true, executor.type=JCO_RFC, rfcName=BAPI_PR_CREATE)
- Produces: `sap.mm.pr.create-draft` binding(rfcName=BAPI_PR_CREATE, allowedImports/Outputs)
- Produces: `sapnexus:MM_PR_CreateDraft` ontology individual

- [x] **Step 1: 写 ontology OWL 文件**

Create `ontology/mm-purchaserequisition.owl`:

```xml
<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xml:base="sapnexus">
  <owl:Ontology rdf:about="sapnexus:MM_PurchaseRequisition"/>

  <owl:Class rdf:about="sapnexus:PurchaseRequisition">
    <rdfs:subClassOf rdf:resource="sapnexus:BusinessObject"/>
  </owl:Class>
  <owl:Class rdf:about="sapnexus:PurchaseRequisitionCreateAction">
    <rdfs:subClassOf rdf:resource="sapnexus:Action"/>
  </owl:Class>
  <owl:Class rdf:about="sapnexus:PrNumber"/>
  <owl:Class rdf:about="sapnexus:AcctAssignmentCat"/>
  <owl:Class rdf:about="sapnexus:CostCenter"/>
  <owl:Class rdf:about="sapnexus:DeliveryDate"/>

  <owl:NamedIndividual rdf:about="sapnexus:MM_PR_CreateDraft">
    <rdf:type rdf:resource="sapnexus:PurchaseRequisitionCreateAction"/>
    <rdfs:label>MM.PR.CreateDraft</rdfs:label>
  </owl:NamedIndividual>
</rdf:RDF>
```

- [x] **Step 2: 追加 executor binding**

在 `registry/executor-bindings.yaml` 末尾追加:

```yaml
  - bindingId: sap.mm.pr.create-draft
    type: JCO_RFC
    rfcName: BAPI_PR_CREATE
    allowedImports:
      - PRITEM
      - PRITEMEXP
      - PRHEADER
      - PRHEADEREXP
      - RETURN
    allowedOutputs:
      - PRITEMEXP
      - PRHEADEREXP
      - RETURN
    constraints:
      sideEffect: sap_write
      timeoutMs: 30000
```

- [x] **Step 3: 追加 capability 定义**

在 `registry/capabilities.yaml` 的 `capabilities` 数组末尾追加:

```yaml
  - capabilityId: MM.PR.CreateDraft
    name: Purchase Requisition Create Draft
    description: 创建采购申请 (PR) 草稿, 支持实物直采与间采 (成本中心)
    status: active
    kind: Action
    domain: MM
    businessObject: PurchaseRequisition
    ontologyIri: sapnexus:MM_PR_CreateDraft
    semanticType: sapnexus:PurchaseRequisitionCreateAction
    inputs:
      - name: material
        semanticName: materialNumber
        semanticType: sapnexus:MaterialNumber
        required: true
        type: string
        minLength: 1
        maxLength: 40
        sapParameter: PRITEM.MATERIAL
      - name: plant
        semanticName: plant
        semanticType: sapnexus:Plant
        required: true
        type: string
        minLength: 1
        maxLength: 4
        sapParameter: PRITEM.PLANT
      - name: quantity
        semanticName: quantity
        semanticType: sapnexus:Quantity
        required: true
        type: number
        sapParameter: PRITEM.QUANTITY
      - name: unit
        semanticName: unitOfMeasure
        semanticType: sapnexus:UnitOfMeasure
        required: true
        type: string
        minLength: 1
        maxLength: 3
        sapParameter: PRITEM.UNIT
      - name: delivery_date
        semanticName: deliveryDate
        semanticType: sapnexus:DeliveryDate
        required: true
        type: string
        sapParameter: PRITEM.DELIV_DATE
      - name: acct_assgn_cat
        semanticName: accountAssignmentCategory
        semanticType: sapnexus:AcctAssignmentCat
        required: false
        type: string
        maxLength: 1
        sapParameter: PRITEM.ACCTASSCAT
      - name: cost_center
        semanticName: costCenter
        semanticType: sapnexus:CostCenter
        required: false
        type: string
        maxLength: 10
        sapParameter: PRITEM.COSTCENTER
    outputs:
      - name: prNumber
        semanticType: sapnexus:PrNumber
        type: string
        evidenceRole: primaryFact
      - name: returnMessages
        semanticType: sapnexus:SapReturnMessage
        type: array
        evidenceRole: executionEvidence
    executor:
      type: JCO_RFC
      rfcName: BAPI_PR_CREATE
      inputMapping:
        material: PRITEM.MATERIAL
        plant: PRITEM.PLANT
        quantity: PRITEM.QUANTITY
        unit: PRITEM.UNIT
        delivery_date: PRITEM.DELIV_DATE
        acct_assgn_cat: PRITEM.ACCTASSCAT
        cost_center: PRITEM.COSTCENTER
      outputMapping:
        prNumber: PRITEMEXP.PREQ_NO
        returnMessages: RETURN
    executorBinding:
      type: JCO_RFC
      bindingId: sap.mm.pr.create-draft
    evalLinkage:
      evalFile: evals/pr_create_cases.json
      caseIds:
        - pr-create-success-direct
        - pr-create-success-indirect
        - pr-create-missing-param
        - pr-create-indirect-missing-cost-center
        - pr-create-approval-missing
        - pr-create-approval-expired
        - pr-create-approval-version-mismatch
        - pr-create-duplicate-submit
        - pr-create-sap-business-error
    governance:
      sideEffect: sap_write
      requiresApproval: true
      approvalPolicy: human_required
      dataClassification: internal
      auditRequired: true
```

- [x] **Step 4: 运行 registry contract 校验**

Run: `.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml`
Expected: PASS(输出 `Registry contract valid: registry/capabilities.yaml`)

注:若报 `evalLinkage file not found`,先创建空的 `evals/pr_create_cases.json`(Task 7 会填充),临时内容:

```json
{"cases": [
  {"id": "pr-create-success-direct"},
  {"id": "pr-create-success-indirect"},
  {"id": "pr-create-missing-param"},
  {"id": "pr-create-indirect-missing-cost-center"},
  {"id": "pr-create-approval-missing"},
  {"id": "pr-create-approval-expired"},
  {"id": "pr-create-approval-version-mismatch"},
  {"id": "pr-create-duplicate-submit"},
  {"id": "pr-create-sap-business-error"}
]}
```

- [x] **Step 5: 运行现有 registry 契约测试确认 read capability 不受影响**

Run: `.venv/bin/python -m pytest agent/tests/test_registry_contract.py -v`
Expected: PASS

- [x] **Step 6: Commit**

```bash
git add ontology/mm-purchaserequisition.owl registry/executor-bindings.yaml registry/capabilities.yaml evals/pr_create_cases.json
git commit -m "feat(registry): register MM.PR.CreateDraft Action capability with BAPI_PR_CREATE binding"
```

---

## Task 3: Gateway ErrorType 与 SideEffect 枚举扩展

**Files:**
- Modify: `services/gateway/core/src/main/java/com/sapnexus/gateway/result/ErrorType.java`
- Modify: `services/gateway/core/src/main/java/com/sapnexus/gateway/registry/SideEffect.java`
- Create: `services/gateway/core/src/main/java/com/sapnexus/gateway/result/CommitStatus.java`
- Test: `services/gateway/core/src/test/java/com/sapnexus/gateway/result/ErrorTypeTest.java`

**Interfaces:**
- Produces: `ErrorType.APPROVAL_REQUIRED/APPROVAL_EXPIRED/APPROVAL_VERSION_MISMATCH/APPROVAL_DUPLICATE/SAP_COMMIT_ERROR`
- Produces: `SideEffect.sap_write`
- Produces: `CommitStatus` enum(committed/rolled_back/none)

- [x] **Step 1: 写失败测试——枚举值存在性**

Create `services/gateway/core/src/test/java/com/sapnexus/gateway/result/ErrorTypeTest.java`:

```java
package com.sapnexus.gateway.result;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

import com.sapnexus.gateway.registry.SideEffect;
import org.junit.jupiter.api.Test;

class ErrorTypeTest {

    @Test
    void approvalErrorTypesExist() {
        assertNotNull(ErrorType.valueOf("APPROVAL_REQUIRED"));
        assertNotNull(ErrorType.valueOf("APPROVAL_EXPIRED"));
        assertNotNull(ErrorType.valueOf("APPROVAL_VERSION_MISMATCH"));
        assertNotNull(ErrorType.valueOf("APPROVAL_DUPLICATE"));
        assertNotNull(ErrorType.valueOf("SAP_COMMIT_ERROR"));
    }

    @Test
    void commitStatusValuesExist() {
        assertEquals("committed", CommitStatus.committed.name());
        assertEquals("rolled_back", CommitStatus.rolled_back.name());
        assertEquals("none", CommitStatus.none.name());
    }

    @Test
    void sideEffectSapWriteExists() {
        assertNotNull(SideEffect.valueOf("sap_write"));
    }
}
```

- [x] **Step 2: 运行测试确认失败**

Run: `cd services/gateway && ./gradlew :gateway-core:test --tests ErrorTypeTest`
Expected: FAIL(枚举值不存在)

- [x] **Step 3: 扩展 ErrorType 枚举**

将 `services/gateway/core/src/main/java/com/sapnexus/gateway/result/ErrorType.java` 改为:

```java
package com.sapnexus.gateway.result;

public enum ErrorType {
    NONE,
    CAPABILITY_NOT_FOUND,
    CAPABILITY_DISABLED,
    MISSING_PARAMETER,
    INVALID_PARAMETER,
    UNSUPPORTED_EXECUTOR,
    APPROVAL_REQUIRED,
    APPROVAL_EXPIRED,
    APPROVAL_VERSION_MISMATCH,
    APPROVAL_DUPLICATE,
    SAP_BUSINESS_ERROR,
    SAP_COMMIT_ERROR,
    SAP_AUTH_ERROR,
    SAP_COMMUNICATION_ERROR,
    NORMALIZATION_ERROR
}
```

- [x] **Step 4: 扩展 SideEffect 枚举**

将 `services/gateway/core/src/main/java/com/sapnexus/gateway/registry/SideEffect.java` 改为:

```java
package com.sapnexus.gateway.registry;

public enum SideEffect {
    none,
    read,
    write,
    sap_write
}
```

- [x] **Step 5: 创建 CommitStatus 枚举**

Create `services/gateway/core/src/main/java/com/sapnexus/gateway/result/CommitStatus.java`:

```java
package com.sapnexus.gateway.result;

public enum CommitStatus {
    committed,
    rolled_back,
    none
}
```

- [x] **Step 6: 运行测试确认通过**

Run: `cd services/gateway && ./gradlew :gateway-core:test --tests ErrorTypeTest`
Expected: PASS

- [x] **Step 7: 运行 gateway 全量测试确认无回归**

Run: `cd services/gateway && ./gradlew test`
Expected: PASS(现有测试不受枚举扩展影响)

- [x] **Step 8: Commit**

```bash
git add services/gateway/core/src/main/java/com/sapnexus/gateway/result/ErrorType.java services/gateway/core/src/main/java/com/sapnexus/gateway/registry/SideEffect.java services/gateway/core/src/main/java/com/sapnexus/gateway/result/CommitStatus.java services/gateway/core/src/test/java/com/sapnexus/gateway/result/ErrorTypeTest.java
git commit -m "feat(gateway): extend ErrorType with approval/commit errors, SideEffect with sap_write, add CommitStatus"
```

---

## Task 4: ApprovalRecord Java record 与 ApprovalStore

**Files:**
- Create: `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/ApprovalRecord.java`
- Create: `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/ApprovalStore.java`
- Create: `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/InMemoryApprovalStore.java`
- Test: `services/gateway/core/src/test/java/com/sapnexus/gateway/approval/InMemoryApprovalStoreTest.java`

**Interfaces:**
- Produces: `ApprovalRecord` record(approvalId/capabilityId/parameterSnapshotHash/parameters/approver/approvedAt/expiresAt/status)
- Produces: `ApprovalStore` 接口(`find(approvalId)` / `save(record)` / `markExecuted(approvalId)`)
- Produces: `InMemoryApprovalStore` 实现(进程内 ConcurrentHashMap + duplicate 索引)

- [x] **Step 1: 写失败测试——store 存取与状态流转**

Create `services/gateway/core/src/test/java/com/sapnexus/gateway/approval/InMemoryApprovalStoreTest.java`:

```java
package com.sapnexus.gateway.approval;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.Test;

class InMemoryApprovalStoreTest {

    private ApprovalRecord sampleRecord(String approvalId, String status) {
        return new ApprovalRecord(
                approvalId,
                "MM.PR.CreateDraft",
                "sha256:abc",
                Map.of("material", "M001", "plant", "1000"),
                "user@example.com",
                Instant.now(),
                Instant.now().plusSeconds(600),
                status
        );
    }

    @Test
    void saveAndFindById() {
        InMemoryApprovalStore store = new InMemoryApprovalStore();
        ApprovalRecord record = sampleRecord("appr-001", "approved");
        store.save(record);
        Optional<ApprovalRecord> found = store.find("appr-001");
        assertTrue(found.isPresent());
        assertEquals("approved", found.get().status());
    }

    @Test
    void markExecutedTransitionsStatus() {
        InMemoryApprovalStore store = new InMemoryApprovalStore();
        store.save(sampleRecord("appr-002", "approved"));
        store.markExecuted("appr-002");
        ApprovalRecord found = store.find("appr-002").orElseThrow();
        assertEquals("executed", found.status());
    }

    @Test
    void findNonexistentReturnsEmpty() {
        InMemoryApprovalStore store = new InMemoryApprovalStore();
        assertTrue(store.find("nonexistent").isEmpty());
    }
}
```

- [x] **Step 2: 运行测试确认失败**

Run: `cd services/gateway && ./gradlew :gateway-core:test --tests InMemoryApprovalStoreTest`
Expected: FAIL(类不存在)

- [x] **Step 3: 创建 ApprovalRecord record**

Create `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/ApprovalRecord.java`:

```java
package com.sapnexus.gateway.approval;

import java.time.Instant;
import java.util.Map;

public record ApprovalRecord(
        String approvalId,
        String capabilityId,
        String parameterSnapshotHash,
        Map<String, String> parameters,
        String approver,
        Instant approvedAt,
        Instant expiresAt,
        String status
) {
    public boolean isExpired(Instant now) {
        return now.isAfter(expiresAt);
    }

    public boolean isExecuted() {
        return "executed".equals(status);
    }
}
```

- [x] **Step 4: 创建 ApprovalStore 接口**

Create `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/ApprovalStore.java`:

```java
package com.sapnexus.gateway.approval;

import java.util.Optional;

public interface ApprovalStore {
    void save(ApprovalRecord record);

    Optional<ApprovalRecord> find(String approvalId);

    void markExecuted(String approvalId);
}
```

- [x] **Step 5: 创建 InMemoryApprovalStore 实现**

Create `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/InMemoryApprovalStore.java`:

```java
package com.sapnexus.gateway.approval;

import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

import org.springframework.stereotype.Component;

@Component
public class InMemoryApprovalStore implements ApprovalStore {
    private final ConcurrentMap<String, ApprovalRecord> store = new ConcurrentHashMap<>();

    @Override
    public void save(ApprovalRecord record) {
        store.put(record.approvalId(), record);
    }

    @Override
    public Optional<ApprovalRecord> find(String approvalId) {
        return Optional.ofNullable(store.get(approvalId));
    }

    @Override
    public void markExecuted(String approvalId) {
        ApprovalRecord existing = store.get(approvalId);
        if (existing != null) {
            store.put(approvalId, new ApprovalRecord(
                    existing.approvalId(),
                    existing.capabilityId(),
                    existing.parameterSnapshotHash(),
                    existing.parameters(),
                    existing.approver(),
                    existing.approvedAt(),
                    existing.expiresAt(),
                    "executed"
            ));
        }
    }
}
```

- [x] **Step 6: 运行测试确认通过**

Run: `cd services/gateway && ./gradlew :gateway-core:test --tests InMemoryApprovalStoreTest`
Expected: PASS

- [x] **Step 7: Commit**

```bash
git add services/gateway/core/src/main/java/com/sapnexus/gateway/approval/ services/gateway/core/src/test/java/com/sapnexus/gateway/approval/
git commit -m "feat(gateway): add ApprovalRecord, ApprovalStore interface and InMemoryApprovalStore"
```

---

## Task 5: ApprovalGuard 守卫(fail-closed)

**Files:**
- Create: `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/ApprovalGuard.java`
- Test: `services/gateway/core/src/test/java/com/sapnexus/gateway/approval/ApprovalGuardTest.java`

**Interfaces:**
- Consumes: `ApprovalStore.find(approvalId)`、`ApprovalRecord.isExpired(now)`/`isExecuted()`/`parameterSnapshotHash()`
- Produces: `ApprovalGuard.check(ApprovalRecord record, String currentParameterHash, Instant now)` 返回 `ApprovalGuardResult`——命中拒绝返回 ErrorType,通过返回 OK

- [x] **Step 1: 写失败测试——四种拒绝场景 + 通过**

Create `services/gateway/core/src/test/java/com/sapnexus/gateway/approval/ApprovalGuardTest.java`:

```java
package com.sapnexus.gateway.approval;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Instant;
import java.util.Map;
import java.util.Optional;

import com.sapnexus.gateway.result.ErrorType;
import org.junit.jupiter.api.Test;

class ApprovalGuardTest {

    private final ApprovalGuard guard = new ApprovalGuard();
    private final Instant now = Instant.parse("2026-07-16T10:05:00Z");

    private ApprovalRecord record(String status, Instant expiresAt) {
        return new ApprovalRecord(
                "appr-001",
                "MM.PR.CreateDraft",
                "sha256:abc",
                Map.of("material", "M001"),
                "user@example.com",
                Instant.parse("2026-07-16T10:00:00Z"),
                expiresAt,
                status
        );
    }

    @Test
    void rejectsWhenRecordMissing() {
        ApprovalGuardResult result = guard.check(null, "sha256:abc", now);
        assertEquals(ErrorType.APPROVAL_REQUIRED, result.errorType());
        assertTrue(result.rejected());
    }

    @Test
    void rejectsWhenExpired() {
        ApprovalRecord expired = record("approved", Instant.parse("2026-07-16T10:01:00Z"));
        ApprovalGuardResult result = guard.check(expired, "sha256:abc", now);
        assertEquals(ErrorType.APPROVAL_EXPIRED, result.errorType());
    }

    @Test
    void rejectsWhenVersionMismatch() {
        ApprovalRecord approved = record("approved", Instant.parse("2026-07-16T10:10:00Z"));
        ApprovalGuardResult result = guard.check(approved, "sha256:different", now);
        assertEquals(ErrorType.APPROVAL_VERSION_MISMATCH, result.errorType());
    }

    @Test
    void rejectsWhenDuplicateExecuted() {
        ApprovalRecord executed = record("executed", Instant.parse("2026-07-16T10:10:00Z"));
        ApprovalGuardResult result = guard.check(executed, "sha256:abc", now);
        assertEquals(ErrorType.APPROVAL_DUPLICATE, result.errorType());
    }

    @Test
    void passesWhenApprovedAndValid() {
        ApprovalRecord approved = record("approved", Instant.parse("2026-07-16T10:10:00Z"));
        ApprovalGuardResult result = guard.check(approved, "sha256:abc", now);
        assertTrue(result.passed());
        assertEquals(ErrorType.NONE, result.errorType());
    }
}
```

- [x] **Step 2: 运行测试确认失败**

Run: `cd services/gateway && ./gradlew :gateway-core:test --tests ApprovalGuardTest`
Expected: FAIL(ApprovalGuard 类不存在)

- [x] **Step 3: 创建 ApprovalGuardResult record**

Create `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/ApprovalGuardResult.java`:

```java
package com.sapnexus.gateway.approval;

import com.sapnexus.gateway.result.ErrorType;

public record ApprovalGuardResult(ErrorType errorType, boolean rejected) {
    public static ApprovalGuardResult passed() {
        return new ApprovalGuardResult(ErrorType.NONE, false);
    }

    public static ApprovalGuardResult rejected(ErrorType errorType) {
        return new ApprovalGuardResult(errorType, true);
    }

    public boolean passed() {
        return !rejected;
    }
}
```

- [x] **Step 4: 创建 ApprovalGuard**

Create `services/gateway/core/src/main/java/com/sapnexus/gateway/approval/ApprovalGuard.java`:

```java
package com.sapnexus.gateway.approval;

import java.time.Instant;

import com.sapnexus.gateway.result.ErrorType;
import org.springframework.stereotype.Component;

@Component
public class ApprovalGuard {

    public ApprovalGuardResult check(ApprovalRecord record, String currentParameterHash, Instant now) {
        if (record == null) {
            return ApprovalGuardResult.rejected(ErrorType.APPROVAL_REQUIRED);
        }
        if (record.isExpired(now)) {
            return ApprovalGuardResult.rejected(ErrorType.APPROVAL_EXPIRED);
        }
        if (!record.parameterSnapshotHash().equals(currentParameterHash)) {
            return ApprovalGuardResult.rejected(ErrorType.APPROVAL_VERSION_MISMATCH);
        }
        if (record.isExecuted()) {
            return ApprovalGuardResult.rejected(ErrorType.APPROVAL_DUPLICATE);
        }
        return ApprovalGuardResult.passed();
    }
}
```

- [x] **Step 5: 运行测试确认通过**

Run: `cd services/gateway && ./gradlew :gateway-core:test --tests ApprovalGuardTest`
Expected: PASS(5 个 case 全部通过)

- [x] **Step 6: Commit**

```bash
git add services/gateway/core/src/main/java/com/sapnexus/gateway/approval/ApprovalGuard.java services/gateway/core/src/main/java/com/sapnexus/gateway/approval/ApprovalGuardResult.java services/gateway/core/src/test/java/com/sapnexus/gateway/approval/ApprovalGuardTest.java
git commit -m "feat(gateway): add ApprovalGuard fail-closed guard for 4 rejection scenarios"
```

---

## Task 6: ActionResult Java record

**Files:**
- Create: `services/gateway/core/src/main/java/com/sapnexus/gateway/result/ActionResult.java`
- Test: `services/gateway/core/src/test/java/com/sapnexus/gateway/result/ActionResultTest.java`

**Interfaces:**
- Produces: `ActionResult` record(traceId/capabilityId/success/prNumber/commitStatus/returnMessages/durationMs/errorType)
- Produces: `ActionResult.success(traceId, capabilityId, prNumber, returnMessages, durationMs)` 工厂
- Produces: `ActionResult.failure(traceId, capabilityId, errorType, message, durationMs)` 工厂

- [x] **Step 1: 写失败测试——工厂方法与字段**

Create `services/gateway/core/src/test/java/com/sapnexus/gateway/result/ActionResultTest.java`:

```java
package com.sapnexus.gateway.result;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

class ActionResultTest {

    @Test
    void successFactoryProducesCommittedResult() {
        List<SapReturnMessage> messages = List.of(new SapReturnMessage("S", "M06", "017", "PR created", ""));
        ActionResult result = ActionResult.success(
                "trace-001",
                "MM.PR.CreateDraft",
                "0010001234",
                messages,
                150L
        );
        assertTrue(result.success());
        assertEquals("0010001234", result.prNumber());
        assertEquals(CommitStatus.committed, result.commitStatus());
        assertEquals(ErrorType.NONE, result.errorType());
        assertEquals(150L, result.durationMs());
    }

    @Test
    void failureFactoryProducesRolledBackResult() {
        ActionResult result = ActionResult.failure(
                "trace-002",
                "MM.PR.CreateDraft",
                ErrorType.SAP_BUSINESS_ERROR,
                "BAPI returned E",
                80L
        );
        assertEquals(false, result.success());
        assertEquals("", result.prNumber());
        assertEquals(CommitStatus.rolled_back, result.commitStatus());
        assertEquals(ErrorType.SAP_BUSINESS_ERROR, result.errorType());
    }

    @Test
    void approvalFailureProducesNoneCommitStatus() {
        ActionResult result = ActionResult.failure(
                "trace-003",
                "MM.PR.CreateDraft",
                ErrorType.APPROVAL_REQUIRED,
                "No approval record",
                1L
        );
        assertEquals(CommitStatus.none, result.commitStatus());
        assertEquals(ErrorType.APPROVAL_REQUIRED, result.errorType());
    }
}
```

- [x] **Step 2: 运行测试确认失败**

Run: `cd services/gateway && ./gradlew :gateway-core:test --tests ActionResultTest`
Expected: FAIL(ActionResult 类不存在)

- [x] **Step 3: 创建 ActionResult record**

Create `services/gateway/core/src/main/java/com/sapnexus/gateway/result/ActionResult.java`:

```java
package com.sapnexus.gateway.result;

import java.util.List;

public record ActionResult(
        String traceId,
        String capabilityId,
        boolean success,
        String prNumber,
        CommitStatus commitStatus,
        List<SapReturnMessage> returnMessages,
        long durationMs,
        ErrorType errorType
) {
    public static ActionResult success(
            String traceId,
            String capabilityId,
            String prNumber,
            List<SapReturnMessage> returnMessages,
            long durationMs
    ) {
        return new ActionResult(
                traceId,
                capabilityId,
                true,
                prNumber,
                CommitStatus.committed,
                returnMessages,
                durationMs,
                ErrorType.NONE
        );
    }

    public static ActionResult failure(
            String traceId,
            String capabilityId,
            ErrorType errorType,
            String message,
            long durationMs
    ) {
        CommitStatus status = (errorType == ErrorType.APPROVAL_REQUIRED
                || errorType == ErrorType.APPROVAL_EXPIRED
                || errorType == ErrorType.APPROVAL_VERSION_MISMATCH
                || errorType == ErrorType.APPROVAL_DUPLICATE)
                ? CommitStatus.none
                : CommitStatus.rolled_back;
        return new ActionResult(
                traceId,
                capabilityId,
                false,
                "",
                status,
                List.of(new SapReturnMessage("E", "", "", message, "")),
                durationMs,
                errorType
        );
    }
}
```

- [x] **Step 4: 运行测试确认通过**

Run: `cd services/gateway && ./gradlew :gateway-core:test --tests ActionResultTest`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add services/gateway/core/src/main/java/com/sapnexus/gateway/result/ActionResult.java services/gateway/core/src/test/java/com/sapnexus/gateway/result/ActionResultTest.java
git commit -m "feat(gateway): add ActionResult record with success/failure factories"
```

---

## Task 7: PrCreateDraftExecutor——BAPI_PR_CREATE + commit/rollback 守卫

**Files:**
- Create: `services/gateway/jco/src/main/java/com/sapnexus/gateway/jco/PrCreateDraftExecutor.java`
- Modify: `services/gateway/core/src/main/java/com/sapnexus/gateway/execution/JcoRfcTechnicalAdapter.java`(按 capabilityId 路由)
- Test: `services/gateway/jco/src/test/java/com/sapnexus/gateway/jco/PrCreateDraftExecutorTest.java`

**Interfaces:**
- Consumes: `JcoDestinationFactory.getDestination()`、`JCoFunction` execute
- Consumes: `CapabilityDefinition.executor().inputMapping()`/`outputMapping()`
- Produces: `PrCreateDraftExecutor.execute(capability, parameters, traceId)` 返回 `ExecutionResult`(write 路径:成功 commit / 业务错误 rollback / commit 失败 rollback)
- Produces: `JcoRfcTechnicalAdapter` 按 capabilityId 选择 executor(MM.PR.CreateDraft -> PrCreateDraftExecutor;其他 -> InventoryAvailabilityExecutor)

- [x] **Step 1: 写失败测试——commit/rollback 时序三种场景**

Create `services/gateway/jco/src/test/java/com/sapnexus/gateway/jco/PrCreateDraftExecutorTest.java`:

```java
package com.sapnexus.gateway.jco;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.List;
import java.util.Map;

import com.sap.conn.jco.JCoDestination;
import com.sap.conn.jco.JCoException;
import com.sap.conn.jco.JCoFunction;
import com.sap.conn.jco.JCoParameterList;
import com.sap.conn.jco.JCoStructure;
import com.sap.conn.jco.JCoTable;
import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.registry.CapabilityKind;
import com.sapnexus.gateway.registry.CapabilityStatus;
import com.sapnexus.gateway.registry.Executor;
import com.sapnexus.gateway.registry.ExecutorBinding;
import com.sapnexus.gateway.registry.Governance;
import com.sapnexus.gateway.registry.SideEffect;
import com.sapnexus.gateway.result.CommitStatus;
import com.sapnexus.gateway.result.ExecutionResult;
import com.sapnexus.gateway.result.SapReturnNormalizer;
import org.junit.jupiter.api.Test;

class PrCreateDraftExecutorTest {

    private CapabilityDefinition prCapability() {
        return new CapabilityDefinition(
                "MM.PR.CreateDraft",
                "PR Create",
                "create PR",
                CapabilityStatus.active,
                CapabilityKind.Action,
                "MM",
                "PurchaseRequisition",
                "sapnexus:MM_PR_CreateDraft",
                "sapnexus:PurchaseRequisitionCreateAction",
                List.of(),
                List.of(),
                new Executor(
                        "JCO_RFC",
                        "BAPI_PR_CREATE",
                        Map.of("material", "PRITEM.MATERIAL", "plant", "PRITEM.PLANT"),
                        Map.of("prNumber", "PRITEMEXP.PREQ_NO", "returnMessages", "RETURN")
                ),
                new ExecutorBinding("JCO_RFC", "sap.mm.pr.create-draft"),
                new Governance(SideEffect.sap_write, true, "human_required", "internal", true)
        );
    }

    @Test
    void successCommitsAndExtractsPrNumber() throws Exception {
        JCoDestination destination = mock(JCoDestination.class);
        JCoFunction prFunction = mock(JCoFunction.class);
        JCoFunction commitFunction = mock(JCoFunction.class);
        JCoParameterList imports = mock(JCoParameterList.class);
        JCoParameterList exports = mock(JCoParameterList.class);
        JCoParameterList tables = mock(JCoParameterList.class);
        JCoTable returnTable = mock(JCoTable.class);
        JCoTable prItemExpTable = mock(JCoTable.class);

        when(destination.getRepository().getFunction("BAPI_PR_CREATE")).thenReturn(prFunction);
        when(destination.getRepository().getFunction("BAPI_TRANSACTION_COMMIT")).thenReturn(commitFunction);
        when(prFunction.getImportParameterList()).thenReturn(imports);
        when(prFunction.getExportParameterList()).thenReturn(null);
        when(prFunction.getTableParameterList()).thenReturn(tables);
        when(tables.getTable("RETURN")).thenReturn(returnTable);
        when(returnTable.getNumRows()).thenReturn(1);
        when(returnTable.getString("TYPE")).thenReturn("S");
        when(returnTable.getString("ID")).thenReturn("M06");
        when(returnTable.getString("NUMBER")).thenReturn("017");
        when(returnTable.getString("MESSAGE")).thenReturn("PR created");
        when(returnTable.getString("FIELD")).thenReturn("");
        when(tables.getTable("PRITEMEXP")).thenReturn(prItemExpTable);
        when(prItemExpTable.getNumRows()).thenReturn(1);
        when(prItemExpTable.getString("PREQ_NO")).thenReturn("0010001234");

        JcoDestinationFactory factory = mock(JcoDestinationFactory.class);
        when(factory.getDestination()).thenReturn(destination);
        SapReturnNormalizer normalizer = new SapReturnNormalizer();

        PrCreateDraftExecutor executor = new PrCreateDraftExecutor(factory, normalizer);
        ExecutionResult result = executor.execute(prCapability(), Map.of("material", "M001", "plant", "1000"), "trace-001");

        assertTrue(result.success());
        assertEquals("0010001234", result.data().get("prNumber"));
        verify(prFunction, times(1)).execute(destination);
        verify(commitFunction, times(1)).execute(destination);
    }

    @Test
    void businessErrorRollbacksAndNoCommit() throws Exception {
        JCoDestination destination = mock(JCoDestination.class);
        JCoFunction prFunction = mock(JCoFunction.class);
        JCoFunction rollbackFunction = mock(JCoFunction.class);
        JCoParameterList tables = mock(JCoParameterList.class);
        JCoTable returnTable = mock(JCoTable.class);

        when(destination.getRepository().getFunction("BAPI_PR_CREATE")).thenReturn(prFunction);
        when(destination.getRepository().getFunction("BAPI_TRANSACTION_ROLLBACK")).thenReturn(rollbackFunction);
        when(prFunction.getImportParameterList()).thenReturn(mock(JCoParameterList.class));
        when(prFunction.getTableParameterList()).thenReturn(tables);
        when(tables.getTable("RETURN")).thenReturn(returnTable);
        when(returnTable.getNumRows()).thenReturn(1);
        when(returnTable.getString("TYPE")).thenReturn("E");
        when(returnTable.getString("MESSAGE")).thenReturn("Material not found");

        JcoDestinationFactory factory = mock(JcoDestinationFactory.class);
        when(factory.getDestination()).thenReturn(destination);

        PrCreateDraftExecutor executor = new PrCreateDraftExecutor(factory, new SapReturnNormalizer());
        ExecutionResult result = executor.execute(prCapability(), Map.of("material", "INVALID"), "trace-002");

        assertFalse(result.success());
        verify(prFunction, times(1)).execute(destination);
        verify(rollbackFunction, times(1)).execute(destination);
    }

    @Test
    void commitFailureRollbacksAsFallback() throws Exception {
        JCoDestination destination = mock(JCoDestination.class);
        JCoFunction prFunction = mock(JCoFunction.class);
        JCoFunction commitFunction = mock(JCoFunction.class);
        JCoFunction rollbackFunction = mock(JCoFunction.class);
        JCoParameterList tables = mock(JCoParameterList.class);
        JCoTable returnTable = mock(JCoTable.class);
        JCoStructure commitReturn = mock(JCoStructure.class);
        JCoParameterList commitExports = mock(JCoParameterList.class);

        when(destination.getRepository().getFunction("BAPI_PR_CREATE")).thenReturn(prFunction);
        when(destination.getRepository().getFunction("BAPI_TRANSACTION_COMMIT")).thenReturn(commitFunction);
        when(destination.getRepository().getFunction("BAPI_TRANSACTION_ROLLBACK")).thenReturn(rollbackFunction);
        when(prFunction.getImportParameterList()).thenReturn(mock(JCoParameterList.class));
        when(prFunction.getTableParameterList()).thenReturn(tables);
        when(tables.getTable("RETURN")).thenReturn(returnTable);
        when(returnTable.getNumRows()).thenReturn(1);
        when(returnTable.getString("TYPE")).thenReturn("S");
        when(returnTable.getString("MESSAGE")).thenReturn("PR created");
        when(commitFunction.getExportParameterList()).thenReturn(commitExports);
        when(commitExports.getStructure("RETURN")).thenReturn(commitReturn);
        when(commitReturn.getString("TYPE")).thenReturn("E");
        when(commitReturn.getString("MESSAGE")).thenReturn("Commit failed");

        JcoDestinationFactory factory = mock(JcoDestinationFactory.class);
        when(factory.getDestination()).thenReturn(destination);

        PrCreateDraftExecutor executor = new PrCreateDraftExecutor(factory, new SapReturnNormalizer());
        ExecutionResult result = executor.execute(prCapability(), Map.of("material", "M001"), "trace-003");

        assertFalse(result.success());
        verify(commitFunction, times(1)).execute(destination);
        verify(rollbackFunction, times(1)).execute(destination);
    }
}
```

- [x] **Step 2: 运行测试确认失败**

Run: `cd services/gateway && ./gradlew :gateway-jco:test --tests PrCreateDraftExecutorTest`
Expected: FAIL(PrCreateDraftExecutor 类不存在)

- [x] **Step 3: 创建 PrCreateDraftExecutor**

Create `services/gateway/jco/src/main/java/com/sapnexus/gateway/jco/PrCreateDraftExecutor.java`:

```java
package com.sapnexus.gateway.jco;

import com.sap.conn.jco.JCoDestination;
import com.sap.conn.jco.JCoException;
import com.sap.conn.jco.JCoFunction;
import com.sap.conn.jco.JCoParameterList;
import com.sap.conn.jco.JCoRecord;
import com.sap.conn.jco.JCoTable;
import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.result.ErrorType;
import com.sapnexus.gateway.result.ExecutionResult;
import com.sapnexus.gateway.result.SapReturnMessage;
import com.sapnexus.gateway.result.SapReturnNormalizer;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Component
public class PrCreateDraftExecutor implements JcoCapabilityExecutor {
    private final JcoDestinationFactory destinationFactory;
    private final SapReturnNormalizer returnNormalizer;

    public PrCreateDraftExecutor() {
        this(new JcoDestinationFactory(), new SapReturnNormalizer());
    }

    PrCreateDraftExecutor(JcoDestinationFactory destinationFactory, SapReturnNormalizer returnNormalizer) {
        this.destinationFactory = destinationFactory;
        this.returnNormalizer = returnNormalizer;
    }

    @Override
    public ExecutionResult execute(CapabilityDefinition capability, Map<String, Object> parameters, String traceId) {
        long started = System.nanoTime();
        try {
            JCoDestination destination = destinationFactory.getDestination();
            JCoFunction prFunction = destination.getRepository().getFunction(capability.executor().rfcName());
            if (prFunction == null) {
                return failure(traceId, capability, ErrorType.NORMALIZATION_ERROR, "SAP function not found", started);
            }

            applyImportParameters(prFunction.getImportParameterList(), capability, parameters);
            applyPrItemTable(prFunction.getTableParameterList(), capability, parameters);
            prFunction.execute(destination);

            List<SapReturnMessage> returnMessages = extractReturnMessages(prFunction);
            SapReturnNormalizer.Result normalized = returnNormalizer.normalize(returnMessages);

            if (!normalized.success()) {
                rollback(destination, traceId);
                return new ExecutionResult(
                        traceId,
                        capability.capabilityId(),
                        false,
                        new ExecutionResult.ExecutorMetadata(capability.executor().type(), capability.executor().rfcName()),
                        normalized.messages(),
                        Map.of(),
                        elapsedMs(started),
                        ErrorType.SAP_BUSINESS_ERROR
                );
            }

            // Commit with WAIT=X
            JCoFunction commitFunction = destination.getRepository().getFunction("BAPI_TRANSACTION_COMMIT");
            commitFunction.getImportParameterList().setValue("WAIT", "X");
            commitFunction.execute(destination);

            List<SapReturnMessage> commitReturn = extractCommitReturn(commitFunction);
            SapReturnNormalizer.Result commitNormalized = returnNormalizer.normalize(commitReturn);
            if (!commitNormalized.success()) {
                rollback(destination, traceId);
                return new ExecutionResult(
                        traceId,
                        capability.capabilityId(),
                        false,
                        new ExecutionResult.ExecutorMetadata(capability.executor().type(), capability.executor().rfcName()),
                        commitNormalized.messages(),
                        Map.of(),
                        elapsedMs(started),
                        ErrorType.SAP_COMMIT_ERROR
                );
            }

            Map<String, Object> data = extractPrNumber(prFunction, capability);
            return ExecutionResult.success(
                    traceId,
                    capability.capabilityId(),
                    capability.executor().type(),
                    capability.executor().rfcName(),
                    normalized.messages(),
                    data,
                    elapsedMs(started)
            );
        } catch (JCoException exception) {
            return failure(traceId, capability, mapJcoError(exception), sanitize(exception.getMessage()), started);
        } catch (RuntimeException exception) {
            return failure(traceId, capability, ErrorType.SAP_COMMUNICATION_ERROR, sanitize(exception.getMessage()), started);
        }
    }

    private void applyImportParameters(JCoParameterList imports, CapabilityDefinition capability, Map<String, Object> parameters) {
        if (imports == null) {
            return;
        }
        capability.executor().inputMapping().forEach((requestName, sapName) -> {
            Object value = parameters.get(requestName);
            if (value != null && hasParameter(imports, sapName)) {
                imports.setValue(sapName, value);
            }
        });
    }

    private void applyPrItemTable(JCoParameterList tables, CapabilityDefinition capability, Map<String, Object> parameters) {
        if (tables == null || !safeIsInitialized(tables, "PRITEM")) {
            return;
        }
        try {
            JCoTable prItem = tables.getTable("PRITEM");
            prItem.appendRow();
            capability.executor().inputMapping().forEach((requestName, sapName) -> {
                Object value = parameters.get(requestName);
                if (value != null && prItem.getMetaData().hasField(sapName)) {
                    prItem.setValue(sapName, value);
                }
            });
        } catch (RuntimeException ignored) {
            // PRITEM table shape varies by SAP release; import params path covers scalar fields.
        }
    }

    private List<SapReturnMessage> extractReturnMessages(JCoFunction function) {
        List<SapReturnMessage> messages = new ArrayList<>();
        JCoParameterList tables = function.getTableParameterList();
        if (tables != null && safeIsInitialized(tables, "RETURN")) {
            try {
                JCoTable table = tables.getTable("RETURN");
                for (int row = 0; row < table.getNumRows(); row++) {
                    table.setRow(row);
                    messages.add(toReturnMessage(table));
                }
            } catch (RuntimeException ignored) {
            }
        }
        return messages;
    }

    private List<SapReturnMessage> extractCommitReturn(JCoFunction commitFunction) {
        List<SapReturnMessage> messages = new ArrayList<>();
        JCoParameterList exports = commitFunction.getExportParameterList();
        if (exports != null && safeIsInitialized(exports, "RETURN")) {
            try {
                messages.add(toReturnMessage(exports.getStructure("RETURN")));
            } catch (RuntimeException ignored) {
            }
        }
        return messages;
    }

    private Map<String, Object> extractPrNumber(JCoFunction function, CapabilityDefinition capability) {
        Map<String, Object> data = new LinkedHashMap<>();
        JCoParameterList tables = function.getTableParameterList();
        if (tables != null && safeIsInitialized(tables, "PRITEMEXP")) {
            try {
                JCoTable prItemExp = tables.getTable("PRITEMEXP");
                if (prItemExp.getNumRows() > 0) {
                    prItemExp.setRow(0);
                    data.put("prNumber", getString(prItemExp, "PREQ_NO"));
                }
            } catch (RuntimeException ignored) {
            }
        }
        return data;
    }

    private void rollback(JCoDestination destination, String traceId) {
        try {
            JCoFunction rollbackFunction = destination.getRepository().getFunction("BAPI_TRANSACTION_ROLLBACK");
            rollbackFunction.execute(destination);
        } catch (JCoException | RuntimeException ignored) {
            // Best-effort rollback; trace already records the primary failure.
        }
    }

    private SapReturnMessage toReturnMessage(JCoRecord record) {
        return new SapReturnMessage(
                getString(record, "TYPE"),
                getString(record, "ID"),
                getString(record, "NUMBER"),
                getString(record, "MESSAGE"),
                getString(record, "FIELD")
        );
    }

    private String getString(JCoRecord record, String field) {
        try {
            return record.isInitialized(field) ? record.getString(field) : "";
        } catch (RuntimeException ignored) {
            return "";
        }
    }

    private boolean safeIsInitialized(JCoRecord record, String field) {
        try {
            return record.isInitialized(field);
        } catch (RuntimeException ignored) {
            return false;
        }
    }

    private boolean hasParameter(JCoParameterList parameters, String field) {
        try {
            return parameters.getMetaData().indexOf(field) >= 0;
        } catch (RuntimeException ignored) {
            return false;
        }
    }

    private ErrorType mapJcoError(JCoException exception) {
        return switch (exception.getGroup()) {
            case JCoException.JCO_ERROR_LOGON_FAILURE, JCoException.JCO_ERROR_PASSWORD_CHANGE_REQUIRED -> ErrorType.SAP_AUTH_ERROR;
            case JCoException.JCO_ERROR_COMMUNICATION, JCoException.JCO_ERROR_TIMEOUT -> ErrorType.SAP_COMMUNICATION_ERROR;
            default -> ErrorType.SAP_BUSINESS_ERROR;
        };
    }

    private ExecutionResult failure(String traceId, CapabilityDefinition capability, ErrorType errorType, String message, long started) {
        return ExecutionResult.failure(
                traceId,
                capability.capabilityId(),
                capability.executor().type(),
                capability.executor().rfcName(),
                errorType,
                message,
                elapsedMs(started)
        );
    }

    private long elapsedMs(long started) {
        return (System.nanoTime() - started) / 1_000_000;
    }

    private String sanitize(String message) {
        if (message == null || message.isBlank()) {
            return "SAP JCo execution failed";
        }
        return message.replaceAll("(?i)(passwd|password)=\\S+", "$1=***");
    }
}
```

- [x] **Step 4: 修改 JcoRfcTechnicalAdapter 按 capabilityId 路由**

将 `services/gateway/core/src/main/java/com/sapnexus/gateway/execution/JcoRfcTechnicalAdapter.java` 改为:

```java
package com.sapnexus.gateway.execution;

import com.sapnexus.gateway.jco.JcoCapabilityExecutor;
import com.sapnexus.gateway.registry.CapabilityDefinition;
import com.sapnexus.gateway.registry.CapabilityRegistry;
import com.sapnexus.gateway.result.ExecutionResult;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;

@Component("JCO_RFC")
public class JcoRfcTechnicalAdapter implements TechnicalAdapter {
    private final List<JcoCapabilityExecutor> executors;
    private final CapabilityRegistry registry;

    public JcoRfcTechnicalAdapter(List<JcoCapabilityExecutor> executors, CapabilityRegistry registry) {
        this.executors = executors == null ? List.of() : executors;
        this.registry = registry;
    }

    @Override
    public TechnicalExecutionResult execute(TechnicalExecutionRequest request) {
        CapabilityDefinition capability = registry.findEnabled(request.capabilityId())
                .orElseThrow(() -> new IllegalStateException("Capability not found or disabled: " + request.capabilityId()));
        JcoCapabilityExecutor executor = selectExecutor(capability);
        ExecutionResult result = executor.execute(capability, request.parameters(), request.traceId());
        return TechnicalExecutionResult.fromExecutionResult(request.bindingId(), result);
    }

    private JcoCapabilityExecutor selectExecutor(CapabilityDefinition capability) {
        // Route by capabilityId; PR create uses dedicated write executor.
        if ("MM.PR.CreateDraft".equals(capability.capabilityId())) {
            return executors.stream()
                    .filter(e -> e instanceof com.sapnexus.gateway.jco.PrCreateDraftExecutor)
                    .findFirst()
                    .orElseThrow(() -> new IllegalStateException("PrCreateDraftExecutor not found"));
        }
        // Default: inventory availability (read path).
        return executors.stream()
                .filter(e -> e instanceof com.sapnexus.gateway.jco.InventoryAvailabilityExecutor)
                .findFirst()
                .orElseThrow(() -> new IllegalStateException("InventoryAvailabilityExecutor not found"));
    }
}
```

- [x] **Step 5: 运行测试确认通过**

Run: `cd services/gateway && ./gradlew :gateway-jco:test --tests PrCreateDraftExecutorTest`
Expected: PASS(3 个 commit/rollback 时序场景)

- [x] **Step 6: 运行 gateway 全量测试确认 read 路径无回归**

Run: `cd services/gateway && ./gradlew test`
Expected: PASS(现有 InventoryAvailabilityExecutor 测试仍通过)

- [x] **Step 7: Commit**

```bash
git add services/gateway/jco/src/main/java/com/sapnexus/gateway/jco/PrCreateDraftExecutor.java services/gateway/jco/src/test/java/com/sapnexus/gateway/jco/PrCreateDraftExecutorTest.java services/gateway/core/src/main/java/com/sapnexus/gateway/execution/JcoRfcTechnicalAdapter.java
git commit -m "feat(gateway): add PrCreateDraftExecutor with commit/rollback guard, route by capabilityId"
```

---

## Task 8: CapabilityController execute 入口插入 approval 守卫

**Files:**
- Modify: `services/gateway/core/src/main/java/com/sapnexus/gateway/api/CapabilityController.java`(execute 方法)
- Modify: `services/gateway/core/src/main/java/com/sapnexus/gateway/execution/TechnicalExecutionRequest.java`(增加 approvalId 字段)
- Test: `services/gateway/app/src/test/java/com/sapnexus/gateway/api/CapabilityWriteExecutionApiTest.java`

**Interfaces:**
- Consumes: `ApprovalGuard.check(record, hash, now)`、`ApprovalStore.find(approvalId)`
- Consumes: `CapabilityRequest` 中新增 `approvalId` 与 `parameterSnapshotHash` 字段
- Produces: execute 方法对 Action capability 先校验 approval,失败返回 ActionResult(fail-closed),不触发 SAP
- Produces: read capability(Function)跳过 approval 守卫

- [x] **Step 1: 写失败测试——approval 守卫四种拒绝场景 + read 路径跳过**

Create `services/gateway/app/src/test/java/com/sapnexus/gateway/api/CapabilityWriteExecutionApiTest.java`:

```java
package com.sapnexus.gateway.api;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Instant;
import java.util.List;
import java.util.Map;

import com.sapnexus.gateway.approval.ApprovalRecord;
import com.sapnexus.gateway.approval.ApprovalStore;
import com.sapnexus.gateway.approval.InMemoryApprovalStore;
import com.sapnexus.gateway.execution.TechnicalExecutionDispatcher;
import com.sapnexus.gateway.registry.CapabilityRegistry;
import com.sapnexus.gateway.registry.CapabilityRegistryLoader;
import com.sapnexus.gateway.result.ErrorType;
import com.sapnexus.gateway.trace.TraceWriter;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;

class CapabilityWriteExecutionApiTest {

    private ApprovalStore approvalStore;
    private CapabilityController controller;

    @BeforeEach
    void setUp() {
        approvalStore = new InMemoryApprovalStore();
        CapabilityRegistry registry = CapabilityRegistryLoader.load("registry/capabilities.yaml");
        TechnicalExecutionDispatcher dispatcher = new TechnicalExecutionDispatcher(Map.of());
        ObjectProvider<TraceWriter> traceProvider = org.mockito.Mockito.mock(ObjectProvider.class);
        controller = new CapabilityController(registry, dispatcher, traceProvider, approvalStore);
    }

    @Test
    void executeActionWithoutApprovalReturnsApprovalRequired() {
        CapabilityRequest request = new CapabilityRequest(
                Map.of("material", "M001", "plant", "1000", "quantity", "10", "unit", "EA", "delivery_date", "2026-08-01"),
                null,
                null,
                null
        );
        var response = controller.execute("MM.PR.CreateDraft", request);
        var body = (com.sapnexus.gateway.result.ExecutionResult) response.getBody();
        assertFalse(body.success());
        assertEquals(ErrorType.APPROVAL_REQUIRED, body.errorType());
    }

    @Test
    void executeActionWithExpiredApprovalReturnsExpired() {
        ApprovalRecord expired = new ApprovalRecord(
                "appr-001", "MM.PR.CreateDraft", "sha256:abc",
                Map.of("material", "M001"), "user", Instant.now().minusSeconds(700),
                Instant.now().minusSeconds(100), "approved"
        );
        approvalStore.save(expired);
        CapabilityRequest request = new CapabilityRequest(
                Map.of("material", "M001", "plant", "1000", "quantity", "10", "unit", "EA", "delivery_date", "2026-08-01"),
                "appr-001",
                "sha256:abc",
                null
        );
        var response = controller.execute("MM.PR.CreateDraft", request);
        var body = (com.sapnexus.gateway.result.ExecutionResult) response.getBody();
        assertEquals(ErrorType.APPROVAL_EXPIRED, body.errorType());
    }

    @Test
    void executeActionWithVersionMismatchReturnsMismatch() {
        ApprovalRecord approved = new ApprovalRecord(
                "appr-002", "MM.PR.CreateDraft", "sha256:original",
                Map.of("material", "M001"), "user", Instant.now(),
                Instant.now().plusSeconds(600), "approved"
        );
        approvalStore.save(approved);
        CapabilityRequest request = new CapabilityRequest(
                Map.of("material", "M001", "plant", "1000", "quantity", "10", "unit", "EA", "delivery_date", "2026-08-01"),
                "appr-002",
                "sha256:changed",
                null
        );
        var response = controller.execute("MM.PR.CreateDraft", request);
        var body = (com.sapnexus.gateway.result.ExecutionResult) response.getBody();
        assertEquals(ErrorType.APPROVAL_VERSION_MISMATCH, body.errorType());
    }

    @Test
    void executeActionDuplicateReturnsDuplicate() {
        ApprovalRecord executed = new ApprovalRecord(
                "appr-003", "MM.PR.CreateDraft", "sha256:abc",
                Map.of("material", "M001"), "user", Instant.now(),
                Instant.now().plusSeconds(600), "executed"
        );
        approvalStore.save(executed);
        CapabilityRequest request = new CapabilityRequest(
                Map.of("material", "M001", "plant", "1000", "quantity", "10", "unit", "EA", "delivery_date", "2026-08-01"),
                "appr-003",
                "sha256:abc",
                null
        );
        var response = controller.execute("MM.PR.CreateDraft", request);
        var body = (com.sapnexus.gateway.result.ExecutionResult) response.getBody();
        assertEquals(ErrorType.APPROVAL_DUPLICATE, body.errorType());
    }
}
```

- [x] **Step 2: 运行测试确认失败**

Run: `cd services/gateway && ./gradlew :gateway-app:test --tests CapabilityWriteExecutionApiTest`
Expected: FAIL(CapabilityController 构造函数未注入 ApprovalStore;CapabilityRequest 无 approvalId 字段)

- [x] **Step 3: 扩展 CapabilityRequest 支持 approvalId**

在 `services/gateway/core/src/main/java/com/sapnexus/gateway/api/CapabilityRequest.java` 中(现有 record),增加 `approvalId` 与 `parameterSnapshotHash` 字段。若该文件为 record,改为:

```java
package com.sapnexus.gateway.api;

import java.util.Map;
import java.util.Set;

public record CapabilityRequest(
        Map<String, Object> parameters,
        String approvalId,
        String parameterSnapshotHash,
        Map<String, Object> technicalOverrides
) {
    public CapabilityRequest(Map<String, Object> parameters) {
        this(parameters, null, null, null);
    }

    public Map<String, Object> safeParameters() {
        return parameters == null ? Map.of() : Map.copyOf(parameters);
    }

    public Set<String> technicalOverrideKeys() {
        return technicalOverrides == null ? Set.of() : technicalOverrides.keySet();
    }
}
```

注:需确认现有 `CapabilityRequest` 的实际字段名,以保持向后兼容。若现有字段不同,仅追加新字段 `approvalId`/`parameterSnapshotHash` 并保留原构造函数。

- [x] **Step 4: 修改 CapabilityController 注入 ApprovalStore 与 ApprovalGuard**

在 `services/gateway/core/src/main/java/com/sapnexus/gateway/api/CapabilityController.java` 中:

1. 构造函数增加 `ApprovalStore approvalStore` 与 `ApprovalGuard approvalGuard` 参数
2. execute 方法在 validation 通过后、dispatch 前插入 approval 守卫(仅 Action):

```java
// 在 validation 通过后
CapabilityDefinition capability = registry.findEnabled(capabilityId).orElseThrow();

// Approval guard: Action only, fail-closed before SAP
if (capability.kind() == CapabilityKind.Action) {
    String approvalId = request.approvalId();
    String parameterHash = request.parameterSnapshotHash();
    ApprovalRecord record = approvalId == null ? null : approvalStore.find(approvalId).orElse(null);
    ApprovalGuardResult guardResult = approvalGuard.check(record, parameterHash, Instant.now());
    if (guardResult.rejected()) {
        ExecutionResult rejection = ExecutionResult.failure(
                validation.traceId(),
                capabilityId,
                capability.executor().type(),
                capability.executor().rfcName(),
                guardResult.errorType(),
                guardResult.errorType().name(),
                0
        );
        writeTrace(rejection.traceId(), "execute", capabilityId, parameters, false, 0, rejection.errorType());
        return ResponseEntity.status(statusFor(rejection.errorType())).body(rejection);
    }
    // mark executed after successful dispatch (below)
}
```

3. dispatch 成功后,若为 Action,调用 `approvalStore.markExecuted(approvalId)`

增加 imports:
```java
import com.sapnexus.gateway.approval.ApprovalGuard;
import com.sapnexus.gateway.approval.ApprovalGuardResult;
import com.sapnexus.gateway.approval.ApprovalRecord;
import com.sapnexus.gateway.approval.ApprovalStore;
import com.sapnexus.gateway.registry.CapabilityKind;
import java.time.Instant;
```

- [x] **Step 5: 运行测试确认通过**

Run: `cd services/gateway && ./gradlew :gateway-app:test --tests CapabilityWriteExecutionApiTest`
Expected: PASS(4 个 approval 拒绝场景)

- [x] **Step 6: 运行 gateway 全量测试确认 read 路径无回归**

Run: `cd services/gateway && ./gradlew test`
Expected: PASS(现有 CapabilityExecutionApiTest、CapabilityValidationApiTest 仍通过)

- [x] **Step 7: Commit**

```bash
git add services/gateway/core/src/main/java/com/sapnexus/gateway/api/CapabilityController.java services/gateway/core/src/main/java/com/sapnexus/gateway/api/CapabilityRequest.java services/gateway/app/src/test/java/com/sapnexus/gateway/api/CapabilityWriteExecutionApiTest.java
git commit -m "feat(gateway): insert ApprovalGuard fail-closed at execute entry for Action capabilities"
```

---

## Task 9: READ/WRITE 路径隔离回归测试

**Files:**
- Test: `services/gateway/app/src/test/java/com/sapnexus/gateway/api/ReadWriteIsolationTest.java`

**Interfaces:**
- Produces: 隔离回归断言——Function execute 不调用 commit/rollback;Action execute 必经 approval 守卫

- [x] **Step 1: 写隔离回归测试**

Create `services/gateway/app/src/test/java/com/sapnexus/gateway/api/ReadWriteIsolationTest.java`:

```java
package com.sapnexus.gateway.api;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.Map;

import com.sapnexus.gateway.approval.ApprovalStore;
import com.sapnexus.gateway.approval.InMemoryApprovalStore;
import com.sapnexus.gateway.execution.TechnicalExecutionDispatcher;
import com.sapnexus.gateway.registry.CapabilityRegistry;
import com.sapnexus.gateway.registry.CapabilityRegistryLoader;
import com.sapnexus.gateway.result.ErrorType;
import com.sapnexus.gateway.trace.TraceWriter;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.ObjectProvider;

class ReadWriteIsolationTest {

    @Test
    void readPathSkipsApprovalGuard() {
        // Inventory (Function) should not require approvalId; validation proceeds.
        // This test asserts that Function capabilities bypass the approval guard
        // and reach validation (which may fail due to mock dispatcher, but NOT with APPROVAL_*).
        ApprovalStore approvalStore = new InMemoryApprovalStore();
        CapabilityRegistry registry = CapabilityRegistryLoader.load("registry/capabilities.yaml");
        TechnicalExecutionDispatcher dispatcher = new TechnicalExecutionDispatcher(Map.of());
        ObjectProvider<TraceWriter> traceProvider = org.mockito.Mockito.mock(ObjectProvider.class);
        CapabilityController controller = new CapabilityController(registry, dispatcher, traceProvider, approvalStore);

        CapabilityRequest request = new CapabilityRequest(
                Map.of("material", "M001", "plant", "1000"),
                null,
                null,
                null
        );
        var response = controller.execute("MM.Inventory.GetAvailability", request);
        var body = (com.sapnexus.gateway.result.ExecutionResult) response.getBody();
        // Function path does not return APPROVAL_REQUIRED even without approvalId
        assertTrue(body.errorType() != ErrorType.APPROVAL_REQUIRED
                && body.errorType() != ErrorType.APPROVAL_EXPIRED
                && body.errorType() != ErrorType.APPROVAL_VERSION_MISMATCH
                && body.errorType() != ErrorType.APPROVAL_DUPLICATE,
                "Function path must not trigger approval guard, got: " + body.errorType());
    }

    @Test
    void writePathBlocksWithoutApproval() {
        ApprovalStore approvalStore = new InMemoryApprovalStore();
        CapabilityRegistry registry = CapabilityRegistryLoader.load("registry/capabilities.yaml");
        TechnicalExecutionDispatcher dispatcher = new TechnicalExecutionDispatcher(Map.of());
        ObjectProvider<TraceWriter> traceProvider = org.mockito.Mockito.mock(ObjectProvider.class);
        CapabilityController controller = new CapabilityController(registry, dispatcher, traceProvider, approvalStore);

        CapabilityRequest request = new CapabilityRequest(
                Map.of("material", "M001", "plant", "1000", "quantity", "10", "unit", "EA", "delivery_date", "2026-08-01"),
                null,
                null,
                null
        );
        var response = controller.execute("MM.PR.CreateDraft", request);
        var body = (com.sapnexus.gateway.result.ExecutionResult) response.getBody();
        assertEquals(ErrorType.APPROVAL_REQUIRED, body.errorType());
    }
}
```

- [x] **Step 2: 运行测试确认通过**

Run: `cd services/gateway && ./gradlew :gateway-app:test --tests ReadWriteIsolationTest`
Expected: PASS

- [x] **Step 3: Commit**

```bash
git add services/gateway/app/src/test/java/com/sapnexus/gateway/api/ReadWriteIsolationTest.java
git commit -m "test(gateway): add READ/WRITE path isolation regression tests"
```

---

## Task 10: Agent approval.py 状态机 + 参数快照 hash

**Files:**
- Create: `agent/sap_nexus_agent/approval.py`
- Test: `agent/tests/test_approval.py`

**Interfaces:**
- Produces: `ApprovalState` 枚举(pending/approved/executed/rejected)
- Produces: `ApprovalRecord` dataclass(approvalId/capabilityId/parameterSnapshotHash/parameters/approver/approvedAt/expiresAt/status)
- Produces: `compute_parameter_hash(parameters: dict) -> str`(sha256)
- Produces: `create_approval_record(capability_id, parameters, approver, ttl_seconds) -> ApprovalRecord`
- Produces: `is_expired(record, now) -> bool`

- [x] **Step 1: 写失败测试——状态机与 hash**

Create `agent/tests/test_approval.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sap_nexus_agent.approval import (
    ApprovalRecord,
    ApprovalState,
    compute_parameter_hash,
    create_approval_record,
    is_expired,
)


def test_compute_parameter_hash_is_deterministic():
    params = {"material": "M001", "plant": "1000", "quantity": "10"}
    hash1 = compute_parameter_hash(params)
    hash2 = compute_parameter_hash(params)
    assert hash1 == hash2
    assert hash1.startswith("sha256:")


def test_compute_parameter_hash_differs_on_change():
    base = {"material": "M001", "plant": "1000"}
    changed = {"material": "M002", "plant": "1000"}
    assert compute_parameter_hash(base) != compute_parameter_hash(changed)


def test_create_approval_record_sets_pending_then_approved():
    params = {"material": "M001", "plant": "1000", "quantity": "10", "unit": "EA", "delivery_date": "2026-08-01"}
    record = create_approval_record(
        capability_id="MM.PR.CreateDraft",
        parameters=params,
        approver="user@example.com",
        ttl_seconds=600,
    )
    assert record.capability_id == "MM.PR.CreateDraft"
    assert record.parameter_snapshot_hash.startswith("sha256:")
    assert record.status == ApprovalState.approved
    assert record.approver == "user@example.com"


def test_is_expired_true_after_ttl():
    now = datetime(2026, 7, 16, 10, 11, 0, tzinfo=timezone.utc)
    record = ApprovalRecord(
        approval_id="appr-001",
        capability_id="MM.PR.CreateDraft",
        parameter_snapshot_hash="sha256:abc",
        parameters={"material": "M001"},
        approver="user",
        approved_at=datetime(2026, 7, 16, 10, 0, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 7, 16, 10, 10, 0, tzinfo=timezone.utc),
        status=ApprovalState.approved,
    )
    assert is_expired(record, now) is True


def test_is_expired_false_within_ttl():
    now = datetime(2026, 7, 16, 10, 5, 0, tzinfo=timezone.utc)
    record = ApprovalRecord(
        approval_id="appr-001",
        capability_id="MM.PR.CreateDraft",
        parameter_snapshot_hash="sha256:abc",
        parameters={"material": "M001"},
        approver="user",
        approved_at=datetime(2026, 7, 16, 10, 0, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 7, 16, 10, 10, 0, tzinfo=timezone.utc),
        status=ApprovalState.approved,
    )
    assert is_expired(record, now) is False
```

- [x] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest agent/tests/test_approval.py -v`
Expected: FAIL(模块不存在)

- [x] **Step 3: 创建 approval.py**

Create `agent/sap_nexus_agent/approval.py`:

```python
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ApprovalState(str, Enum):
    pending = "pending"
    approved = "approved"
    executed = "executed"
    rejected = "rejected"


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    capability_id: str
    parameter_snapshot_hash: str
    parameters: dict[str, str]
    approver: str
    approved_at: datetime
    expires_at: datetime
    status: ApprovalState

    def to_dict(self) -> dict[str, Any]:
        return {
            "approvalId": self.approval_id,
            "capabilityId": self.capability_id,
            "parameterSnapshotHash": self.parameter_snapshot_hash,
            "parameters": dict(self.parameters),
            "approver": self.approver,
            "approvedAt": self.approved_at.isoformat(),
            "expiresAt": self.expires_at.isoformat(),
            "status": self.status.value,
        }


def compute_parameter_hash(parameters: dict[str, str]) -> str:
    canonical = json.dumps(parameters, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def create_approval_record(
    capability_id: str,
    parameters: dict[str, str],
    approver: str,
    ttl_seconds: int = 600,
) -> ApprovalRecord:
    now = datetime.now(timezone.utc)
    return ApprovalRecord(
        approval_id=f"appr-{uuid.uuid4()}",
        capability_id=capability_id,
        parameter_snapshot_hash=compute_parameter_hash(parameters),
        parameters=dict(parameters),
        approver=approver,
        approved_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
        status=ApprovalState.approved,
    )


def is_expired(record: ApprovalRecord, now: datetime) -> bool:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now > record.expires_at
```

注:需在文件顶部增加 `from datetime import timedelta` import。修正为:

```python
from datetime import datetime, timedelta, timezone
```

- [x] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest agent/tests/test_approval.py -v`
Expected: PASS(5 个 case)

- [x] **Step 5: Commit**

```bash
git add agent/sap_nexus_agent/approval.py agent/tests/test_approval.py
git commit -m "feat(agent): add approval state machine, parameter snapshot hash, TTL logic"
```

---

## Task 11: Agent action_result.py 解析 Gateway write 返回

**Files:**
- Create: `agent/sap_nexus_agent/action_result.py`
- Test: `agent/tests/test_action_result.py`

**Interfaces:**
- Produces: `ActionResult` dataclass(trace_id/capability_id/success/pr_number/commit_status/return_messages/duration_ms/error_type)
- Produces: `ActionResult.from_dict(payload)` 工厂

- [x] **Step 1: 写失败测试——解析成功与失败 payload**

Create `agent/tests/test_action_result.py`:

```python
from __future__ import annotations

from sap_nexus_agent.action_result import ActionResult


def test_from_dict_success():
    payload = {
        "traceId": "trace-001",
        "capabilityId": "MM.PR.CreateDraft",
        "success": True,
        "prNumber": "0010001234",
        "commitStatus": "committed",
        "returnMessages": [],
        "durationMs": 150,
        "errorType": "NONE",
    }
    result = ActionResult.from_dict(payload)
    assert result.success is True
    assert result.pr_number == "0010001234"
    assert result.commit_status == "committed"
    assert result.error_type == "NONE"


def test_from_dict_approval_required():
    payload = {
        "traceId": "trace-002",
        "capabilityId": "MM.PR.CreateDraft",
        "success": False,
        "prNumber": "",
        "commitStatus": "none",
        "returnMessages": [],
        "durationMs": 1,
        "errorType": "APPROVAL_REQUIRED",
    }
    result = ActionResult.from_dict(payload)
    assert result.success is False
    assert result.pr_number == ""
    assert result.commit_status == "none"
    assert result.error_type == "APPROVAL_REQUIRED"


def test_from_dict_sap_business_error_rolled_back():
    payload = {
        "traceId": "trace-003",
        "capabilityId": "MM.PR.CreateDraft",
        "success": False,
        "prNumber": "",
        "commitStatus": "rolled_back",
        "returnMessages": [{"type": "E", "message": "Material not found"}],
        "durationMs": 80,
        "errorType": "SAP_BUSINESS_ERROR",
    }
    result = ActionResult.from_dict(payload)
    assert result.success is False
    assert result.commit_status == "rolled_back"
    assert result.error_type == "SAP_BUSINESS_ERROR"
    assert len(result.return_messages) == 1
```

- [x] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest agent/tests/test_action_result.py -v`
Expected: FAIL(模块不存在)

- [x] **Step 3: 创建 action_result.py**

Create `agent/sap_nexus_agent/action_result.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ActionResult:
    trace_id: str
    capability_id: str
    success: bool
    pr_number: str
    commit_status: str
    return_messages: list[dict[str, Any]]
    duration_ms: int
    error_type: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ActionResult":
        return cls(
            trace_id=str(payload.get("traceId", "")),
            capability_id=str(payload.get("capabilityId", "")),
            success=bool(payload.get("success", False)),
            pr_number=str(payload.get("prNumber", "")),
            commit_status=str(payload.get("commitStatus", "none")),
            return_messages=[dict(msg) for msg in payload.get("returnMessages", [])],
            duration_ms=int(payload.get("durationMs", 0)),
            error_type=str(payload.get("errorType", "UNKNOWN")),
        )
```

- [x] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest agent/tests/test_action_result.py -v`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add agent/sap_nexus_agent/action_result.py agent/tests/test_action_result.py
git commit -m "feat(agent): add ActionResult parser for Gateway write responses"
```

---

## Task 12: Agent pr_intent.py——PR create intent 解析与条件必填

**Files:**
- Create: `agent/sap_nexus_agent/pr_intent.py`
- Test: `agent/tests/test_pr_intent.py`

**Interfaces:**
- Produces: `parse_pr_create_intent(text) -> IntentParseResult`(复用现有 IntentParseResult)
- Produces: 缺参澄清(material/plant/quantity/unit/delivery_date)
- Produces: 条件必填校验(acct_assgn_cat="K" 时缺 cost_center 触发澄清)

- [x] **Step 1: 写失败测试——缺参澄清与条件必填**

Create `agent/tests/test_pr_intent.py`:

```python
from __future__ import annotations

from sap_nexus_agent.pr_intent import parse_pr_create_intent


def test_full_direct_pr_create():
    text = "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01"
    result = parse_pr_create_intent(text)
    assert result.intent == "pr_create"
    assert result.parameters.get("material") == "M001"
    assert result.parameters.get("plant") == "1000"
    assert result.parameters.get("quantity") == "100"
    assert result.parameters.get("unit") == "EA"
    assert result.parameters.get("delivery_date") == "2026-08-01"
    assert result.missing_parameters == []


def test_missing_required_params_triggers_clarification():
    text = "建个采购申请"
    result = parse_pr_create_intent(text)
    assert result.intent == "pr_create"
    assert "material" in result.missing_parameters
    assert "plant" in result.missing_parameters
    assert "quantity" in result.missing_parameters
    assert result.clarification is not None


def test_indirect_missing_cost_center_triggers_clarification():
    text = "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01 间采 K"
    result = parse_pr_create_intent(text)
    assert result.parameters.get("acct_assgn_cat") == "K"
    assert "cost_center" in result.missing_parameters
    assert result.clarification is not None
    assert "成本中心" in result.clarification


def test_indirect_with_cost_center_no_missing():
    text = "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01 间采 K 成本中心 1000"
    result = parse_pr_create_intent(text)
    assert result.parameters.get("acct_assgn_cat") == "K"
    assert result.parameters.get("cost_center") == "1000"
    assert "cost_center" not in result.missing_parameters
```

- [x] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest agent/tests/test_pr_intent.py -v`
Expected: FAIL(模块不存在)

- [x] **Step 3: 创建 pr_intent.py**

Create `agent/sap_nexus_agent/pr_intent.py`:

```python
from __future__ import annotations

import re

from sap_nexus_agent.intent import IntentParseResult


PR_CREATE_KEYWORDS = ("采购申请", "建PR", "建 PR", "创建PR", "创建 PR", "PR草稿", "PR 草稿")
MATERIAL_PATTERN = re.compile(r"物料\s*([A-Za-z0-9][A-Za-z0-9\-/]+)")
PLANT_PATTERN = re.compile(r"(?:工厂\s*(\d{4}|[A-Z]\d{3}))|(?:(\d{4}|[A-Z]\d{3})\s*工厂)")
QUANTITY_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:EA|PC|KG|G|L|M)", re.IGNORECASE)
UNIT_PATTERN = re.compile(r"\b(EA|PC|KG|G|L|M)\b", re.IGNORECASE)
DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")
ACCT_ASSGN_CAT_PATTERN = re.compile(r"(?:间采|账号分配)\s*[Kk]")
COST_CENTER_PATTERN = re.compile(r"成本中心\s*(\d+)")

REQUIRED_FIELDS = ("material", "plant", "quantity", "unit", "delivery_date")


def parse_pr_create_intent(text: str) -> IntentParseResult:
    normalized = text.strip()

    parameters: dict[str, str] = {}

    material_match = MATERIAL_PATTERN.search(normalized)
    if material_match:
        parameters["material"] = material_match.group(1)

    plant_match = PLANT_PATTERN.search(normalized)
    if plant_match:
        parameters["plant"] = plant_match.group(1) or plant_match.group(2)

    quantity_match = QUANTITY_PATTERN.search(normalized)
    if quantity_match:
        parameters["quantity"] = quantity_match.group(1)

    unit_match = UNIT_PATTERN.search(normalized)
    if unit_match:
        parameters["unit"] = unit_match.group(1).upper()

    date_match = DATE_PATTERN.search(normalized)
    if date_match:
        parameters["delivery_date"] = date_match.group(1)

    acct_match = ACCT_ASSGN_CAT_PATTERN.search(normalized)
    if acct_match:
        parameters["acct_assgn_cat"] = "K"

    if parameters.get("acct_assgn_cat") == "K":
        cost_center_match = COST_CENTER_PATTERN.search(normalized)
        if cost_center_match:
            parameters["cost_center"] = cost_center_match.group(1)

    missing = [field for field in REQUIRED_FIELDS if field not in parameters]
    if parameters.get("acct_assgn_cat") == "K" and "cost_center" not in parameters:
        missing.append("cost_center")

    clarification = _build_clarification(missing)

    return IntentParseResult(
        intent="pr_create",
        parameters=parameters,
        missing_parameters=missing,
        clarification=clarification,
        contains_rfc_name=False,
        contains_odata_override=False,
        capability_id="MM.PR.CreateDraft",
    )


def _build_clarification(missing: list[str]) -> str | None:
    if not missing:
        return None
    parts = []
    field_names = {
        "material": "物料编号",
        "plant": "工厂",
        "quantity": "数量",
        "unit": "单位",
        "delivery_date": "交货日期",
        "cost_center": "成本中心(间采 PR 需提供)",
    }
    for field in missing:
        if field in field_names:
            parts.append(field_names[field])
    if parts:
        return f"请提供: {', '.join(parts)}"
    return None
```

- [x] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest agent/tests/test_pr_intent.py -v`
Expected: PASS(4 个 case)

- [x] **Step 5: Commit**

```bash
git add agent/sap_nexus_agent/pr_intent.py agent/tests/test_pr_intent.py
git commit -m "feat(agent): add PR create intent parser with conditional required field validation"
```

---

## Task 13: Agent call_plan.py 与 capability_selector.py 扩展 Action 语义

**Files:**
- Modify: `agent/sap_nexus_agent/call_plan.py`(create_call_plan 支持 kind=Action)
- Modify: `agent/sap_nexus_agent/capability_selector.py`(INTENT_TO_CAPABILITY 增加 pr_create)
- Test: `agent/tests/test_orchestrator.py`(现有,追加 Action call_plan 断言)

**Interfaces:**
- Produces: `create_call_plan(capability_id, parameters, kind="Function")` 支持 kind=Action + requires_approval=True
- Produces: `INTENT_TO_CAPABILITY["pr_create"] = "MM.PR.CreateDraft"`

- [x] **Step 1: 写失败测试——Action call_plan**

在 `agent/tests/test_orchestrator.py` 追加(或新建 `agent/tests/test_call_plan_action.py`):

```python
from __future__ import annotations

from sap_nexus_agent.call_plan import create_call_plan


def test_action_call_plan_sets_kind_and_approval():
    plan = create_call_plan(
        "MM.PR.CreateDraft",
        {"material": "M001", "plant": "1000"},
        kind="Action",
    )
    assert plan.kind == "Action"
    assert plan.requires_approval is True
    assert plan.capability_id == "MM.PR.CreateDraft"


def test_function_call_plan_remains_default():
    plan = create_call_plan(
        "MM.Inventory.GetAvailability",
        {"material": "M001", "plant": "1000"},
    )
    assert plan.kind == "Function"
    assert plan.requires_approval is False
```

- [x] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest agent/tests/test_call_plan_action.py -v`
Expected: FAIL(create_call_plan 不接受 kind 参数)

- [x] **Step 3: 修改 call_plan.py**

将 `agent/sap_nexus_agent/call_plan.py` 的 `create_call_plan` 改为:

```python
def create_call_plan(
    capability_id: str,
    parameters: dict[str, str],
    *,
    kind: str = "Function",
) -> CallPlan:
    normalized_parameters = dict(parameters)
    requires_approval = kind == "Action"
    return CallPlan(
        agent_trace_id=f"agent-{uuid.uuid4()}",
        capability_id=capability_id,
        kind=kind,
        parameters=normalized_parameters,
        validation_policy="validate_before_execute",
        created_by="agent",
        requires_approval=requires_approval,
    )
```

- [x] **Step 4: 修改 capability_selector.py 增加 pr_create 映射**

在 `agent/sap_nexus_agent/capability_selector.py` 的 `INTENT_TO_CAPABILITY` 字典增加:

```python
INTENT_TO_CAPABILITY = {
    "inventory_availability": "MM.Inventory.GetAvailability",
    "purchase_order_list": "MM.PurchaseOrder.GetList",
    "pr_create": "MM.PR.CreateDraft",
}
```

- [x] **Step 5: 运行测试确认通过**

Run: `.venv/bin/python -m pytest agent/tests/test_call_plan_action.py -v`
Expected: PASS

- [x] **Step 6: 运行现有 orchestrator 测试确认无回归**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py -v`
Expected: PASS(现有 Function 路径不受影响)

- [x] **Step 7: Commit**

```bash
git add agent/sap_nexus_agent/call_plan.py agent/sap_nexus_agent/capability_selector.py agent/tests/test_call_plan_action.py
git commit -m "feat(agent): extend call_plan for Action kind, add pr_create capability mapping"
```

---

## Task 14: Agent orchestrator.py 串联 write 路径

**Files:**
- Modify: `agent/sap_nexus_agent/orchestrator.py`(run_query 增加 Action 分支)
- Modify: `agent/sap_nexus_agent/intent.py`(parse_intent 增加 PR create 关键词)
- Modify: `agent/sap_nexus_agent/gateway_client.py`(execute 传递 approvalId)
- Test: `agent/tests/test_orchestrator_write.py`

**Interfaces:**
- Consumes: `parse_pr_create_intent`、`create_approval_record`、`create_call_plan(kind="Action")`、`ActionResult.from_dict`
- Produces: `run_query` 对 pr_create intent 走 Action 路径:缺参澄清 -> 生成 ApprovalRecord -> gateway.execute(approvalId) -> ActionResult -> narrate
- Produces: `GatewayClient.execute` 支持 `approval_id` 参数

- [x] **Step 1: 写失败测试——write 路径缺参澄清与 approval 流转**

Create `agent/tests/test_orchestrator_write.py`:

```python
from __future__ import annotations

from sap_nexus_agent.orchestrator import run_query


class StubWriteGateway:
    def __init__(self, execute_payload: dict):
        self._execute_payload = execute_payload
        self.validate_calls: list = []
        self.execute_calls: list = []

    def validate(self, capability_id: str, parameters: dict[str, str]):
        self.validate_calls.append((capability_id, dict(parameters)))
        from sap_nexus_agent.execution_result import ValidationResult
        return ValidationResult(
            trace_id="trace-val",
            capability_id=capability_id,
            success=True,
            error_type="NONE",
            messages=[],
        )

    def execute(self, capability_id: str, parameters: dict[str, str], approval_id: str | None = None):
        self.execute_calls.append((capability_id, dict(parameters), approval_id))
        from sap_nexus_agent.action_result import ActionResult
        return ActionResult.from_dict(self._execute_payload)


def test_pr_create_missing_params_returns_clarification():
    gateway = StubWriteGateway({})
    outcome = run_query("建个采购申请", gateway)
    assert outcome.status == "clarification"
    assert "material" in (outcome.missing_parameters or [])
    assert len(gateway.execute_calls) == 0


def test_pr_create_success_returns_pr_number():
    execute_payload = {
        "traceId": "trace-001",
        "capabilityId": "MM.PR.CreateDraft",
        "success": True,
        "prNumber": "0010001234",
        "commitStatus": "committed",
        "returnMessages": [],
        "durationMs": 150,
        "errorType": "NONE",
    }
    gateway = StubWriteGateway(execute_payload)
    outcome = run_query(
        "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01",
        gateway,
    )
    assert outcome.status == "success"
    assert len(gateway.execute_calls) == 1
    capability_id, params, approval_id = gateway.execute_calls[0]
    assert capability_id == "MM.PR.CreateDraft"
    assert approval_id is not None
    assert approval_id.startswith("appr-")


def test_pr_create_sap_error_returns_failure():
    execute_payload = {
        "traceId": "trace-002",
        "capabilityId": "MM.PR.CreateDraft",
        "success": False,
        "prNumber": "",
        "commitStatus": "rolled_back",
        "returnMessages": [{"type": "E", "message": "Material not found"}],
        "durationMs": 80,
        "errorType": "SAP_BUSINESS_ERROR",
    }
    gateway = StubWriteGateway(execute_payload)
    outcome = run_query(
        "给物料 INVALID 工厂 1000 建 100 EA 采购申请 交货 2026-08-01",
        gateway,
    )
    assert outcome.status == "failure"
    assert outcome.error_type == "SAP_BUSINESS_ERROR"


def test_pr_create_approval_required_returns_failure():
    execute_payload = {
        "traceId": "trace-003",
        "capabilityId": "MM.PR.CreateDraft",
        "success": False,
        "prNumber": "",
        "commitStatus": "none",
        "returnMessages": [],
        "durationMs": 1,
        "errorType": "APPROVAL_REQUIRED",
    }
    gateway = StubWriteGateway(execute_payload)
    outcome = run_query(
        "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01",
        gateway,
    )
    assert outcome.status == "failure"
    assert outcome.error_type == "APPROVAL_REQUIRED"
```

- [x] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator_write.py -v`
Expected: FAIL(orchestrator 未处理 pr_create intent)

- [x] **Step 3: 修改 intent.py 增加 PR create 关键词**

在 `agent/sap_nexus_agent/intent.py` 的 `parse_intent` 函数中,在 purchase_order 分支后增加 PR create 分支。在文件顶部增加 import:

```python
from sap_nexus_agent.pr_intent import parse_pr_create_intent, PR_CREATE_KEYWORDS
```

在 `parse_intent` 函数中,`_PURCHASE_ORDER_KEYWORD_PATTERN.search` 分支后增加:

```python
    if any(keyword in normalized for keyword in PR_CREATE_KEYWORDS):
        return parse_pr_create_intent(normalized)
```

- [x] **Step 4: 修改 gateway_client.py execute 支持 approval_id**

将 `agent/sap_nexus_agent/gateway_client.py` 的 `GatewayClientProtocol.execute` 与 `GatewayClient.execute` 改为:

```python
class GatewayClientProtocol(Protocol):
    def validate(self, capability_id: str, parameters: dict[str, str]) -> ValidationResult:
        ...

    def execute(
        self,
        capability_id: str,
        parameters: dict[str, str],
        approval_id: str | None = None,
    ) -> ExecutionResult:
        ...
```

`GatewayClient.execute` 实现:

```python
    def execute(
        self,
        capability_id: str,
        parameters: dict[str, str],
        approval_id: str | None = None,
    ) -> ExecutionResult:
        payload = self._post(f"/capabilities/{capability_id}/execute", parameters, approval_id)
        return ExecutionResult.from_dict(payload)
```

`_post` 增加 approval_id 参数,将其加入 request body:

```python
    def _post(self, path: str, parameters: dict[str, str], approval_id: str | None = None) -> dict[str, object]:
        body_dict: dict[str, object] = {"parameters": dict(parameters)}
        if approval_id is not None:
            body_dict["approvalId"] = approval_id
        body = json.dumps(body_dict).encode("utf-8")
        # ... rest unchanged
```

- [x] **Step 5: 修改 orchestrator.py run_query 增加 Action 分支**

在 `agent/sap_nexus_agent/orchestrator.py` 的 `run_query` 中,在 `selected.capability_id == INVENTORY_CAPABILITY_ID` 分支后增加 Action 分支。增加 imports:

```python
from sap_nexus_agent.action_result import ActionResult
from sap_nexus_agent.approval import create_approval_record
```

在 `run_query` 中,validation 通过后、execute 前,增加:

```python
    is_action = call_plan.kind == "Action"
    approval_id = None
    if is_action:
        approval = create_approval_record(
            capability_id=call_plan.capability_id,
            parameters=call_plan.parameters,
            approver="user",
        )
        approval_id = approval.approval_id

    execution = gateway.execute(call_plan.capability_id, call_plan.parameters, approval_id=approval_id)
    if not execution.success:
        messages = [_message_text(message) for message in execution.return_messages]
        return AgentOutcome(
            status="failure",
            message="Gateway execute failed",
            response_text=narrate_failure(execution.error_type, messages),
            call_plan=call_plan,
            validation_result=validation,
            execution_result=execution,
            gateway_trace_id=execution.trace_id,
            error_type=execution.error_type,
        )

    if is_action:
        return _finalize_pr_create(call_plan, validation, execution)

    if selected.capability_id == INVENTORY_CAPABILITY_ID:
        return _finalize_inventory(call_plan, validation, execution)
    return _finalize_purchase_order(call_plan, validation, execution)
```

增加 `_finalize_pr_create` 函数:

```python
def _finalize_pr_create(
    call_plan: CallPlan,
    validation: ValidationResult,
    execution: ExecutionResult,
) -> AgentOutcome:
    pr_number = execution.data.get("prNumber", "")
    response_text = f"采购申请创建成功,PR 号: {pr_number}" if pr_number else "采购请求创建成功但未返回 PR 号。"
    return AgentOutcome(
        status="success",
        response_text=response_text,
        call_plan=call_plan,
        validation_result=validation,
        execution_result=execution,
        gateway_trace_id=execution.trace_id,
    )
```

注:`ExecutionResult` 已有 `data` 字段,`prNumber` 在 `data` 中;但 write 路径返回 `ActionResult` 结构。需确认 `gateway.execute` 返回类型——由于 `ExecutionResult.from_dict` 忽略未知字段,write 返回的 `prNumber` 顶层字段不会进入 `data`。需在 `gateway_client.py` 中将 write 返回的 `prNumber` 注入 `data`,或使用 `ActionResult` 单独解析。

修正方案:在 `gateway_client.py` 增加 `execute_write` 方法返回 `ActionResult`,或在 orchestrator 中用 `ActionResult.from_dict` 解析。最简方案:orchestrator 对 Action 路径使用 `ActionResult.from_dict(execution_payload)`——但 `gateway.execute` 已返回 `ExecutionResult`。

**采用方案**:扩展 `ExecutionResult.from_dict` 使其将顶层 `prNumber`/`commitStatus` 吸收到 `data` 字典中。在 `execution_result.py` 的 `from_dict` 方法增加:

```python
    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExecutionResult":
        data = dict(payload.get("data") or {})
        # Absorb write-path top-level fields into data for unified access
        if "prNumber" in payload:
            data["prNumber"] = payload["prNumber"]
        if "commitStatus" in payload:
            data["commitStatus"] = payload["commitStatus"]
        return cls(
            trace_id=str(payload.get("traceId", "")),
            capability_id=str(payload.get("capabilityId", "")),
            success=bool(payload.get("success", False)),
            executor=dict(payload.get("executor") or {}),
            return_messages=[dict(message) for message in payload.get("returnMessages", [])],
            data=data,
            duration_ms=int(payload.get("durationMs", 0)),
            error_type=str(payload.get("errorType", "UNKNOWN")),
        )
```

- [x] **Step 6: 运行测试确认通过**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator_write.py -v`
Expected: PASS(4 个 case)

- [x] **Step 7: 运行现有 orchestrator 测试确认无回归**

Run: `.venv/bin/python -m pytest agent/tests/test_orchestrator.py agent/tests/test_intent.py -v`
Expected: PASS

- [x] **Step 8: Commit**

```bash
git add agent/sap_nexus_agent/orchestrator.py agent/sap_nexus_agent/intent.py agent/sap_nexus_agent/gateway_client.py agent/sap_nexus_agent/execution_result.py agent/tests/test_orchestrator_write.py
git commit -m "feat(agent): wire orchestrator write path with approval state machine and ActionResult"
```

---

## Task 15: Eval 写入回归集 pr_create_cases.json

**Files:**
- Modify: `evals/pr_create_cases.json`(替换 Task 2 的占位内容)
- Modify: `scripts/verify-agent-callplan-evidence.sh`(增加 pr_create 回归行)
- Test: `agent/tests/test_eval_runner.py`(现有,确认新 eval 文件可运行)

**Interfaces:**
- Produces: 9 个 eval case(pr-create-success-direct/indirect/missing-param/indirect-missing-cost-center/approval-missing/expired/version-mismatch/duplicate-submit/sap-business-error)

- [x] **Step 1: 写完整 eval case 文件**

Replace `evals/pr_create_cases.json` with:

```json
{
  "cases": [
    {
      "id": "pr-create-success-direct",
      "userQuery": "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01",
      "gateway": {
        "execute": {
          "traceId": "trace-success-direct",
          "capabilityId": "MM.PR.CreateDraft",
          "success": true,
          "prNumber": "0010001234",
          "commitStatus": "committed",
          "returnMessages": [],
          "durationMs": 150,
          "errorType": "NONE"
        }
      },
      "expected": {
        "status": "success",
        "capabilityId": "MM.PR.CreateDraft",
        "validateCalls": 1,
        "executeCalls": 1,
        "responseContains": ["0010001234"]
      }
    },
    {
      "id": "pr-create-success-indirect",
      "userQuery": "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01 间采 K 成本中心 1000",
      "gateway": {
        "execute": {
          "traceId": "trace-success-indirect",
          "capabilityId": "MM.PR.CreateDraft",
          "success": true,
          "prNumber": "0010001235",
          "commitStatus": "committed",
          "returnMessages": [],
          "durationMs": 160,
          "errorType": "NONE"
        }
      },
      "expected": {
        "status": "success",
        "capabilityId": "MM.PR.CreateDraft",
        "validateCalls": 1,
        "executeCalls": 1,
        "responseContains": ["0010001235"]
      }
    },
    {
      "id": "pr-create-missing-param",
      "userQuery": "建个采购申请",
      "expected": {
        "status": "clarification",
        "missingParameters": ["material", "plant", "quantity", "unit", "delivery_date"],
        "validateCalls": 0,
        "executeCalls": 0
      }
    },
    {
      "id": "pr-create-indirect-missing-cost-center",
      "userQuery": "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01 间采 K",
      "expected": {
        "status": "clarification",
        "missingParameters": ["cost_center"],
        "validateCalls": 0,
        "executeCalls": 0
      }
    },
    {
      "id": "pr-create-approval-missing",
      "userQuery": "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01",
      "gateway": {
        "execute": {
          "traceId": "trace-approval-missing",
          "capabilityId": "MM.PR.CreateDraft",
          "success": false,
          "prNumber": "",
          "commitStatus": "none",
          "returnMessages": [],
          "durationMs": 1,
          "errorType": "APPROVAL_REQUIRED"
        }
      },
      "expected": {
        "status": "failure",
        "errorType": "APPROVAL_REQUIRED",
        "validateCalls": 1,
        "executeCalls": 1
      }
    },
    {
      "id": "pr-create-approval-expired",
      "userQuery": "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01",
      "gateway": {
        "execute": {
          "traceId": "trace-approval-expired",
          "capabilityId": "MM.PR.CreateDraft",
          "success": false,
          "prNumber": "",
          "commitStatus": "none",
          "returnMessages": [],
          "durationMs": 1,
          "errorType": "APPROVAL_EXPIRED"
        }
      },
      "expected": {
        "status": "failure",
        "errorType": "APPROVAL_EXPIRED",
        "validateCalls": 1,
        "executeCalls": 1
      }
    },
    {
      "id": "pr-create-approval-version-mismatch",
      "userQuery": "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01",
      "gateway": {
        "execute": {
          "traceId": "trace-version-mismatch",
          "capabilityId": "MM.PR.CreateDraft",
          "success": false,
          "prNumber": "",
          "commitStatus": "none",
          "returnMessages": [],
          "durationMs": 1,
          "errorType": "APPROVAL_VERSION_MISMATCH"
        }
      },
      "expected": {
        "status": "failure",
        "errorType": "APPROVAL_VERSION_MISMATCH",
        "validateCalls": 1,
        "executeCalls": 1
      }
    },
    {
      "id": "pr-create-duplicate-submit",
      "userQuery": "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01",
      "gateway": {
        "execute": {
          "traceId": "trace-duplicate",
          "capabilityId": "MM.PR.CreateDraft",
          "success": false,
          "prNumber": "",
          "commitStatus": "none",
          "returnMessages": [],
          "durationMs": 1,
          "errorType": "APPROVAL_DUPLICATE"
        }
      },
      "expected": {
        "status": "failure",
        "errorType": "APPROVAL_DUPLICATE",
        "validateCalls": 1,
        "executeCalls": 1
      }
    },
    {
      "id": "pr-create-sap-business-error",
      "userQuery": "给物料 INVALID 工厂 1000 建 100 EA 采购申请 交货 2026-08-01",
      "gateway": {
        "execute": {
          "traceId": "trace-sap-error",
          "capabilityId": "MM.PR.CreateDraft",
          "success": false,
          "prNumber": "",
          "commitStatus": "rolled_back",
          "returnMessages": [{"type": "E", "message": "Material not found"}],
          "durationMs": 80,
          "errorType": "SAP_BUSINESS_ERROR"
        }
      },
      "expected": {
        "status": "failure",
        "errorType": "SAP_BUSINESS_ERROR",
        "validateCalls": 1,
        "executeCalls": 1
      }
    }
  ]
}
```

- [x] **Step 2: 更新 verify-agent-callplan-evidence.sh**

在 `scripts/verify-agent-callplan-evidence.sh` 的 pytest 行后、openspec 行前增加:

```bash
"$PYTHON_BIN" -m sap_nexus_agent.eval evals/pr_create_cases.json
```

完整脚本:

```bash
#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"

"$PYTHON_BIN" -m pytest agent/tests
"$PYTHON_BIN" -m sap_nexus_agent.eval evals/inventory_availability_cases.yaml
"$PYTHON_BIN" -m sap_nexus_agent.eval evals/eval_harness_seed_cases.json
"$PYTHON_BIN" -m sap_nexus_agent.eval evals/pr_create_cases.json
openspec validate --all --strict
```

- [x] **Step 3: 运行 eval 回归确认通过**

Run: `.venv/bin/python -m sap_nexus_agent.eval evals/pr_create_cases.json`
Expected: PASS(输出 `Eval passed: 9/9`)

- [x] **Step 4: 运行 verify-agent-callplan-evidence.sh 确认全量通过**

Run: `bash scripts/verify-agent-callplan-evidence.sh`
Expected: PASS(pytest + 3 个 eval + openspec validate)

- [x] **Step 5: Commit**

```bash
git add evals/pr_create_cases.json scripts/verify-agent-callplan-evidence.sh
git commit -m "test(eval): add 9 PR create write regression cases, wire into verify script"
```

---

## Task 16: 全量验证与文档归档准备

**Files:**
- Create: `docs/runbooks/11-sandbox-write-vertical-slice.md`
- Modify: `docs/runbooks/README.md`(索引追加)
- Modify: `docs/wiki/sap-nexus-agent-implementation-roadmap.md`(§17.3 进度)

**Interfaces:**
- Produces: runbook 11 session closeout 文档
- Produces: README 索引更新
- Produces: roadmap §17.3 / row 10 进度标记

- [x] **Step 1: 运行全量验证命令**

```bash
git status --short
openspec list --json
openspec validate --all --strict
scripts/validate-registry-contract.py registry/capabilities.yaml
cd services/gateway && ./gradlew test
.venv/bin/python -m pytest agent/tests/
bash scripts/verify-agent-callplan-evidence.sh
```

Expected: 全部 PASS,无未跟踪文件遗漏

- [x] **Step 2: 写 runbook 11**

Create `docs/runbooks/11-sandbox-write-vertical-slice.md`:

```markdown
# Runbook 11: Sandbox Write Vertical Slice

- Change: `sap-nexus-sandbox-write-vertical-slice`
- 日期: 2026-07-16
- 状态: 已完成
- 关联: `docs/superpowers/specs/2026-07-16-sap-nexus-sandbox-write-vertical-slice-design.md`

## 目标

打通 SAP Nexus Agent 首个 WRITE/Approval 闭环——以 `BAPI_PR_CREATE` 为首个 Action capability。

## 交付物

- `MM.PR.CreateDraft` capability 注册(kind=Action, sideEffect=sap_write, requiresApproval=true)
- `ApprovalGuard` 守卫(4 种拒绝场景 fail-closed)
- `PrCreateDraftExecutor`(BAPI_PR_CREATE + commit/rollback 守卫)
- Agent approval 状态机 + Action CallPlan + ActionResult 解析
- 9 个 eval 回归 case
- READ/WRITE 路径隔离回归测试

## 关键决策

- commit/rollback 在 Gateway 内部强制(JcoCapabilityExecutor write 分支)
- approval 守卫在 execute 入口、SAP 调用前 fail-closed
- ApprovalRecord 存储:进程内 InMemoryApprovalStore(MVP)
- approval TTL 默认 600s
- 间采薄纵切先只支持 acct_assgn_cat="K"

## 验证命令

```bash
openspec validate --all --strict
scripts/validate-registry-contract.py registry/capabilities.yaml
cd services/gateway && ./gradlew test
.venv/bin/python -m pytest agent/tests/
bash scripts/verify-agent-callplan-evidence.sh
```

## Live Smoke(本地 .env SAP)

```bash
# 直采
.venv/bin/python -m sap_nexus_agent.cli "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01"
# 间采
.venv/bin/python -m sap_nexus_agent.cli "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01 间采 K 成本中心 1000"
```

## 后续

- 生产 client 写入(留后续)
- release/post 重量级 action(留后续)
- RecommendationPlan 推理引擎(row 11)
```

- [x] **Step 3: 更新 docs/runbooks/README.md 索引**

在 `docs/runbooks/README.md` 的 runbook 列表末尾追加:

```markdown
- [11-sandbox-write-vertical-slice.md](11-sandbox-write-vertical-slice.md) - 首个 SAP WRITE/Approval 闭环(MM.PR.CreateDraft)
```

- [x] **Step 4: 更新 roadmap §17.3 / row 10 进度**

在 `docs/wiki/sap-nexus-agent-implementation-roadmap.md` 的 §17.3 或 row 10 标记进度为已完成,附 runbook 11 链接。

- [x] **Step 5: 最终 openspec validate**

Run: `openspec validate --all --strict`
Expected: PASS

- [x] **Step 6: Commit**

```bash
git add docs/runbooks/11-sandbox-write-vertical-slice.md docs/runbooks/README.md docs/wiki/sap-nexus-agent-implementation-roadmap.md
git commit -m "docs: add runbook 11 for sandbox write vertical slice, update roadmap progress"
```

---

## Task 18: Approval 注册通道(Agent↔Gateway 断层修复)

> **背景**:Task 17 live smoke 暴露跨 Task 8/14 集成断层:Agent 侧 approval 状态机(pending->approved->executed)与 Gateway 侧 ApprovalGuard(fail-closed)各自正确,但二者之间缺注册通道--Agent 生成的 ApprovalRecord 未传到 Gateway ApprovalStore,导致 `approvalStore.find(approvalId)` 恒返回 null -> APPROVAL_REQUIRED,Action capability 无法 live execute。修复方案 A:Gateway 加 approve endpoint + Agent 注册调用。

- [x] **Step 1: 写失败测试--Gateway approve endpoint**

新增 `CapabilityApprovalApiTest`:对 `POST /capabilities/{capabilityId}/approve` 提交 ApprovalRecord(approvalId/capabilityId/parameterSnapshotHash/parameters/approver/expiresAt/status=approved),Gateway 调 `approvalStore.save()` 存储,返回 200 + approvalId。RED:endpoint 不存在,404。

- [x] **Step 2: 运行测试确认失败**

```bash
cd services/gateway && gradle :app:test --tests "com.sapnexus.gateway.api.CapabilityApprovalApiTest"
```

- [x] **Step 3: 实现 Gateway approve endpoint**

在 `CapabilityController` 新增 `approve` 方法:`POST /capabilities/{capabilityId}/approve`,接收 ApprovalRecord 请求体,调 `approvalStore.save(record)`,返回 approvalId。仅允许 Action capability(可选校验)。不触发 SAP。

- [x] **Step 4: 写失败测试--Agent 注册 approval 到 Gateway**

扩展 `test_orchestrator_write.py`:orchestrator 在用户批准后调 `gateway_client.approve(capability_id, approval_record)`,再 execute。RED:`gateway_client.approve` 不存在。

- [x] **Step 5: 运行测试确认失败**

```bash
.venv/bin/python -m pytest agent/tests/test_orchestrator_write.py -v
```

- [x] **Step 6: 实现 Agent gateway_client.approve + orchestrator 调用**

- `gateway_client.py` 新增 `approve(capability_id, approval_record)`:POST `/capabilities/{id}/approve`,把 ApprovalRecord 发给 Gateway 注册,返回 approvalId。
- `orchestrator.py` write 路径:用户批准后(approval 状态 pending->approved)调 `gateway_client.approve(...)` 注册到 Gateway,再 execute(带 approvalId)。

- [x] **Step 7: 运行测试确认通过**

```bash
cd services/gateway && gradle :app:test --tests "com.sapnexus.gateway.api.CapabilityApprovalApiTest"
.venv/bin/python -m pytest agent/tests/test_orchestrator_write.py -v
```

- [x] **Step 8: 运行全量回归确认无破坏**

```bash
cd services/gateway && gradle test
.venv/bin/python -m pytest agent/tests/ -v
scripts/verify-agent-callplan-evidence.sh
```

- [x] **Step 9: Commit**

```bash
git add -A
git commit -m "feat(approval): add Gateway approve endpoint and Agent registration for WRITE path"
```

> Task 18 完成后,重跑 Task 17 live smoke 验证真实 PR 创建。

## Task 19: 修复 BAPI_PR_CREATE technical envelope

> **背景**:Task 17 首次真实直采调用通过 validation 与 approval guard，但 SAP 返回 `Please enter items first` / `Enter Document Type`。sandbox JCo repository metadata 已确认需要 `PRHEADER/PRHEADERX/PRITEM/PRITEMX`；当前 executor 错把 `isInitialized` 当作 table existence，并把 `PRITEM.MATERIAL` 当作真实列名。

**Files:**
- Modify: `services/gateway/jco/src/main/java/com/sapnexus/gateway/jco/PrCreateDraftExecutor.java`
- Test: `services/gateway/jco/src/test/java/com/sapnexus/gateway/jco/PrCreateDraftExecutorTest.java`

**Interfaces:**
- Consumes: `CapabilityDefinition.executor().inputMapping()`，值为 `PRITEM.<FIELD>`；已审批参数 material/plant/quantity/unit/delivery_date
- Produces: `BAPI_PR_CREATE` 标准直采 envelope（`PR_TYPE=NB`、item `00010`、对应 X indicators），保持现有 commit/rollback 与 `ExecutionResult` 接口不变

- [x] **Step 1: 写失败测试——真实 header/item/X 结构必须被填充**

扩展 `successCommitsAndExtractsPrNumber()`：mock `PRHEADER`、`PRHEADERX`、`PRITEM`、`PRITEMX` 及各自 metadata；`JCoParameterList.getMetaData().indexOf(...)` 对四个结构返回非负值；item metadata 对 `PREQ_ITEM/MATERIAL/PLANT/QUANTITY/UNIT/DELIV_DATE` 返回 true。执行参数固定为：

```java
Map.of(
        "material", "DEMOA1",
        "plant", "1000",
        "quantity", "10",
        "unit", "EA",
        "delivery_date", "2026-08-15"
)
```

新增精确断言：

```java
verify(prHeader).setValue("PR_TYPE", "NB");
verify(prHeaderX).setValue("PR_TYPE", "X");
verify(prItem).appendRow();
verify(prItem).setValue("PREQ_ITEM", "00010");
verify(prItem).setValue("MATERIAL", "DEMOA1");
verify(prItem).setValue("PLANT", "1000");
verify(prItem).setValue("QUANTITY", "10");
verify(prItem).setValue("UNIT", "EA");
verify(prItem).setValue(eq("DELIV_DATE"), isA(java.sql.Date.class));
verify(prItemX).appendRow();
verify(prItemX).setValue("PREQ_ITEM", "00010");
verify(prItemX).setValue("PREQ_ITEMX", "X");
verify(prItemX).setValue("MATERIAL", "X");
verify(prItemX).setValue("PLANT", "X");
verify(prItemX).setValue("QUANTITY", "X");
verify(prItemX).setValue("UNIT", "X");
verify(prItemX).setValue("DELIV_DATE", "X");
```

- [x] **Step 2: 运行 focused test，确认 RED**

```bash
cd services/gateway
/tmp/gradle-8.8/bin/gradle --no-daemon :jco:test --tests "com.sapnexus.gateway.jco.PrCreateDraftExecutorTest.successCommitsAndExtractsPrNumber"
```

Expected: FAIL，至少缺少 `PRHEADER.PR_TYPE` 或 `PRITEM`/`PRITEMX` 写入调用；不得因测试配置错误失败。

- [x] **Step 3: 实现最小 BAPI technical envelope**

在 `PrCreateDraftExecutor` 中增加以下常量与私有方法，保持 public interface 不变：

```java
private static final String STANDARD_PR_TYPE = "NB";
private static final String FIRST_ITEM = "00010";

private void applyPrHeader(JCoParameterList imports) {
    JCoStructure header = imports.getStructure("PRHEADER");
    JCoStructure headerX = imports.getStructure("PRHEADERX");
    header.setValue("PR_TYPE", STANDARD_PR_TYPE);
    headerX.setValue("PR_TYPE", "X");
}
```

`applyPrItemTables(...)` 必须：

1. 用 parameter-list metadata 判断 `PRITEM`/`PRITEMX` 是否存在，不使用 `isInitialized`。
2. 两张表各 append 一行并写相同 `PREQ_ITEM="00010"`；`PRITEMX.PREQ_ITEMX="X"`。
3. 仅处理 target 前缀为 `PRITEM.` 的 mapping，以最后一个 `.` 后的 suffix 作为真实 field。
4. 对每个存在且有值的 field 写 `PRITEM`，并在 `PRITEMX` 写 `"X"`。
5. `delivery_date` 用 `java.sql.Date.valueOf(LocalDate.parse(value.toString()))` 转换；其他值保持现状。

- [x] **Step 4: 运行 focused test，确认 GREEN**

```bash
cd services/gateway
/tmp/gradle-8.8/bin/gradle --no-daemon :jco:test --tests "com.sapnexus.gateway.jco.PrCreateDraftExecutorTest"
```

Expected: PASS，成功、业务错误 rollback、commit 失败 rollback 全部通过。

- [x] **Step 5: 运行 Gateway 全量回归**

```bash
cd services/gateway
/tmp/gradle-8.8/bin/gradle --no-daemon test
```

Expected: `BUILD SUCCESSFUL`；READ 路径隔离测试仍通过。

- [x] **Step 6: Commit envelope 修复**

```bash
git add services/gateway/jco/src/main/java/com/sapnexus/gateway/jco/PrCreateDraftExecutor.java services/gateway/jco/src/test/java/com/sapnexus/gateway/jco/PrCreateDraftExecutorTest.java
git commit -m "fix(write): build required BAPI_PR_CREATE payload envelope"
```

## Task 17: Live smoke 验证（Task 19 后恢复）

**Files:**
- Modify: `docs/runbooks/11-sandbox-write-vertical-slice.md`

**Interfaces:**
- Consumes: 本地 `.env` sandbox/dev SAP、Gateway 18080、Task 19 修复后的 `PrCreateDraftExecutor`
- Produces: 1 个且仅 1 个 committed 直采 PR 证据；间采保持 mock-only

- [x] **Step 1: 确认本地环境与候选数据**

已验证：Gateway `health=UP`、`jcoConfigured=true`；真实 READ 确认 material `DEMOA1` / plant `1000` 可用于 sandbox 调用。

- [x] **Step 2: 记录首次 live 失败为 RED 证据**

首次唯一 execute 返回 `SAP_BUSINESS_ERROR`：`Please enter items first` / `Enter Document Type` / `No instance ... created`；没有 PR，失败路径调用 rollback，不允许原样重试。

- [x] **Step 3: 确认间采不进入 live 范围**

用户确认只做直采最小验证。sandbox metadata 证明 `COSTCENTER` 不在 `PRITEM`；间采保留 mock 覆盖，不调用真实 SAP。

- [x] **Step 4: Task 19 全量测试通过后，执行最后一次直采 live smoke**

```bash
cd agent
../.venv/bin/python -m sap_nexus_agent.cli \
  --gateway-url http://127.0.0.1:18080 \
  --intent-mode rule \
  --json \
  "给物料 DEMOA1 工厂 1000 建 10 EA 采购申请 交货 2026-08-15"
```

Expected: `status=success`、返回真实 PR 号、Gateway `errorType=NONE`。该命令最多执行一次；成功或失败均停止，不做第三次尝试。

- [x] **Step 5: 确认失败 rollback 与 trace 脱敏**

检查本次 Gateway/Agent trace；成功时验证 commit，失败时验证明确业务错误、无 PR、进入 rollback 分支：

- capabilityId=`MM.PR.CreateDraft`
- approval pending -> approved；失败时不伪造 executed
- 成功时 `prNumber` 非空且 commit status 为 committed；失败时 `prNumber` 为空且无 commit
- 不含 SAP password、destination、token 或 `.env` 值
- runtime trace 不加入 git

- [x] **Step 6: 更新 runbook 11 的 Live Smoke 事实**

记录首次失败根因、Task 19 修复、最后一次 execute 的真实 PR 号/commit/trace 结果；不得记录凭据或原始 runtime trace。

- [x] **Step 7: 运行 change 全量验证**

```bash
scripts/verify-agent-callplan-evidence.sh
openspec validate --all --strict
git diff --check
```

Expected: evidence/eval/OpenSpec 全部通过；PostHog telemetry 网络告警不改变命令退出码判断。

- [x] **Step 8: Commit live smoke 结果**

```bash
git add docs/runbooks/11-sandbox-write-vertical-slice.md docs/superpowers/plans/2026-07-16-sap-nexus-sandbox-write-vertical-slice.md openspec/changes/sap-nexus-sandbox-write-vertical-slice/tasks.md
git commit -m "docs(write): record sandbox PR live smoke result"
```

## Task 20: 治理 Purchasing Group 并恢复一次 live smoke

> **背景**:Task 19 后的 live smoke 已被 SAP 接受 header/item/X envelope，但返回 `Enter Purch. Group`。用户确认 sandbox 采购组为 `601`，并授权一次新的受控尝试。`601` 是本次请求数据，不得硬编码到 executor。

**Files:**
- Modify: `registry/capabilities.yaml`
- Modify: `agent/sap_nexus_agent/pr_intent.py`
- Test: `agent/tests/test_pr_intent.py`
- Modify: `evals/pr_create_cases.json`
- Test: `services/gateway/jco/src/test/java/com/sapnexus/gateway/jco/PrCreateDraftExecutorTest.java`
- Modify: `ontology/mm-purchaserequisition.owl`
- Modify: OpenSpec/design/runbook coordination artifacts

**Interfaces:**
- Consumes: `purchasing_group` as a required, approved PR business parameter
- Produces: `PRITEM.PUR_GROUP` plus `PRITEMX.PUR_GROUP="X"`
- Safety: validation failure stops before approval/SAP; one authorized sandbox/dev direct-purchase WRITE only

- [x] **Step 1: RED - Agent 缺参和解析测试**

Add tests proving a complete PR request without `采购组` clarifies `purchasing_group`, while `采购组 601` is parsed into the approved parameter map. Run focused pytest and confirm the new tests fail for the missing behavior.

- [x] **Step 2: RED - Registry PUR_GROUP contract test**

Add a real-registry descriptor assertion proving `purchasing_group` is required and confirm it fails before the YAML contract changes. The production executor already generically handles governed `PRITEM.*` mappings, so do not add a field-specific Java branch.

- [x] **Step 3: GREEN - Minimal end-to-end parameter mapping**

Add the required capability input and mapping, parse `采购组`, include it in required-field clarification/eval cases, and extend the generic executor regression with `PRITEM.PUR_GROUP` / X-marker assertions. Do not hardcode `601` in production code.

- [x] **Step 4: Verify focused and full regression**

Run focused Agent/Gateway tests, Gateway full tests, `scripts/verify-agent-callplan-evidence.sh`, `openspec validate --all --strict`, and `git diff --check`.

Review: main-session thorough review completed because session policy did not authorize subagent dispatch. It found and fixed the missing `sapnexus:PurchasingGroup` ontology declaration and a plan-only historical file-list regression; no unresolved CRITICAL or IMPORTANT findings remain.

- [x] **Step 5: Execute one authorized sandbox live smoke**

Start the Gateway with local `.env`, confirm health and READ connectivity, then run exactly one direct PR query with material `DEMOA1`, plant `1000`, quantity `10 EA`, delivery date `2026-08-15`, purchasing group `601`. Stop after success or explicit rollback failure.

- [x] **Step 6: Record evidence and close Task 7.4/8.1/8.2 only if proven**

Update runbook 11 with trace ID, PR number/commit or rollback error, and credential-scan result. Runtime traces remain uncommitted.

## Task 21: 关闭成功返回与 approval trace 契约

> **背景**:唯一一次授权 WRITE 已成功创建 PR `10137471`，SAP RETURN 与 Gateway trace 均为 success，但 `data.prNumber` 为空，Agent approval trace 只到 `approved`。metadata-only JCo 探针确认正式导出参数为 `NUMBER`。不得再次执行 WRITE。

**Files:**
- Modify: `services/gateway/jco/src/main/java/com/sapnexus/gateway/jco/PrCreateDraftExecutor.java`
- Test: `services/gateway/jco/src/test/java/com/sapnexus/gateway/jco/PrCreateDraftExecutorTest.java`
- Modify: `agent/sap_nexus_agent/orchestrator.py`
- Test: `agent/tests/test_orchestrator_write.py`

- [x] **Step 1: RED - export NUMBER 与 executed trace**

Make the success executor test expose `NUMBER=10137471` while `PRITEMEXP.PREQ_NO` is empty, and assert the structured PR number. Make the successful orchestrator test assert `pending -> approved -> executed` in an isolated trace directory. Confirm both fail for the observed reasons.

- [x] **Step 2: GREEN - minimal contract fixes**

Read `EXPORTS.NUMBER` before the existing table fallback. Call `mark_executed` only after a successful Action execute. Do not parse human-readable SAP messages and do not change the failure path.

- [x] **Step 3: Full regression and evidence closeout**

Run Agent/Gateway focused and full tests, deterministic evidence verification, OpenSpec strict validation, credential scan, and `git diff --check`. Update runbook/tasks with the already-created PR evidence; do not invoke SAP WRITE again.

## Task 22: 恢复 Gateway ActionResult HTTP 契约

> **背景**:live 响应显示 Controller 仍直接返回通用 `ExecutionResult`，虽然 Java/Python 两侧都已定义并期待顶层 `ActionResult`。该偏差导致 `commitStatus` 缺失，并让 `prNumber` 留在内部 data。

- [x] **Step 1: RED - approved Action response shape**

Add a Controller API test with an approved Action execution and assert the response body is `ActionResult` with `prNumber=10137471` and `commitStatus=committed`. Confirm the current `ExecutionResult` response fails the test.

- [x] **Step 2: GREEN - map Action ExecutionResult**

After dispatch and approval-store update, map Action success/failure to `ActionResult` while preserving trace ID, SAP RETURN, duration and error type. Keep Function responses unchanged.

- [x] **Step 3: Regression and review**

Run API focused tests, full Gateway/Agent suites and deterministic evidence verification. No SAP call is permitted.
