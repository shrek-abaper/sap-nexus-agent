---
comet_change: flexible-intent-recognition
role: technical-design
canonical_spec: openspec
archived-with: 2026-07-09-flexible-intent-recognition
status: final
---

# Flexible Intent Recognition - Technical Design

## 1. 背景与目标

### 1.1 问题

Agent 意图识别入口层（`llm_intent.py` / `cli.py`）为库存-only 时代编写，OData 采购订单能力（`MM.PurchaseOrder.GetList`）已注册并经 `run_query` + PO fact/narrator 端到端验证（`test_run_query_po_list_success`），但意图识别入口层未同步，导致「查询采购订单DEMOPO1」返回 `当前仅支持已注册的只读能力...`。

三处根因：
1. `llm_intent.py` hybrid fallback 调 `parse_inventory_intent`（库存-only），非 `parse_intent`（已支持 PO）。
2. `llm_intent.py` LLM prompt 写死 `CAPABILITY_ID=MM.Inventory.GetAvailability`，allowed intents 仅 `inventory_availability/unsupported`；`_payload_to_parse_result` 只认库存意图。
3. `cli.py` 入口 `run_inventory_query`。

### 1.2 目标

柔性意图识别：意图闭集从 `registry/capabilities.yaml` active capability 动态派生，LLM prompt 动态注入能力元数据，新增能力只需注册即自动支持（LLM 可用时零代码）；修复规则 fallback 使已注册显式意图在 LLM 不可用时也可查。

### 1.3 非目标

- 不改 `registry/capabilities.yaml` schema（不加 intent/keywords 字段，`aliases` 留未来扩展）。
- 不实现规则路径完全柔性（规则路径仍需 `intent.py` 显式映射；LLM 不可用时仅覆盖显式意图）。
- 不改前端（intentMode 默认 hybrid 保留，事件流不变）、不改 LLM client、不改下游 fact/narrator/gateway。
- 不做多轮上下文、不做 capability 之外的意图。

## 2. 架构与数据流

```
用户查询
  │
  ├─ hybrid/llm ─> parse_with_llm(text, client, catalog)
  │     ├─ _messages: 动态注入 active capability 的 capabilityId+description+inputs
  │     ├─ LLM 返回 capabilityId + 参数
  │     ├─ _payload_to_parse_result: 闭集校验 + required 参数校验 + OData/RFC 检测
  │     └─ 填 IntentParseResult.capability_id（不填 intent）
  │     └─ LLM 不可用 -> fallback parse_intent
  │
  └─ rule ─> parse_intent（统一规则，支持 inventory + PO）
        └─ 填 IntentParseResult.intent（不填 capability_id）
  │
  ▼
select_capability: 优先 capability_id，回退 INTENT_TO_CAPABILITY[intent]
  │
  ▼
run_query -> CallPlan -> Gateway validate/execute -> fact/narrator
```

两条意图路径在 `select_capability` 汇合，下游（run_query 及之后）无感。

## 3. 组件设计

### 3.1 `registry_loader.py`（新增）

```python
@dataclass(frozen=True)
class InputDescriptor:
    name: str            # poNumber
    semantic_name: str   # purchaseOrderNumber
    required: bool
    type: str

@dataclass(frozen=True)
class CapabilityDescriptor:
    capability_id: str          # MM.PurchaseOrder.GetList
    name: str                   # Purchase Order List
    description: str
    domain: str                 # MM
    business_object: str        # PurchaseOrder
    inputs: tuple[InputDescriptor, ...]

@dataclass(frozen=True)
class IntentCatalog:
    capabilities: tuple[CapabilityDescriptor, ...]
    capability_ids: frozenset[str]

    def find(self, capability_id: str) -> CapabilityDescriptor | None: ...

def load_intent_catalog(repo_root: str | None = None) -> IntentCatalog:
    # 读 registry/capabilities.yaml，过滤 status==active
    # repo_root 解析：SAP_NEXUS_AGENT_ROOT env > 向上找 registry/ > cwd
    # 找不到 registry 返回空 IntentCatalog（不抛异常，LLM 路径降级 unsupported）
```

