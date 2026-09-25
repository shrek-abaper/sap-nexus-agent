# Outcome

提供确定性的 **Identity Foundation**：对业务对象类型与 keyedBy 标识符派生稳定 canonical
identity，支持直接/别名解析与冲突检测，并为未来跨系统 MDM 合并预留 alias 钩子。
不实现跨系统自动匹配（当前单一 SAP 源）。

# Scope

1. **canonical identity 派生**：`identity(object_type, sorted identifiers)` 内容寻址
   （sha256），与系统编码无关、同输入恒等。
2. **IdentityRegistry**：
   - resolve：未登记标识符集合时按规则派生并登记，返回 (identity, kind)
     kind ∈ `direct / alias / new`；
   - register_alias：把外部/同义标识符映射到既有 canonical identity；
   - 冲突：同一标识符已指向不同 canonical 时抛 IdentityConflict，不静默归并。
3. 标识符合法性对照 fact-types 的 businessObject + keyedBy（类型缺失即拒绝）。
4. 纯函数式、无 IO；不修改其他状态。

# Non-goals

- 跨系统自动匹配/合并、概率实体解析（无第二数据源）；
- 不改 MatchDecision、Gateway、审批、WRITE 链、补货、Impact Analysis；
- 解析不参与授权（resolve/enforce 边界不变）。

# Acceptance examples

- resolve(MaterialInfo, {material: P0226750AD, plant: 5260})：两次返回同一 canonical，kind=new 后再次=direct；
- 登记别名后用别名 resolve：kind=alias，canonical 相同；
- 同一标识符被映射到另一 identity：抛 IdentityConflict；
- 空标识符/未知 object 类型：拒绝（fail closed）。

# Constraints and invariants

- identity 派生确定性、可复现；冲突必须显式报错；不做网络/SAP 访问。

# Decisions

- D1（用户授权，自主）：只做 Identity 基础与别名钩子，跨系统合并待第二数据源触发。

# Open questions

无。CONFIRM 基于用户预授权。

# Verification expectations

- 全量 agent 测试 + 全部 evals 绿；identity 派生可复现；别名/冲突/空输入正确。
