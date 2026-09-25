# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-1c65b1af0e6217147762bf9b2507365d75ee09fd612c17ec9c070175b71e2e10",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/c703cd5861c1404e8109a883457c97965bd290c8ae60e0f029a5c927d5ef21ab.json"
    ]
  },
  {
    "acceptance_id": "acceptance-77392f47f8fd7636ac05753c92e57498bef1323c4bc21e3b9f160dd0f5a40c93",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/c703cd5861c1404e8109a883457c97965bd290c8ae60e0f029a5c927d5ef21ab.json"
    ]
  },
  {
    "acceptance_id": "acceptance-7f72b27c3a75bca512323bfaaf8b852a7cf5d3ac78339be995f2787a63796d3a",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/c703cd5861c1404e8109a883457c97965bd290c8ae60e0f029a5c927d5ef21ab.json"
    ]
  },
  {
    "acceptance_id": "acceptance-840b54ace3652389030bbbfb62ebf501d80e94508dfb4ae5d537a999593f74aa",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/c703cd5861c1404e8109a883457c97965bd290c8ae60e0f029a5c927d5ef21ab.json"
    ]
  },
  {
    "acceptance_id": "acceptance-8d8592a0ff7e0b266da98e55893091fcd18f5a4fce77bdda8f0c39079d5d16ca",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/c703cd5861c1404e8109a883457c97965bd290c8ae60e0f029a5c927d5ef21ab.json"
    ]
  },
  {
    "acceptance_id": "acceptance-a7c5d0483e8b59b68e71c8dce5eecb08bedfe5433998fb777d971d5d109c6eb6",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/c703cd5861c1404e8109a883457c97965bd290c8ae60e0f029a5c927d5ef21ab.json"
    ]
  },
  {
    "acceptance_id": "acceptance-bad7d9f44f31909ec38d4f3f18448452cb16aaddfebecb0cebbf260be20476d1",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/c703cd5861c1404e8109a883457c97965bd290c8ae60e0f029a5c927d5ef21ab.json"
    ]
  },
  {
    "acceptance_id": "acceptance-cb6102f229efaa92d7b91b69b269c7c3f7554f5097e342025797d77b6eb2a879",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/c703cd5861c1404e8109a883457c97965bd290c8ae60e0f029a5c927d5ef21ab.json"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

| 命令 | 结果 |
|---|---|
| `pytest agent/tests`（240s） | **1651 passed, 1 skipped, 2 xfailed** |
| test_identity（8） | passed：稳定/顺序无关身份、类型与取值区分、空输入拒绝、new/direct/alias、别名冲突在注册时拦截 |

# Skipped checks

无未运行的必需检查。

# Spec consistency

规格 `identity-foundation` 全部满足：

- canonical identity 内容寻址、确定性可复现、与系统编码无关；
- resolve 返回 direct/alias/new；别名命中采用被映射身份；
- 同一别名重复绑定到不同身份在 register_alias 阶段即拒绝（IdentityConflict）；
- 未知类型/空标识符 fail closed；无网络/SAP 访问，不参与授权。

# Known limitations and risks

- 跨系统概率匹配/自动合并不在内（单一数据源）；待第二数据源出现时基于 alias 钩子扩展。

# Conclusion

**pass**——8/8 acceptance 通过；1651 测试全绿；身份解析正确，行为不变。
