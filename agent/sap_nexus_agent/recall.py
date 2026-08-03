"""Closed-set recall stage (Runbook 14).

Three independent recall sources merged + deduped:
- lexical recall: keyword match against capability name/description
- alias recall: capability aliases from registry
- example recall: capability examples from registry

Output is advisory only: ``list[str]`` of capability_ids. Does NOT produce a
MatchDecision and does NOT use embedding / vector store / RAG.
"""

from __future__ import annotations

from sap_nexus_agent.registry_loader import IntentCatalog


def recall(
    utterance: str,
    visible_capability_ids: frozenset[str],
    catalog: IntentCatalog,
) -> list[str]:
    """Run closed-set recall over the visible capability set.

    Args:
        utterance: User's raw utterance.
        visible_capability_ids: Closed set of capability_ids visible to this
            conversation (from ``VisibleCapabilitySet``).
        catalog: IntentCatalog providing name/description/aliases/examples.

    Returns:
        Deduped list of capability_ids that matched at least one recall
        source. Order: lexical hits first, then alias, then example; each
        capability appears at most once.
    """
    if not utterance or not visible_capability_ids:
        return []

    text = utterance.lower()
    lexical_hits: list[str] = []
    alias_hits: list[str] = []
    example_hits: list[str] = []

    for cap in catalog.capabilities:
        if cap.capability_id not in visible_capability_ids:
            continue

        # Lexical: keyword match against name/description (case-insensitive).
        # For each capability, check if any keyword from the utterance appears
        # in name/description OR vice versa (catches '查库存' -> '库存').
        name_desc = f"{cap.name} {cap.description}".lower()
        if _text_overlaps(text, name_desc):
            lexical_hits.append(cap.capability_id)
            continue

        # Alias: substring match against any alias.
        if any(alias.lower() in text for alias in cap.aliases):
            alias_hits.append(cap.capability_id)
            continue

        # Example: substring match — utterance resembles a registered example.
        if any(ex.lower() in text or text in ex.lower() for ex in cap.examples):
            example_hits.append(cap.capability_id)
            continue

    # Merge + dedupe by capability_id, preserving source order (lexical,
    # alias, example).
    seen: set[str] = set()
    candidates: list[str] = []
    for cap_id in (*lexical_hits, *alias_hits, *example_hits):
        if cap_id not in seen:
            seen.add(cap_id)
            candidates.append(cap_id)
    return candidates


def _text_overlaps(text: str, haystack: str) -> bool:
    """Return True if ``text`` and ``haystack`` share any keyword overlap.

    Strategy:
    1. Whitespace tokens of ``text`` checked against ``haystack`` (catches
       English / alphanumeric identifiers like 'PO' / 'PR').
    2. For Chinese text (no whitespace), check if the full ``text`` is a
       substring of ``haystack`` (catches '库存查询' -> '...库存...').
    3. Also check the reverse: any keyword from ``haystack`` that appears in
       ``text`` (catches '查库存' where '库存' is a name token).
    """
    if not text:
        return False
    # Strategy 1: whitespace tokens.
    tokens = text.split()
    for token in tokens:
        if token and token in haystack:
            return True
    # Strategy 2: full text substring (Chinese without whitespace).
    if text in haystack:
        return True
    # Strategy 3: haystack tokens in text.
    for token in haystack.split():
        if len(token) >= 2 and token in text:
            return True
    return False
