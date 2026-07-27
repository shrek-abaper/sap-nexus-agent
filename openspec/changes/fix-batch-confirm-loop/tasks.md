## 1. 修复 _last_context_from_outcome

- [ ] 1.1 `_last_context_from_outcome` 增加 `awaiting_batch_confirm` 早返回 None（类比 `awaiting_approval`，在 SELECT 分支之前）
- [ ] 1.2 测试：awaiting_batch_confirm outcome -> lastContext=None（不返回 SELECT）
- [ ] 1.3 全量回归通过

## 2. 验证

- [ ] 2.1 `openspec validate --all --strict` 通过
- [ ] 2.2 pytest 回归
- [ ] 2.3 verify-agent-callplan-evidence.sh 通过
