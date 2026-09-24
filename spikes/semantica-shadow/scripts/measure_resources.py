#!/usr/bin/env python3
"""Resource and stability measurements for Task 5.

Measures, over a fresh process:
  graph load time and peak RSS,
  per-query latency (validate / preconditions / permission / recall),
  repeated-run consistency.

No SAP, no network. Deterministic; the same run repeated yields the same
timings within jitter. Timings are recorded in ms with the raw samples.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

SPIKE_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(Path(__file__).parent),
    "/home/shrek/projects/GitHub_Projects/sap-nexus-agent",
    "/home/shrek/projects/GitHub_Projects/sap-nexus-agent/agent",
]

import yaml  # noqa: E402

from query_shadow import (  # noqa: E402
    check_permission,
    evaluate_preconditions,
    load_graph,
    recall_capabilities,
    validate_input,
)

REPEAT = 50


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 3)


def measure() -> dict[str, Any]:
    rss_before = _rss()
    start = time.perf_counter()
    graph = load_graph()
    load_ms = _ms(start)
    rss_after = _rss()

    triple_count = len(graph)
    samples: dict[str, list[float]] = {
        "validate": [],
        "preconditions": [],
        "permission": [],
        "recall": [],
    }

    approval = {
        "capabilityId": "MM.PR.CreateDraft",
        "parameterSnapshotHash": "hash-1",
        "status": "approved",
        "expiresAt": "2099-01-01T00:00:00+00:00",
    }
    slots = {
        "material": "P0226750AD", "plant": "5260", "quantity": 100,
        "unit": "EA", "delivery_date": "2026-10-01", "purchasing_group": "601",
    }

    for _ in range(REPEAT):
        start = time.perf_counter()
        validate_input(graph, "MM.Inventory.GetAvailability", "plant", "5260")
        samples["validate"].append(_ms(start))

        start = time.perf_counter()
        evaluate_preconditions(graph, "MM.Inventory.GetAvailability", slots)
        samples["preconditions"].append(_ms(start))

        start = time.perf_counter()
        check_permission(
            graph, "MM.PR.CreateDraft", approval, parameter_snapshot_hash="hash-1"
        )
        samples["permission"].append(_ms(start))

        start = time.perf_counter()
        recall_capabilities(graph, "查物料库存")
        samples["recall"].append(_ms(start))

    rss_peak = _rss()
    return {
        "tripleCount": triple_count,
        "load": {
            "ms": load_ms,
            "rssBeforeKb": rss_before,
            "rssAfterLoadKb": rss_after,
            "rssPeakKb": rss_peak,
        },
        "repetitions": REPEAT,
        "queries": {
            name: {
                "minMs": min(values),
                "medianMs": round(statistics.median(values), 3),
                "maxMs": max(values),
                "samples": values,
            }
            for name, values in samples.items()
        },
    }


def _rss() -> int:
    """Current resident set size in kB (Linux /proc)."""
    text = Path("/proc/self/status").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    return 0


def main() -> int:
    result = measure()
    out = SPIKE_ROOT / "reports" / "resource-measurement.json"
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"graph: {result['tripleCount']} triples | load {result['load']['ms']} ms")
    print(
        f"RSS {result['load']['rssBeforeKb']} -> "
        f"{result['load']['rssPeakKb']} kB"
    )
    for name, stats_ in result["queries"].items():
        print(
            f"{name:14s} median {stats_['medianMs']:8.3f} ms "
            f"(min {stats_['minMs']}, max {stats_['maxMs']})"
        )
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