**设计要点**：
- dataclass frozen，不可变，安全共享。
- `capability_ids` frozenset 供闭集校验 O(1) 查找。
- `find()` 按 capabilityId 取描述符，供 required 参数校验。
- 路径解析失败返回空 catalog 而非抛异常--避免 agent 进程在非标准 cwd 启动时崩溃；空 catalog 使所有 LLM 选择都通不过闭集校验，自然降级为 unsupported（安全失败）。
- 依赖 PyYAML（已是项目依赖）。

### 3.2 `intent.py`（小改）

`IntentParseResult` 增加 `capability_id: str | None = None` 字段。规则解析器（`parse_intent`/`parse_inventory_intent`）行为不变，不填 capability_id（保持 None）。LLM 路径填 capability_id，不填 intent。

frozen dataclass 加带默认值字段，既有构造调用（不传 capability_id）仍合法，向后兼容。

### 3.3 `capability_selector.py`（小改）

```python
def select_capability(parse_result: IntentParseResult) -> SelectionResult:
    if parse_result.contains_rfc_name or parse_result.contains_odata_override:
        return SelectionResult(... UNSUPPORTED_RFC_NAME ...)
    capability_id = parse_result.capability_id or INTENT_TO_CAPABILITY.get(parse_result.intent)
    if capability_id is None:
        return SelectionResult(... UNSUPPORTED_INTENT ...)
    if parse_result.missing_parameters:
        return SelectionResult(... MISSING_PARAMETER ...)
    return SelectionResult(capability_id=capability_id)
```

RFC/OData 拦截优先级不变；missing_parameters 逻辑不变。`INTENT_TO_CAPABILITY` 保留（规则路径用）。

### 3.4 `llm_intent.py`（核心重构）

#### Prompt 构造 `_messages(text, catalog)`

```python
def _messages(text, catalog):
    capabilities_desc = "\n".join(
        f"- capabilityId: {c.capability_id}\n"
        f"  description: {c.description}\n"
        f"  inputs: {_format_inputs(c.inputs)}"
        for c in catalog.capabilities
    )
    return [
        {"role": "system", "content": (
            "You extract SAP Nexus read-only query intent as strict JSON. "
            "Select exactly one capabilityId from the registered closed set below, "
            "and extract parameters from the user query. "
            "If none matches, set capabilityId=null. "
            "Never output rfcName or raw SAP BAPI/RFC names. "
            "Return keys: capabilityId, parameters, missingParameters, clarification.\n\n"
            f"Registered capabilities:\n{capabilities_desc}"
        )},
        {"role": "user", "content": text},
    ]
```

动态注入，不再写死库存。新增 active capability 自动进入 prompt。

#### 闭集校验与参数校验 `_payload_to_parse_result(payload, catalog)`

```python
def _payload_to_parse_result(payload, catalog):
    # OData/RFC 注入检测（保留双层防御）
    contains_rfc_name = ...
    contains_odata_override = ...
    if contains_rfc_name or contains_odata_override:
        return IntentParseResult(intent=None, parameters={}, missing_parameters=[],
                                 contains_rfc_name=..., contains_odata_override=...)

    capability_id = payload.get("capabilityId")
    if not capability_id or capability_id not in catalog.capability_ids:
        return IntentParseResult(intent=None, parameters={}, missing_parameters=[])  # unsupported

    descriptor = catalog.find(capability_id)
    # 参数提取 + 别名归一
    parameters = _extract_parameters(payload.get("parameters"), descriptor)
    # required 参数校验
    missing = [inp.name for inp in descriptor.inputs if inp.required and inp.name not in parameters]
    clarification = _clarification_for(capability_id, missing)

    return IntentParseResult(
        intent=None,           # LLM 路径不填 intent
        capability_id=capability_id,
        parameters=parameters,
        missing_parameters=missing,
        clarification=clarification,
    )
```

#### 参数别名归一 `_extract_parameters`

保留 `_parameter_key` 别名映射，**扩展含 PO**：

