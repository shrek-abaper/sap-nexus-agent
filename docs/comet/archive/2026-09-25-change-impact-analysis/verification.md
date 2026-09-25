# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-5505c382c674785e8db98b379a5870e01e43a927e2dd952b630d36211ccb711e",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/6b8efa3de7f877fe5a7b61f521c6d89c47165030c2b7519d173ad90b0786189e.json"
    ]
  },
  {
    "acceptance_id": "acceptance-72928fb686cfa8adf12c0218e427816398814254872baf6b6065a724f80a3798",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/6b8efa3de7f877fe5a7b61f521c6d89c47165030c2b7519d173ad90b0786189e.json"
    ]
  },
  {
    "acceptance_id": "acceptance-8369994c7d012c3e389a43ca543eb82c78f05b61135fc4dac69e08f6bf7d07b2",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/6b8efa3de7f877fe5a7b61f521c6d89c47165030c2b7519d173ad90b0786189e.json"
    ]
  },
  {
    "acceptance_id": "acceptance-88c091e498c19928a1262c42668f043ed0bc1d70403eab6164c6fcf89474516d",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/6b8efa3de7f877fe5a7b61f521c6d89c47165030c2b7519d173ad90b0786189e.json"
    ]
  },
  {
    "acceptance_id": "acceptance-91c5cba0c0d2884fb61321e29e99f51b83b36a7315f9d946e82aff890db9ffa1",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/6b8efa3de7f877fe5a7b61f521c6d89c47165030c2b7519d173ad90b0786189e.json"
    ]
  },
  {
    "acceptance_id": "acceptance-a71b03f72a51e77edbc62a439ff7bfd6bae1a4cc29e45eb8b5f4666cfedba92e",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/6b8efa3de7f877fe5a7b61f521c6d89c47165030c2b7519d173ad90b0786189e.json"
    ]
  },
  {
    "acceptance_id": "acceptance-cd924c42abbe6b76c51c9eb148995172da9ef9d74d0a75f165c629f2be6ad2ab",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/6b8efa3de7f877fe5a7b61f521c6d89c47165030c2b7519d173ad90b0786189e.json"
    ]
  },
  {
    "acceptance_id": "acceptance-d20cf8e92c22c66e2646d70a6fe926f3166db1c547ef680c73579df61503a058",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/6b8efa3de7f877fe5a7b61f521c6d89c47165030c2b7519d173ad90b0786189e.json"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

| 命令 | 结果 |
|---|---|
| `pytest agent/tests`（240s） | **1643 passed, 1 skipped, 2 xfailed** |
| test_impact_analysis（9） | passed：规则/类型入口、传递闭包、排他性、dict/object 审批、空变更、可序列化 |

# Skipped checks

无未运行的必需检查。

# Spec consistency

规格 `change-impact-analysis` 全部满足：

- 影响图确定性、可复现；
- 规则→能力→factType→下游能力的传递闭包正确；
- affected_approvals 仅从调用方传入的活跃审批只读识别；
- 全程无状态修改、无网络/SAP 访问，结果不参与授权。

# Known limitations and risks

- 活跃审批由调用方传入，本模块不直接读取 Java gateway 的审批 store；接入真实部署时由边界适配。
- 不含自动重算（刻意为之，当前无跨版本事实留存）。

# Conclusion

**pass**——8/8 acceptance 通过；1643 测试全绿；只读影响分析正确，行为不变。
