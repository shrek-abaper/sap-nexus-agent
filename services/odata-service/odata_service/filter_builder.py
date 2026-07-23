"""OData $filter assembly.

Builds an OData ``$filter`` expression from semantic parameters and a
binding-declared ``filterMapping`` (semantic param name -> OData field name).

Read-only: this module only assembles a filter string; it never executes SAP.
"""

from __future__ import annotations

from typing import Mapping


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
        escaped = text.replace("'", "''")
        clauses.append(f"{odata_field} eq '{escaped}'")
    return " and ".join(clauses)
