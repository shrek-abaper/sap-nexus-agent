#!/usr/bin/env python3
"""Codegen: registry/capabilities.yaml -> SKOS labels + SHACL input shapes.

Generated artifacts augment the authored capability individuals (subjects are
the existing ontologyIri nodes); authored YAML/OWL are never modified.

Outputs (deterministic: fixed ordering, no timestamps, no blank nodes):
  bundle/skos-capabilities.ttl   prefLabel / altLabel / definition / example
  bundle/shacl-inputs.ttl        one NodeShape per input with constraints
  bundle/manifest.json           sha256 of the two files
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

SPIKE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SPIKE_ROOT.parents[1]
BUNDLE_DIR = SPIKE_ROOT / "bundle"

import yaml  # noqa: E402

REGISTRY_PATH = REPO_ROOT / "registry" / "capabilities.yaml"

PREFIXES = (
    "@prefix sapnexus: <https://sap-nexus-agent.local/ontology#> .\n"
    "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n"
)

DATATYPE_FOR_TYPE = {
    "string": "xsd:string",
    "number": "xsd:decimal",
}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _literal(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
    return f'"{escaped}"'


def _plain_keywords(cap: dict) -> list[str]:
    """Strong trigger keywords that are plain text (regex-shaped keywords
    cannot serve as SKOS labels)."""
    intent = cap.get("intent") or {}
    keywords = [
        *intent.get("primaryKeywords", []),
        *(intent.get("triggerKeywords") or intent.get("primaryKeywords", [])),
    ]
    plain = [kw for kw in keywords if re.fullmatch(r"[\w一-鿿 ]+", kw)]
    return sorted(set(plain))


def build_skos(capabilities: list[dict]) -> str:
    lines = [
        PREFIXES,
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n",
        "sapnexus:CapabilityConceptScheme a skos:ConceptScheme ;",
        '    skos:prefLabel "SAP Nexus Capability Concept Scheme" .',
    ]
    for cap in capabilities:
        node = cap["ontologyIri"]
        lines.append(f"{node} a skos:Concept ;")
        # Labels: aliases plus the intent's plain strong keywords (the words
        # real utterances actually contain).
        alt_labels = sorted(set(cap.get("aliases", [])) | set(_plain_keywords(cap)))
        label_lines = [f'    skos:prefLabel {_literal(cap["name"])}@en']
        for alias in alt_labels:
            label_lines.append(f"    skos:altLabel {_literal(alias)}")
        if cap.get("description"):
            label_lines.append(f"    skos:definition {_literal(cap['description'])}")
        for example in cap.get("examples", []):
            label_lines.append(f"    skos:example {_literal(example)}")
        label_lines.append("    skos:topConceptOf sapnexus:CapabilityConceptScheme")
        label_lines.append("    skos:inScheme sapnexus:CapabilityConceptScheme")
        for index in range(len(label_lines) - 1):
            label_lines[index] += " ;"
        label_lines[-1] += " ."
        lines.extend(label_lines)
    return "\n".join(lines) + "\n"


def _shape_iri(capability_id: str, input_name: str) -> str:
    safe = capability_id.replace(".", "_").replace("-", "_")
    return f"sapnexus:Shape.{safe}.{input_name}"


def build_shacl(capabilities: list[dict]) -> str:
    lines = [
        PREFIXES,
        "@prefix sh: <http://www.w3.org/ns/shacl#> .\n",
    ]
    for cap in capabilities:
        for inp in cap.get("inputs", []):
            constraints: list[str] = []
            datatype = DATATYPE_FOR_TYPE.get(inp.get("type"))
            if datatype:
                constraints.append(f"    sh:datatype {datatype}")
            if inp.get("minLength") is not None:
                constraints.append(f"    sh:minLength {int(inp['minLength'])}")
            if inp.get("maxLength") is not None:
                constraints.append(f"    sh:maxLength {int(inp['maxLength'])}")
            if inp.get("pattern"):
                constraints.append(f"    sh:pattern {_literal(inp['pattern'])}")
            if not constraints:
                continue

            shape = _shape_iri(cap["capabilityId"], inp["name"])
            lines.append(f"{shape} a sh:NodeShape ;")
            lines.append(f"    sh:name {_literal(inp['name'])} ;")
            lines.append(f"    sapnexus:forCapability {cap['ontologyIri']} ;")
            lines.append(f'    sapnexus:forInput {_literal(inp["name"])} ;')
            lines.append(
                f"    sapnexus:required {'true' if inp.get('required') else 'false'} ;"
            )
            lines.append(" ;\n".join(constraints) + " .")
    return "\n".join(lines) + "\n"


def main() -> int:
    registry = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    capabilities = registry["capabilities"]

    skos = build_skos(capabilities)
    shacl = build_shacl(capabilities)

    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    (BUNDLE_DIR / "skos-capabilities.ttl").write_text(skos, encoding="utf-8")
    (BUNDLE_DIR / "shacl-inputs.ttl").write_text(shacl, encoding="utf-8")
    manifest = {
        "skos-capabilities.ttl": _sha256(skos),
        "shacl-inputs.ttl": _sha256(shacl),
    }
    (BUNDLE_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
