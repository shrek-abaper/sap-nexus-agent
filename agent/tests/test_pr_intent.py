from __future__ import annotations

from sap_nexus_agent.intent import parse_intent


def test_full_direct_pr_create():
    text = "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01 采购组 601"
    result = parse_intent(text)
    assert result.intent == "pr_create"
    assert result.parameters.get("material") == "M001"
    assert result.parameters.get("plant") == "1000"
    assert result.parameters.get("quantity") == "100"
    assert result.parameters.get("unit") == "EA"
    assert result.parameters.get("delivery_date") == "2026-08-01"
    assert result.parameters.get("purchasing_group") == "601"
    assert result.missing_parameters == []


def test_pr_create_accepts_compact_sap_date_and_normalizes_to_iso():
    """用户按 SAP DATS 存储格式输入紧凑日期时，应归一化为 ISO 供下游消费。"""
    text = "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 20260801 采购组 601"
    result = parse_intent(text)
    assert result.parameters.get("delivery_date") == "2026-08-01"
    assert result.missing_parameters == []


def test_missing_required_params_triggers_clarification():
    text = "建个采购申请"
    result = parse_intent(text)
    assert result.intent == "pr_create"
    assert "material" in result.missing_parameters
    assert "plant" in result.missing_parameters
    assert "quantity" in result.missing_parameters
    assert "purchasing_group" in result.missing_parameters
    assert result.clarification is not None


def test_missing_purchasing_group_triggers_clarification():
    text = "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01"
    result = parse_intent(text)

    assert result.missing_parameters == ["purchasing_group"]
    assert result.clarification is not None
    assert "采购组" in result.clarification


def test_indirect_missing_cost_center_triggers_clarification():
    text = "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01 采购组 601 间采 K"
    result = parse_intent(text)
    assert result.parameters.get("acct_assgn_cat") == "K"
    assert "cost_center" in result.missing_parameters
    assert result.clarification is not None
    assert "成本中心" in result.clarification


def test_indirect_with_cost_center_no_missing():
    text = "给物料 M001 工厂 1000 建 100 EA 采购申请 交货 2026-08-01 采购组 601 间采 K 成本中心 1000"
    result = parse_intent(text)
    assert result.parameters.get("acct_assgn_cat") == "K"
    assert result.parameters.get("cost_center") == "1000"
    assert "cost_center" not in result.missing_parameters
