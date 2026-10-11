"""Current method only; historical reports are read without loading an engine."""
import json
from consensus_assurance.core.types import Analysis
from .prompts import manifest


def load_analysis(path):
    raw = json.loads(path.read_text())
    if raw.get("framework_revision") != manifest()["version"]:
        raise ValueError("Historical run uses an incompatible method; use its original Git revision")
    return Analysis.model_validate(raw)