```python
_ALIASES = {
    # inventory
    "material": "material", "materialNumber": "material", "materialCode": "material", "matnr": "material",
    "plant": "plant", "plantCode": "plant", "werks": "plant",
    "unit": "unit", "uom": "unit", "unitOfMeasure": "unit",
    # purchase order
    "poNumber": "poNumber", "purchaseOrderNumber": "poNumber", "ebeln": "poNumber",
    "vendor": "vendor", "supplier": "vendor", "lifnr": "vendor",
}
```

别名表**全局共享**（plant/material 跨 inventory 和 PO 共用），PO 专属别名（poNumber/vendor）扩展加入。LLM 输出 name 或 semanticName 都能归一到 registry inputs.name。

校验：归一后的 key 必须在选中 capability 的 inputs.name 集合内，否则丢弃（防止 LLM 注入未注册参数）。

#### Fallback 修复

```python
def parse_with_hybrid(text, client=None, catalog=None):
    try:
        llm_client = client or OpenAiCompatibleLlmClient()
        result = parse_with_llm(text, llm_client, catalog)
        if _requires_safe_fallback(result):
            return parse_intent(text)          # 非 parse_inventory_intent
        return result
    except LlmUnavailable:
        return parse_intent(text)              # 非 parse_inventory_intent

def build_intent_adapter(mode, catalog):
    if mode == "rule":
        return parse_intent                    # 三路径一致
    if mode == "llm":
        return lambda text: _parse_llm_only(text, catalog)
    if mode == "hybrid":
        return lambda text: parse_with_hybrid(text, catalog=catalog)
```

`parse_inventory_intent` 保留，仅 `run_inventory_query` 向后兼容用。

### 3.5 `cli.py`（小改）

```python
from sap_nexus_agent.orchestrator import run_query
from sap_nexus_agent.registry_loader import load_intent_catalog

def main(argv=None):
    ...
    catalog = load_intent_catalog()
    intent_adapter = build_intent_adapter(args.intent_mode, catalog)
    outcome = run_query(args.query, GatewayClient(args.gateway_url), intent_adapter=intent_adapter)
    ...
```

help 文案去掉「inventory-only」措辞，改为「read-only SAP query」。

## 4. 错误处理与边界条件

| 场景 | 行为 |
|---|---|
| LLM 不可用（缺配置/连接失败） | hybrid/llm fallback `parse_intent`；llm 模式 fallback 返回 unsupported |
| LLM 返回非法 capabilityId | 闭集校验失败 -> unsupported |
| LLM 返回 rfcName/OData 注入 | 检测到 -> UNSUPPORTED_RFC_NAME（双层防御） |
| LLM 缺 required 参数 | missing_parameters + clarification |
| registry 文件缺失 | 空 catalog -> LLM 路径全部 unsupported；rule 路径不受影响（`parse_intent` 不依赖 catalog） |
| LLM 返回未注册参数 | 别名归一后不在 inputs.name 集合 -> 丢弃 |
| 空 query | `parse_intent` 返回 intent=None -> unsupported（现有行为） |

**安全失败原则**：任何 LLM/registry 异常都不让 agent 崩溃，降级为 unsupported 或 rule fallback。

## 5. 测试策略

| 文件 | 类型 | 覆盖 |
|---|---|---|
| `test_registry_loader.py`（新） | 单元 | 读真实 capabilities.yaml、active 过滤、闭集含 inventory+PO、inputs 解析、路径回退、空 catalog |
| `test_llm_intent.py`（更新） | 单元 | PO LLM 用例（fake client 返回 PO capabilityId+poNumber -> 正确解析）、闭集校验（非法 -> unsupported）、fallback 改 parse_intent、PO 别名归一、移除「prompt 写死库存」断言 |
| `test_orchestrator.py`（更新） | 集成 | run_query 经 LLM adapter（catalog+fake client）选 PO 全链路、现有 inventory 用例不破坏 |
| `test_intent.py` | 回归 | 不改，确认加字段后不破坏 |
| `evals/purchase_order_cases.json` | eval | po-by-number 覆盖 DEMOPO1 风格 |
| 端到端 | 手动 | CLI 直测「查询采购订单DEMOPO1」返回 PO 列表 |

