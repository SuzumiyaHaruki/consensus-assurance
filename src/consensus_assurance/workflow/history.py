"""Current structured state; old archives remain raw, read-only historical records."""
import json
from pathlib import Path
from consensus_assurance.core.types import Analysis
from .prompts import manifest


def load_analysis(path):
    value = json.loads(Path(path).read_text())
    revision = value.get("framework_revision")
    if revision is not None and revision != manifest()["version"]:
        raise ValueError("Historical framework revision is read-only; use its saved report or an explicit offline child import")
    return Analysis.model_validate(value)
