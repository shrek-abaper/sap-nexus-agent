from __future__ import annotations

from typing import Final

from sap_nexus_agent.registry_loader import CapabilityDescriptor

ACTIVE_LOCALE: Final = "zh-CN"


def _field_names(cap: CapabilityDescriptor, locale: str) -> dict[str, str]:
    intent_config = cap.intent_config
    if intent_config is None:
        return {}
    for loc, names in intent_config.field_names:
        if loc == locale:
            return dict(names)
    return {}


def render_clarify(
    cap: CapabilityDescriptor,
    missing: list[str],
    locale: str = ACTIVE_LOCALE,
) -> str | None:
    intent_config = cap.intent_config
    if not missing or intent_config is None:
        return None

    prompt = None
    for loc, cfg in intent_config.clarify_prompt:
        if loc == locale:
            prompt = cfg
            break

    if prompt is None:
        if locale != ACTIVE_LOCALE:
            names = _field_names(cap, ACTIVE_LOCALE)
            fields = ", ".join(names.get(name, name) for name in missing)
            return f"请提供: {fields}"
        return None

    missing_set = frozenset(missing)
    for case in prompt.cases:
        if case.missing == missing_set:
            return case.text

    if prompt.fallback_template is None:
        return None

    names = _field_names(cap, locale)
    fields = ", ".join(names.get(name, name) for name in missing)
    return prompt.fallback_template.replace("{fields}", fields)