fake LLM client 复用现有 `test_llm_intent.py` 的 mock 模式（`chat_json` 返回固定 payload）。

## 6. 风险与取舍

- **LLM 选错 capabilityId** -> 闭集校验 + required 参数校验兜底；错则 unsupported，不执行。
- **LLM 不可用时规则 fallback 仅覆盖显式意图** -> 已修复为 `parse_intent`（PO 可查）；口语变体需 LLM（Non-Goal）。
- **IntentParseResult 加字段影响既有测试** -> 字段默认 None，既有断言不破坏；测试同步更新。
- **registry 路径解析（agent cwd 不定）** -> 多级回退 env > 向上找 registry/ > cwd；测试注入固定路径。
- **LLM prompt 随能力增长变长** -> 当前仅 2 能力，可控；后续可按 domain 分组或摘要。
- **规则路径仍需手动加映射** -> 规则路径固有局限；LLM 可用时完全柔性。`aliases` 字段留未来扩展口。
- **别名表全局共享** -> 参数语义跨能力共享（plant/material），比每 capability 独立别名表简单；PO 专属别名扩展加入。

## 7. 迁移与回滚

纯 agent 侧重构，无数据迁移、无后端部署：

1. 实现 registry_loader + llm_intent 重构 + intent/capability_selector/cli 小改。
2. 更新/新增测试。
3. 验证：pytest + PO eval + validate_registry_contract + openspec validate + verify 脚本通过。
4. 端到端：CLI 直测「查询采购订单DEMOPO1」返回 PO 列表。
5. 归档 change。

**回滚**：`git revert` agent 改动即可，无副作用。

## 8. 改动文件清单

| 文件 | 改动 |
|---|---|
| `agent/sap_nexus_agent/registry_loader.py` | 新增 |
| `agent/sap_nexus_agent/llm_intent.py` | 重构（动态 prompt + 闭集校验 + fallback + 别名扩展 + unhashable capabilityId safe-fail 守卫） |
| `agent/sap_nexus_agent/intent.py` | 加 `capability_id` 字段 |
| `agent/sap_nexus_agent/capability_selector.py` | 优先 capability_id |
| `agent/sap_nexus_agent/cli.py` | run_query + catalog 注入 |
| `agent/pyproject.toml` | 加 pyyaml 依赖 |
| `agent/tests/test_registry_loader.py` | 新增 |
| `agent/tests/test_llm_intent.py` | 更新 |
| `agent/tests/test_orchestrator.py` | 更新 |

## 9. Review 发现与跟进项

### 已修复（本 PR 内）
- **unhashable capabilityId safe-fail 回归**（review Important #1）：`_payload_to_parse_result` 用 `frozenset` 成员检查，LLM 返回 list-valued capabilityId 会抛 `TypeError` 不被 `except LlmUnavailable` 捕获。已加 `isinstance(capability_id, str)` 守卫 + 测试 `test_parse_with_llm_handles_unhashable_capability_id_without_crash`。

### 跟进项（本 PR 暴露的既有 bug，超出本 change 范围）
- **PO fact builder 不处理真实 OData 嵌套 items 结构**（review Important #2）：`build_purchase_order_facts`（`reasoning_fact.py`，本 PR 未改）从 PO header 读 plant/material/orderQuantity/purchaseOrderUnit，但真实 OData 嵌套在 `items[]` 子数组。此前 CLI 到不了 PO 故未暴露；本 PR 让 PO 可达后暴露，端到端 CLI 返回 `NARRATIVE_GUARD_ERROR`。意图识别层正确，此为下游 fact builder 的独立 bug。跟进：`build_purchase_order_facts` 应展开 `items[]` 逐行建 fact + `FakePoGatewayClient` 测试数据改为真实嵌套结构。不阻塞本 change 归档。

### 设计文档勘误
- 设计文档原称 `workbench_output.py`「不受影响」：文件未改，但其 rule 模式行为变化（`parse_inventory_intent` -> `parse_intent`，现可路由 PO），属正向改进，与重构目标一致。

