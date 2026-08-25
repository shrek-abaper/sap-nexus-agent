#!/usr/bin/env python3
"""Print the derived data dependency view and write it to ``runtime/``.

Invariant 3's reading instrument. ``ontology/capability-relations.yaml`` carries
only relations that *cannot* be inferred from data shape, so the acceptance
criterion for derived dependencies is never "the file is non-empty" — it is
"this view is non-empty". This script is how a human checks that without
trusting a summary.

It never writes to ``registry/`` or ``ontology/``. The registry is the execution
boundary; a derived view is a report about it, and writing a report back into it
would launder derivation into authored governance. The output path is under
``runtime/``, which is gitignored.

Exit codes follow ``scripts/validate-registry-contract.py``: 0 on success, 1 on
a source load or validation failure, 2 on usage error. An **empty** view and a
view carrying **diagnostics** are both successes — emptiness is a legitimate
state (no shipped input declares ``satisfiableByFactType`` yet), and a
diagnostic is a report of an unresolved modelling decision, not a failure of
this script. Task 3.6's validator rule is what turns a *derivable* relation
hand-written as ``origin: manual`` into an error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_ROOT = REPO_ROOT / "agent"
for path in (str(REPO_ROOT), str(AGENT_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from sap_nexus_agent.semantic_planning.derivation import (  # noqa: E402
    derive_data_dependencies,
)
from sap_nexus_agent.semantic_planning.loader import (  # noqa: E402
    SourceLoadError,
    load_semantic_sources,
)
from sap_nexus_agent.semantic_planning.snapshot import (  # noqa: E402
    build_registry_snapshot,
)

ARTIFACT_NAME = "derived-data-dependencies"
ARTIFACT_VERSION = 1
DEFAULT_OUTPUT = Path("runtime") / f"{ARTIFACT_NAME}.json"


def build_artifact(repo_root: Path) -> dict:
    """Assemble the view plus the snapshot it was derived from.

    ``snapshotId`` is not decoration: a derived view is only meaningful against
    the registry state that produced it, and defect D4 will make upstream Fact
    provenance part of the approval subject. An artifact that cannot say which
    snapshot it describes could not be used as evidence for that.

    Assembled here rather than in ``derivation.py`` on purpose — that module's
    import set is asserted against an allowlist (invariant 2: it authors, it
    never executes), and importing the snapshot builder there would widen it.
    """
    sources = load_semantic_sources(repo_root)
    view = derive_data_dependencies(sources)
    return {
        "artifact": ARTIFACT_NAME,
        "version": ARTIFACT_VERSION,
        "snapshotId": build_registry_snapshot(sources).snapshot_id,
        **view.to_dict(),
        "relations": list(view.to_relations()),
    }


def format_summary(artifact: dict) -> str:
    """One line per edge and per diagnostic, then the counts.

    Diagnostics are printed in full rather than counted: the candidates are the
    whole point — a reader has to see *which* sources were tied to break the
    tie in the registry.
    """
    lines: list[str] = []
    for edge in artifact["edges"]:
        lines.append(
            f"edge {edge['consumerCapabilityId']}.{edge['consumerInputName']}"
            f" <- {edge['producerCapabilityId']}.{edge['producerOutputName']}"
            f" via {edge['factTypeId']}.{edge['factFieldName']}"
            f" ({edge['semanticType']})"
        )
    for diagnostic in artifact["diagnostics"]:
        lines.append(
            f"{diagnostic['kind']} {diagnostic['consumerCapabilityId']}"
            f".{diagnostic['consumerInputName']}"
            f" wants {diagnostic['semanticType']}"
            f" from {diagnostic['factTypeId']};"
            f" {diagnostic['candidateKind']} candidates:"
            f" {', '.join(diagnostic['candidates'])}"
        )
    lines.append(
        f"derived {len(artifact['edges'])} edge(s), "
        f"{len(artifact['relations'])} relation(s), "
        f"{len(artifact['diagnostics'])} diagnostic(s)"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) > 1:
        print(
            "Usage: derive-data-dependencies.py [output-file]",
            file=sys.stderr,
        )
        return 2
    output = Path(args[0]) if args else REPO_ROOT / DEFAULT_OUTPUT
    try:
        artifact = build_artifact(REPO_ROOT)
    except SourceLoadError as exc:
        print(f"SCHEMA_INVALID {exc.path}: {exc.message}", file=sys.stderr)
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(artifact, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    print(format_summary(artifact))
    print(f"Derived data dependency view written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
