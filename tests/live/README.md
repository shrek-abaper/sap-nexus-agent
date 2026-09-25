# Live test harnesses

默认全部跳过，仅在显式环境开关下运行。这些测试需要真实系统与有效凭据，
不属于 CI 回归。

## rest2rfc AP 等价验证

`test_rest2rfc_ap_equivalence.py` 比对 `BAPI_AP_ACC_GETOPENITEMS` 经纯 ABAP
rest2rfc SICF 网关与现有 JCO_RFC（经 Java Gateway）的 open items 结果。

运行前置：Java Gateway 已启动；rest2rfc SICF 节点已激活且函数已在
`ZTIF_GENERAL_CON` 注册。凭据仅从环境变量读取。

```bash
SAP_REST2RFC_LIVE=1 \
SAP_REST2RFC_BASE_URL=http://<host>:<port> \
REST2RFC_VENDOR=<vendor> REST2RFC_COMPANY_CODE=<companyCode> \
.venv/bin/python -m pytest tests/live/test_rest2rfc_ap_equivalence.py -v -s
```
