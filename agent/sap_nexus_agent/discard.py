"""LLM output discard detection with structured reasons (Runbook 14).

Detects three classes of invalid LLM output and records each as a structured
reason string in ``IntentEnvelope.discard_reasons``:
- unknown_capability: capability_hint / capabilityId not in visible set
- technical_field: parameters containing baseUrl / rfcName / credential / etc.
- invalid_param: parameters containing __proto__ or other prototype pollution

The system SHALL NOT silently drop LLM output. ``discard_reasons`` is empty
when the LLM output is fully valid.
"""

from __future__ import annotations

# Technical field names that must never appear in LLM-produced parameters.
# Mirrors the OData override pattern in intent.py (technical safety fields
# the Java guard also rejects).
_TECHNICAL_FIELDS = frozenset({
    "baseurl",
    "rfcname",
    "credential",
    "credentialref",
    "credentials",
    "serviceurl",
    "servicepath",
    "serviceref",
    "endpoint",
    "method",
    "header",
    "headers",
    "csrf",
    "token",
    "authorization",
    "destination",
    "bindingid",
    "entityset",
    "executortype",
    "sapclient",
})

# Invalid parameter names (prototype pollution + similar).
_INVALID_PARAMS = frozenset({
    "__proto__",
    "constructor",
    "prototype",
    "__definegetter__",
    "__definesetter__",
    "__lookupgetter__",
    "__lookupsetter__",
})


def detect_discard_reasons(
    payload: dict[str, object],
    visible_capability_ids: frozenset[str],
) -> list[str]:
    """Detect discard reasons from an LLM payload.

    Args:
        payload: Raw LLM payload (may be in goals-based or legacy
            capabilityId-based shape).
        visible_capability_ids: Closed set of visible capability_ids.

    Returns:
        List of structured reason strings (e.g. ``"unknown_capability:Foo.Bar"``,
        ``"technical_field:baseUrl"``, ``"invalid_param:__proto__"``). Empty
        when the payload is fully valid.
    """
    if not isinstance(payload, dict):
        return []

    reasons: list[str] = []
    visible_lower = {cap_id.lower() for cap_id in visible_capability_ids}

    # 1. Check goals-based shape (Runbook 14 envelope format).
    goals = payload.get("goals")
    if isinstance(goals, list):
        for goal in goals:
            if not isinstance(goal, dict):
                continue
            hint = goal.get("capabilityHint")
            if isinstance(hint, str) and hint and hint.lower() not in visible_lower:
                reasons.append(f"unknown_capability:{hint}")
            params = goal.get("parameters")
            if isinstance(params, dict):
                reasons.extend(_check_params(params))

    # 2. Check candidates list (legacy multi-candidate shape).
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        for cand in candidates:
            if not isinstance(cand, dict):
                continue
            cap_id = cand.get("capabilityId")
            if isinstance(cap_id, str) and cap_id and cap_id.lower() not in visible_lower:
                reasons.append(f"unknown_capability:{cap_id}")
            params = cand.get("parameters")
            if isinstance(params, dict):
                reasons.extend(_check_params(params))

    # 3. Check top-level capabilityId (legacy single-capability shape).
    top_cap = payload.get("capabilityId")
    if isinstance(top_cap, str) and top_cap and top_cap.lower() not in visible_lower:
        reasons.append(f"unknown_capability:{top_cap}")

    # 4. Check top-level parameters (legacy single-capability shape).
    top_params = payload.get("parameters")
    if isinstance(top_params, dict):
        reasons.extend(_check_params(top_params))

    # Dedupe while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            unique.append(reason)
    return unique


def _check_params(params: dict[str, object]) -> list[str]:
    """Check parameter dict for technical fields and invalid params."""
    reasons: list[str] = []
    for key in params:
        key_lower = key.lower()
        if key_lower in _TECHNICAL_FIELDS:
            reasons.append(f"technical_field:{key}")
        elif key_lower in _INVALID_PARAMS:
            reasons.append(f"invalid_param:{key}")
    return reasons
