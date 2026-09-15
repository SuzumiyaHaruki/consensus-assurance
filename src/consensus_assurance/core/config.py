from pathlib import Path
from typing import Any, Literal
from pydantic import Field
from .types import Record


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

    targeted_reads: int = Field(default=3, ge=0)
    technical_repairs: int = Field(default=2, ge=0)
    reachability_checks: int = Field(default=3, ge=0)
    consequence_investigations: int = Field(default=1, ge=0)
    exploration_rounds: int = Field(default=3, ge=0)
    semantic_reviews: int = Field(default=4, ge=0)
    graph_objects: int = Field(default=1000, ge=1)
    outer_reserve_seconds: float = Field(default=60, ge=0)
    error_context_chars: int = Field(default=16000, ge=1000)


class Config(Record):
    protocol: str = "none"
    implementation: str = "hashicorp_raft"
    repo_path: str | None = None
    agent_backend: str = "codex"
    verifier_backend: str = "tlc"
    output_language: Literal["zh-CN"] = "zh-CN"
    runs_dir: str = "runs"
    tlc_jar: str | None = None
    budget: Budget = Budget()
    parameters: dict[str, Any] = {}
    directed_question: str | None = None
    fixture: str | None = None
    execution_isolation: Literal["bwrap", "workspace"] = "bwrap"
    allow_experiments: bool = True
    allow_agent_materials: bool = True



def locate_repo(explicit: str | None, configured: str | None) -> Path:
    candidate = explicit or configured
    if candidate:
        path = Path(candidate).expanduser().resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"Target directory does not exist: {path}; supply --repo")
        return path
    desktops = [Path.home() / "Desktop"]
    xdg = Path.home() / ".config/user-dirs.dirs"
    if xdg.is_file():
        import re
        match = re.search(r'^XDG_DESKTOP_DIR="([^"\n]+)"', xdg.read_text(), re.M)
        if match:
            value = match[1].replace("$HOME", str(Path.home()))
            if "$" not in value:
                desktops.append(Path(value))
    for desktop in desktops:
        if (desktop / "hashicorp-raft").is_dir():
            return (desktop / "hashicorp-raft").resolve()
    raise FileNotFoundError("Target not found on discovered desktops; supply --repo")
