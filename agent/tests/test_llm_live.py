import os

import pytest

from sap_nexus_agent.llm_client import LlmUnavailable, OpenAiCompatibleLlmClient
from sap_nexus_agent.llm_intent import parse_with_llm


@pytest.mark.skipif(os.getenv("SAP_NEXUS_LLM_LIVE") != "1", reason="set SAP_NEXUS_LLM_LIVE=1 to run live LLM smoke")
def test_live_llm_extracts_inventory_intent_without_printing_secrets():
    try:
        result = parse_with_llm("请帮我查一下 DEMOA1 在 1000 的可用库存", OpenAiCompatibleLlmClient())
    except LlmUnavailable as exc:
        pytest.fail(f"live LLM unavailable: {exc}")

    assert result.intent == "inventory_availability"
    assert result.parameters.get("material") == "DEMOA1"
    assert result.parameters.get("plant") == "1000"
    assert result.contains_rfc_name is False
