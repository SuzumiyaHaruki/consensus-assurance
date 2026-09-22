from pathlib import Path
from typing import Any, Literal
from pydantic import Field, model_validator
from .types import ActivityClass, Record


class Budget(Record):
    agent_calls: int = Field(default=8, ge=0)
    model_checks: int = Field(default=4, ge=0)
    revisions: int = Field(default=3, ge=0)
    repair_attempts: int = Field(default=4, ge=0)
    repair_stagnation: int = Field(default=2, ge=1)
    repeated_error_revisions: int = Field(default=1, ge=0)
    replays: int = Field(default=1, ge=0)
    action_timeout: float = Field(default=120, gt=0)
    total_seconds: float = Field(default=900, gt=0)

    experiments: int = Field(default=4, ge=0)
    calibration_checks: int = Field(default=8, ge=0)
    material_chars: int = Field(default=120000, ge=0)
    context_preparations: int = Field(default=2, ge=1)
    context_chars: int = Field(default=180000, ge=1000)
    depth_material_reserve: float = Field(default=0.35, ge=0, le=0.5)
    breadth_material_reserve: float = Field(default=0.20, ge=0, le=0.5)
    trigger_retries: int = Field(default=1, ge=0)
    material_chunks: int = Field(default=40, ge=0)
    audit_units: int = Field(default=2, ge=0)

    technical_repairs: int = Field(default=2, ge=0)
    reachability_checks: int = Field(default=3, ge=0)
    consequence_investigations: int = Field(default=1, ge=0)
    exploration_rounds: int = Field(default=3, ge=0)
    semantic_reviews: int = Field(default=4, ge=0)
    graph_objects: int = Field(default=1000, ge=1)
    error_context_chars: int = Field(default=16000, ge=1000)


class TargetConfig(Record):
    expected_module: str | None = None
    variant: str = ""
    analysis_roots: list[str] = []
    execution_package: str = "."
    harness_path: str | None = None

    @model_validator(mode="after")
    def relative_paths(self):
        paths=self.analysis_roots+[self.execution_package]+([self.harness_path] if self.harness_path else [])
        if any(not p or p.startswith('-') or Path(p).is_absolute() or '..' in Path(p).parts for p in paths):
            raise ValueError("Target paths must stay within the relative repository namespace")
        return self


class Config(Record):
    protocol: str = "none"
    execution_backend: Literal["none", "go_module", "python"] = "none"
    target: TargetConfig = TargetConfig()
    repo_path: str | None = None
    agent_backend: str = "codex"
    agent_reasoning_effort: str | None = None
    verifier_backend: str = "tlc"
    output_language: Literal["zh-CN"] = "zh-CN"
    runs_dir: str = "runs"
    tlc_jar: str | None = None
    budget: Budget = Budget()
    parameters: dict[str, Any] = {}
    activity_focus: list[ActivityClass] = []
    directed_question: str | None = None
    fixture: str | None = None
    execution_isolation: Literal["bwrap", "workspace"] = "bwrap"
    allow_experiments: bool = True
    allow_agent_materials: bool = True



def locate_repo(explicit: str | None, configured: str | None) -> Path:
    candidate = explicit or configured
    if not candidate:raise FileNotFoundError("Supply --repo or config.repo_path explicitly")
    path = Path(candidate).expanduser().resolve()
    if not path.is_dir():raise FileNotFoundError(f"Target directory does not exist: {path}; supply --repo")
    return path
