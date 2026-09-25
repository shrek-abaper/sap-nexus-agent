# Verification

# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-18655a20b60fce895907898370a4c47b1f1bf219b62fb8131d2a60f886c7e1b2",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/a1370df8acc306a1d7e7e8865adc4fd59cb298bb158ce50725e470ba96a208ac.json"
    ]
  },
  {
    "acceptance_id": "acceptance-739f008e76d75d5e5763f5eeda93a57ca43c3e79c6b12945453f63ff1ebd61f0",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/349bb26a5c307717f6b943bacef82bfeeba80a48603110b77885918c2b3cf716.json"
    ]
  },
  {
    "acceptance_id": "acceptance-778ce08178164b8c225c46c2c689ba93045f109822adddcfec011e2c7625673b",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/d469e31ee96ab141aadae37500836f0e64d605fc54770701b3af1e0f4d2a2369.json"
    ]
  },
  {
    "acceptance_id": "acceptance-8df5cefb364589f2e3f7566e6098450d0d9aaba48b3d2d961d4e3e82e28b3375",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/d469e31ee96ab141aadae37500836f0e64d605fc54770701b3af1e0f4d2a2369.json"
    ]
  },
  {
    "acceptance_id": "acceptance-9530e658490dc439bd1abe92029a43e65b2da4b7a26b0e34ecb90b7cb39ab02e",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/f4c6ef28d80938c47e5e21cd58faaf494c71161d97eeb08d27346237cd95a28a.json"
    ]
  },
  {
    "acceptance_id": "acceptance-b5b865b15951e9fdfa31dbc7661d781dab76f71e3cfabe0b3130e263dfcf96d7",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/349bb26a5c307717f6b943bacef82bfeeba80a48603110b77885918c2b3cf716.json"
    ]
  },
  {
    "acceptance_id": "acceptance-c0f06fc5bedeff39996dd43ef661f13cc40ab8a9e9cb71a4bd57b41d6898f1ec",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/d469e31ee96ab141aadae37500836f0e64d605fc54770701b3af1e0f4d2a2369.json"
    ]
  },
  {
    "acceptance_id": "acceptance-d69945096607ee03da922d343717e2587fb9b145f466f53bcc9cef40791a3efc",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/d469e31ee96ab141aadae37500836f0e64d605fc54770701b3af1e0f4d2a2369.json"
    ]
  },
  {
    "acceptance_id": "acceptance-e62d5a0a33a01e57a6ecbbbdcdc7e2608620dd60d07486488f66f24cc646fa42",
    "status": "passed",
    "evidence_refs": [
      "runtime/evidence/receipts/54e4b8aa94fffef1ab71897d375b22591cf09fac7ca473ab35dd145744fa3a05.json"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->


# Commands and results

## git status --short

```text
 M agent/tests/test_semantic_planning_contract.py
 M docs/proposals/rest2rfc-migration-assessment.md
 M evals/matcher_cases.yaml
 M registry/README.md
 M registry/capabilities.yaml
 M registry/executor-bindings.yaml
 M tests/live/test_rest2rfc_ap_equivalence.py
?? .comet/current-change.json
?? docs/comet/changes/
```

## Registry contract（receipt 54e4b8aa...）

`.venv/bin/python scripts/validate-registry-contract.py registry/capabilities.yaml`

结果：`Registry contract valid`（exit 0）。

## Gateway Java tests（receipt 349bb26a...）

`./gradlew -p services/gateway --no-daemon test`

结果：`BUILD SUCCESSFUL`。

## Agent full tests（receipt f4c6ef28...）

`.venv/bin/python -m pytest agent/tests -q`

结果：**1656 passed, 1 skipped, 2 xfailed**（binding 数增至 10 后索引同步更新）。

## Evals

8 evals 全过：7/7、13/13、9/9、23/23、3/3、3/3（pending 计数为既有 PENDING 项）。
snapshot pin 14 处更新为
`sha256:231c8a6959ce72634c2a05383eb083c52ed32a25cc0a2069cb5e98560399a5a2`。

## Live 等价（receipt d469e31e...）

迁移后重跑参数化 harness（直接 SICF ↔ Gateway REST_JSON adapter）：

```text
FI.AP: 28197 rows == baseline 28197
FI.AR: 1355 rows  == baseline 1355
SD:    5164 rows  == baseline 5164
```

三路均逐行全字段等价；Gateway 响应 executor.type 均为 REST_JSON，证实翻转生效。

# Skipped checks

- frontend verify：不触及 frontend，按 §4 不运行。
- openspec strict：16 项失败为既有技术债（stash 验证干净 main 同样 exit 1），与本
  变更无关。

# Spec consistency

- 实现与完整目标规格一致：mapping 零改动；旧 JCO bindings 保留；连接/凭据仍为
  Gateway 受控配置；SD 业务错误时非 200 fail-closed 的取舍未改变。

# Known limitations and risks

- SD / Inventory 类 RETURN 文本在 SICF 下缺失（EXPORTING）；本迁移的 SD 主事实
  等价、错误分类不变，但错误消息文本不可得——与迁移前评估记录一致。
- MM.Inventory 未在本次范围内（returnMessages 差异待接受）。

# Conclusion

**pass**：9/9 验收项绑定当前 revision 真实 receipts；contract、Gateway、agent
1656、8 evals、迁移后三能力 live 等价（28,197 / 1,355 / 5,164 行）全绿。
