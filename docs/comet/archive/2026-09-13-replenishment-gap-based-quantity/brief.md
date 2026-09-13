# Outcome

用户通过 DSH 工作台发起补货建议时，生成的采购申请（PR）草稿数量等于**确定性计算的供应缺口**，而不是用户给出的目标需求总量。系统先读取同一物料/工厂的库存与在途供应事实，按业务口径计算缺口，再以缺口数量进入既有的人工审批与 SAP 写入流程；缺口为零时不生成提案。整个计算在服务端基于事实完成，大模型只负责转述与解释，不参与算术。

# Scope

- DSH 语义工具 `propose_replenishment` 触发的受治理链路（TS `executeSemanticTool` → Python agent → Gateway）。
- 提案构建前由服务端执行一次 `MM.Inventory.GetAvailability`（BAPI_MATERIAL_STOCK_REQ_LIST）读取事实，禁止依赖会话中上一轮诊断结果。
- 缺口口径（已与用户确认）：
  - 缺口 = 目标需求量（requiredQuantity，语义=目标需求总量）− 当期可用供应
  - 当期可用供应 = 当前可用库存（MRP 元素 WB，availQty1，恒计入）+ 目标交货日期前可到货的在途供应之和
  - 在途供应仅计入采购申请（MRP 元素指示符 BA / PurRqs）与采购订单行项目（BE / POitem），元素可用日期 `date <= targetDate` 才计入；其他 MRP 元素（计划订单、计划独立需求、销售订单、预留等）一律不计入供应
  - 日期比较按元素的 available/date 字段（YYYY-MM-DD）与 targetDate 做日历日比较
- 计算结果（含每项供应明细：类型/数量/日期/是否计入）成为 PR 数量的事实证据血缘，进入 run 事件、approval handle 与工具返回。
- DSH 审批卡片与模型可见结果中展示计算依据：目标需求量、当前库存、计入的在途 PR/PO（分行）、不计入项（如超期在途）、缺口数量。
- 缺口 <= 0：不调用 WRITE 能力、不产生审批提案，工具返回 `complete` 且 narrative 明确说明“目标日期前供应充足，无需补货”，并给出供应合计与需求对比。
- 库存读取失败（SAP 错误/无该物料）：fail-closed，不生成提案，返回 failed/clarification 错误，禁止在无供应事实时把 requiredQuantity 直接当缺口。

# Non-goals

- 不改变 SAP 侧 BAPI（BAPI_MATERIAL_STOCK_REQ_LIST / PR 创建函数）与 executor binding。
- 不做批量物料补货、批量组合确认（一次提案仍对应一个物料+工厂）。
- 不引入批量倍量/舍入/最小包装量（lot size rounding）、安全库存策略；缺口直接作为 PR 数量。
- 不把计划订单（FE/PA）、计划协议交货计划行等其他供应元素纳入本次计算（后续可扩展）。
- 不改造旧版 Workbench（/workbench）中已有的 TS recommendation decision-engine；其缺口公式（仅减当前库存）维持现状，除非复用其代码到新链路。
- 不改 WRITE 的审批治理：缺口提案与现状一样必须人工批准后才执行 SAP 写入。

# Acceptance examples

- 物料 P0254684AF / 工厂 5260，目标需求 10 EA，目标日期 2026-09-30：库存 WB=1（2026-09-13），在途 BA=3（2026-09-30）、BA=13（2026-09-30）均按期 → 当期供应=1+3+13=17 → 缺口=0 → 不生成提案，回复供应充足。
- 物料 P0227978AG / 工厂 5260，目标需求 10 EA，目标日期 2026-09-30：库存 WB=2，在途 BE=3（2026-08-12）→ 当期供应=5 → 提案 PR 数量=5 EA；审批卡片展示“需求10 − 库存2 − 在途PO 3 = 缺口5”。
- 同一物料在途 BE=3 的日期为 2026-10-15（晚于目标日期 2026-09-30）→ 该 3 EA 不计入 → 供应=2 → 缺口=8，卡片将该行列为“未计入（晚于目标日期）”。
- 用户只说“按缺口补”而未提供目标需求总量 → 澄清追问目标需求量（requiredQuantity 仍为必填槽位）。
- 物料不存在：库存 READ 返回 SAP_BUSINESS_ERROR → 工具返回 failed，不出现审批卡片，错误信息可展示。

# Constraints and invariants

- 硬边界不变：LLM/harness 只能选语义工具与槽位，不能指定 capabilityId/RFC/binding；缺口计算为服务端确定性逻辑。
- WRITE 硬边界不变：缺口提案仍为 Action，必须存在已记录的人工批准（approvalId、参数快照哈希、TTL）后 Gateway 才执行；READ 缺口计算本身不产生写入。
- 数量血缘可审计：PR quantity 的 parameterSources 必须能追溯到 requiredQuantity 约束与库存事实（MRP 元素行），与旧 decision-engine 的血缘结构保持同等可追溯级别。
- 确定性：相同事实输入必须得到相同缺口；时区按服务器本地日期（与现有 KEYDATE 默认一致），MRP 日期均为无时区日历日直接比较。
- fail-closed：库存事实缺失、READ 失败、单位不一致时不得生成提案。
- 证据最小化：模型可见文本只包含业务字段，不泄露 RFC 名称、绑定、技术键（沿用现有 redaction）。

# Decisions

- D1（用户已确认，2026-09-13）：缺口 = 目标需求量 −（当前可用库存 + 目标交货日期前到货的在途 PR + 在途 PO）；PR/PO 是否计入以可用日期 ≤ targetDate 判定。
- D2（用户已确认，2026-09-13）：缺口 ≤ 0 时不生成提案，回复供应充足。
- D3：在途供应的事实来源复用 `MM.Inventory.GetAvailability` 单次 READ 的 MRP 元素行（mrpElementLines：WB/BA/BE + availQty1 + date），不额外调用 PO 列表能力，避免口径分叉。
- D4：计算放在服务端（Python agent 受治理链路），不由 LLM 计算；TS 语义工具契约层不做算术，只传递 requiredQuantity=目标需求总量。
- D5：单位取库存事实单位（预期 EA）；若库存事实单位与 requiredQuantity 隐含单位冲突，作为 fail-closed 情形处理（本次不做单位换算）。
- D6（用户已确认，2026-09-13）：共享理解（Outcome/Scope/口径 D1-D5/验收场景）经用户确认，进入 Build。

# Open questions

_（共享理解已于 2026-09-13 确认 → 见 D6，进入 Build。）_

# Verification expectations

- 新增确定性单元测试：缺口纯函数（按期/超期 PR/PO、零缺口、仅库存、无在途）、fail-closed 分支；Python 编排测试验证 WRITE 前先 READ 且 PR 数量=缺口；零缺口不产生 approval。
- TS 语义工具层：propose_replenishment 在零缺口时返回 complete+供应充足 narrative，无 approval 字段；有缺口时 approval.parameters.quantity=缺口数量且携带计算依据。
- 前端：审批卡片展示计算依据明细行；零缺口时不显示批准/拒绝按钮而显示供应充足说明。
- 用真实 dev 环境（gateway 连 SAP）对 P0227978AG/P0254684AF 做端到端复验，并与 MRP 事实行手工对账。
- 回归：现有补货审批流（批准→SAP 建 PR→PR 号回显）、库存诊断、发布门场景全部保持通过。
