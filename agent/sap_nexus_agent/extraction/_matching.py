from __future__ import annotations

import re
from typing import Final

from sap_nexus_agent.registry_loader import IntentCatalog, MatcherConfig, ValueFilters

EMPTY_FILTERS: Final = ValueFilters()
_CHINESE_LITERAL: Final = re.compile(r"[\u4e00-\u9fff]+")


def keyword_matches(keyword: str, text: str) -> bool:
    try:
        return re.search(keyword, text) is not None
    except re.error:
        return keyword in text


def match_value(
    matcher: MatcherConfig,
    text: str,
    catalog: IntentCatalog,
    filters: ValueFilters,
    excluded_values: set[str],
) -> str | None:
    if matcher.kind == "semanticType":
        entry = catalog.semantic_types.find(matcher.ref or "")
        if entry is None:
            return None
        nested_filters = entry.filters if filters == EMPTY_FILTERS else filters
        for entry_matcher in entry.matchers:
            value = match_value(
                _merge_matcher(entry_matcher, matcher), text, catalog, nested_filters, excluded_values,
            )
            if value is not None:
                return value
        return None

    compiled = _compile_matcher(matcher)
    if compiled is None:
        return _constant_keyword_fallback(matcher, text)
    if matcher.scan == "all":
        for regex_match in compiled.finditer(text):
            value = _captured_value(regex_match, matcher)
            if _accepted(value, filters, excluded_values):
                return value
        return None
    regex_match = compiled.search(text)
    if regex_match is None:
        return _constant_keyword_fallback(matcher, text)
    value = _captured_value(regex_match, matcher)
    return value if _accepted(value, filters, excluded_values) else None


def input_filters(matcher: MatcherConfig, catalog: IntentCatalog) -> ValueFilters:
    if matcher.kind != "semanticType":
        return EMPTY_FILTERS
    entry = catalog.semantic_types.find(matcher.ref or "")
    return entry.filters if entry is not None else EMPTY_FILTERS


def _compile_matcher(matcher: MatcherConfig) -> re.Pattern[str] | None:
    flags = re.IGNORECASE if matcher.ignore_case else 0
    try:
        return re.compile(matcher.pattern or "", flags)
    except re.error:
        return None


def _captured_value(regex_match: re.Match[str], matcher: MatcherConfig) -> str:
    if matcher.kind == "keyword" and matcher.value is not None:
        return matcher.value
    groups = [group for group in regex_match.groups() if group is not None]
    return groups[0] if groups else regex_match.group(0)


def _constant_keyword_fallback(matcher: MatcherConfig, text: str) -> str | None:
    if matcher.kind != "keyword" or matcher.value is None or matcher.pattern is None:
        return None
    return matcher.value if any(literal in text for literal in _CHINESE_LITERAL.findall(matcher.pattern)) else None


def _accepted(value: str, filters: ValueFilters, excluded_values: set[str]) -> bool:
    return _passes_filters(value, filters) and not _is_excluded(value, excluded_values, filters)


def _passes_filters(value: str, filters: ValueFilters) -> bool:
    if filters.min_length is not None and len(value) < filters.min_length:
        return False
    compare = value.upper() if filters.to_upper_compare else value
    if compare in filters.not_in:
        return False
    return not any(value.startswith(prefix) for prefix in filters.prefix_blacklist)


def _is_excluded(value: str, excluded_values: set[str], filters: ValueFilters) -> bool:
    compare = value.upper() if filters.to_upper_compare else value
    return compare in excluded_values


def _merge_matcher(entry_matcher: MatcherConfig, wrapper: MatcherConfig) -> MatcherConfig:
    scan = wrapper.scan if wrapper.scan != "first" else entry_matcher.scan
    return MatcherConfig(
        kind=entry_matcher.kind,
        pattern=wrapper.pattern or entry_matcher.pattern,
        value=wrapper.value or entry_matcher.value,
        ref=entry_matcher.ref,
        ignore_case=entry_matcher.ignore_case or wrapper.ignore_case,
        scan=scan,
    )
