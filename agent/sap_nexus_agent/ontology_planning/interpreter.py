"""GoalInterpreter seam with a deterministic fixture-driven fake."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol


class GoalInterpreter(Protocol):
    def interpret(self, request: dict[str, Any], vocabulary: Any) -> dict[str, Any]:
        ...


class FakeGoalInterpreter:
    """Returns the checked-in draft script for a case (zero model calls)."""

    def __init__(self, drafts_dir: Path):
        self._drafts_dir = Path(drafts_dir)

    def interpret(self, request: dict[str, Any], vocabulary: Any = None) -> dict[str, Any]:
        draft_file = request.get("draftFile")
        if draft_file is None:
            draft_file = f"{request['caseId']}.json"
        path = self._drafts_dir / draft_file
        return json.loads(path.read_text(encoding="utf-8"))
