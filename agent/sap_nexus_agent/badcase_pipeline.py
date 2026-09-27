"""Bad-case review pipeline: annotated traces -> review artifacts + clusters.

Produces proposals only. Nothing is applied or written into evals/registry.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sap_nexus_agent.badcase_attribution import attribute_failure


def load_traces(path: Path) -> dict[str, dict[str, Any]]:
    traces: dict[str, dict[str, Any]] = {}
    for line in Path(path).read_text("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        traces[str(record["traceId"])] = record
    return traces


def is_mismatch(observed: dict[str, Any], expected: dict[str, Any]) -> bool:
    if observed.get("decision") != expected.get("expectedDecision"):
        return True
    expected_capability = expected.get("expectedCapabilityId")
    return bool(
        expected_capability and observed.get("capabilityId") != expected_capability
    ) or bool(expected.get("caliberMismatch"))


def candidate_case_id(trace_id: str, expected: dict[str, Any]) -> str:
    material = json.dumps(expected, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(f"{trace_id}|{material}".encode("utf-8")).hexdigest()[:12]
    return f"bc-candidate-{digest}"


def cluster_key(
    observed: dict[str, Any], category: str
) -> str:
    return "|".join([
        category,
        str(observed.get("capabilityId")),
        str(observed.get("errorType")),
    ])


def build_review_artifact(
    observed: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    attribution = attribute_failure(observed, expected)
    case_id = candidate_case_id(str(observed["traceId"]), expected)
    return {
        "schema": "sap-nexus.badcase-review.v1",
        "caseId": case_id,
        "status": "candidate",
        "sourceTraceId": observed["traceId"],
        "utteranceHash": observed.get("utteranceHash"),
        "observed": {
            "decision": observed.get("decision"),
            "capabilityId": observed.get("capabilityId"),
            "errorType": observed.get("errorType"),
        },
        "expected": {
            "decision": expected.get("expectedDecision"),
            "capabilityId": expected.get("expectedCapabilityId"),
        },
        "attribution": attribution.to_dict(),
        "clusterKey": cluster_key(observed, attribution.category),
        "utterance": None,
    }


def run_pipeline(
    *,
    traces_path: Path,
    annotations_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    traces = load_traces(traces_path)
    annotations = json.loads(Path(annotations_path).read_text("utf-8"))

    artifacts: list[dict[str, Any]] = []
    clusters: dict[str, list[str]] = {}
    for annotation in annotations:
        trace_id = str(annotation["traceId"])
        if trace_id not in traces:
            raise KeyError(f"annotation references unknown traceId: {trace_id}")
        observed = traces[trace_id]
        if not is_mismatch(observed, annotation):
            continue
        artifact = build_review_artifact(observed, annotation)
        artifacts.append(artifact)
        clusters.setdefault(artifact["clusterKey"], []).append(artifact["caseId"])

    # User-correction traces without an annotation: surface for review.
    annotated_ids = {str(a["traceId"]) for a in annotations}
    corrections = [
        {"traceId": trace_id, "utteranceHash": record.get("utteranceHash")}
        for trace_id, record in traces.items()
        if trace_id not in annotated_ids and record.get("userCorrection")
    ]

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for artifact in artifacts:
        (output_dir / f"{artifact['caseId']}.json").write_text(
            json.dumps(artifact, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    summary = {
        "schema": "sap-nexus.badcase-clusters.v1",
        "clusters": [
            {"clusterKey": key, "caseIds": case_ids}
            for key, case_ids in sorted(clusters.items())
        ],
        "corrections": corrections,
    }
    (output_dir / "clusters.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {
        "candidates": len(artifacts),
        "clusters": len(clusters),
        "corrections": len(corrections),
    }
