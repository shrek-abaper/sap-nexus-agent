"""Shared test fixtures for sap_nexus_agent unit tests.

Prevents unit tests from hitting the real LLM gateway by ensuring
LLM_API_KEY / LLM_BASE_URL are empty, so OpenAiCompatibleLlmClient()
raises LlmUnavailable and narrator/orchestrator fall back to templates.

Tests that need the LLM path inject a fake client explicitly and do not
rely on OpenAiCompatibleLlmClient() construction.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_llm_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_BASE_URL", "")


@pytest.fixture(autouse=True)
def _disable_decision_trace(monkeypatch):
    # Keep test runs from appending to the real runtime/traces/decisions.jsonl.
    # Tests that exercise recording override this with their own temp path.
    monkeypatch.setenv("SAP_NEXUS_DECISION_TRACE", "off")
