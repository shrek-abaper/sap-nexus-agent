"""OData $filter assembly.

Builds an OData ``$filter`` expression from semantic parameters and a
binding-declared ``filterMapping`` (semantic param name -> OData field name).

Read-only: this module only assembles a filter string; it never executes SAP.
"""

from __future__ import annotations

from typing import Mapping

# Param keys resolved to an ISO date (agent-side "relative_date" resolver,
# e.g. "近1年" -> "2025-08-26") that must render as a `ge datetime'...'` range
# clause instead of the default `eq 'value'` string-equality clause. A plain
# set keyed by param name (not filter_mapping) mirrors this module's existing
# convention: filter_mapping only ever carries semantic-param -> OData-field,
# never a value-formatting hint, so the hint lives beside the code that acts
# on it instead of widening filter_mapping's shape for one field.
_DATE_SINCE_PARAMS = {"createdSince"}


def build(parameters: Mapping[str, object], filter_mapping: Mapping[str, str]) -> str:
    """Assemble an OData ``$filter`` string.

    Iteration order follows ``filter_mapping`` (binding declaration order) so the
    output is deterministic. Parameters absent from the mapping, or with
    ``None``/empty-string values, are ignored. Single quotes in string values are
    escaped per the OData spec (``'`` -> ``''``).

    Returns an empty string when no parameter contributes a clause.
    """
    clauses: list[str] = []
    for param_key, odata_field in filter_mapping.items():
        value = parameters.get(param_key)
        if value is None:
            continue
        text = str(value)
        if text == "":
            continue
        if param_key in _DATE_SINCE_PARAMS:
            clauses.append(f"{odata_field} ge datetime'{text}T00:00:00'")
            continue
        escaped = text.replace("'", "''")
        clauses.append(f"{odata_field} eq '{escaped}'")
    return " and ".join(clauses)
