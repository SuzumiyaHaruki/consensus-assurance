from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, model_validator


def uid() -> str:
    return uuid4().hex


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ExecutionStatus(str, Enum):
    NOT_SCHEDULED = "not_scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    TIMEOUT = "timeout"
    TOOL_MISSING = "tool_missing"
    LOGIN_REQUIRED = "login_required"
    QUOTA_EXHAUSTED = "quota_exhausted"
    CANCELLED = "cancelled"


class Assessment(str, Enum):
    UNASSESSED = "unassessed"
    SUPPORTED = "supported_in_scope"
    CHALLENGED = "challenged"
    INCONCLUSIVE = "inconclusive"
    STALE = "stale"


class Investigation(str, Enum):
    MODEL_ONLY = "model_only"
    REACHABILITY_PENDING = "reachability_pending"
    REPRODUCED = "implementation_reproduced"
    SPURIOUS = "confirmed_abstraction_artifact"
    INCONCLUSIVE = "replay_inconclusive"


class Origin(str, Enum):
    EXECUTED = "executed"
    MOCK = "mock"
    PRESET = "preset"
    AGENT = "agent_generated"
    SYNTHETIC = "synthetic_trace"
    IMPORTED = "imported"
    MUTATION = "isolated_mutation"


class Scope(Record):
    description: str
    assumptions: list[str] = []
    excluded: list[str] = []
    parameters: dict[str, Any] = {}


class Claim(Record):
    id: str
    kind: Literal["goal", "obligation", "assumption"]
    description: str
    scope: Scope
    source: str
    source_ids: list[str] = []
    pending: list[str] = []
    assessment: Assessment = Assessment.UNASSESSED
    candidate: bool = True


class Binding(Record):
    id: str
    claim_id: str
    file: str
    symbol: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    snapshot_id: str
    content_digest: str
    basis: Literal["code_observation", "document_statement", "model_assumption", "agent_inference"]
    description: str
    pending: list[str] = []
    excerpt: str

    @model_validator(mode="after")
    def ordered_range(self):
        if self.end_line < self.start_line:
            raise ValueError("Invalid code range")
        return self


class ConstraintSource(Record):
    constraint: str
    source_kind: Literal["code_observation", "document_statement", "model_assumption", "agent_inference"]
    source_ids: list[str]
    justification: str


class ModelArtifact(Record):
    id: str = Field(default_factory=uid)
    version: int = Field(ge=1)
    kind: Literal["reference", "implementation_abstraction"]
    origin: Origin
    claim_id: str
    snapshot_id: str
    path: str
    config_path: str
    content_digest: str
    config_digest: str
    scope: Scope
    initial_state: str
    variables: list[str]
    actions: list[str]
    properties: list[str]
    constraints: list[ConstraintSource]
    binding_ids: list[str]
    extension_schema: dict[str, Any]
    extension_version: str
    revision_reason: str = "Initial model"
    previous_id: str | None = None
    unit_id: str = ""
    checker_path: str = ""
    mapping_path: str = ""
    harness_path: str = ""
    bundle_path: str = ""
    artifact_digests: dict[str, str] = {}


class CheckRun(Record):
    id: str = Field(default_factory=uid)
    action: str
    status: ExecutionStatus = ExecutionStatus.NOT_SCHEDULED
    outcome: Literal["holds", "counterexample", "tests_passed", "tests_failed", "unknown", "not_applicable"] = "unknown"
    origin: Origin = Origin.EXECUTED
    command: list[str] = []
    cwd: str
    started_at: str | None = None
    ended_at: str | None = None
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    reason: str = ""
    tool_version: str = "unknown"
    model_id: str | None = None
    snapshot_id: str
    parameters: dict[str, Any] = {}
    artifacts: list[str] = []
    input_versions: dict[str, str] = {}
    reused: bool = False
    search_statistics: dict[str, str] = {}

    def transition(self, status: ExecutionStatus):
        allowed = {ExecutionStatus.NOT_SCHEDULED: {ExecutionStatus.RUNNING, ExecutionStatus.TOOL_MISSING, ExecutionStatus.CANCELLED},
                   ExecutionStatus.RUNNING: set(ExecutionStatus) - {ExecutionStatus.NOT_SCHEDULED, ExecutionStatus.RUNNING}}
        if status not in allowed.get(self.status, set()):
            raise ValueError(f"Invalid execution transition: {self.status} -> {status}")
        self.status = status


class Evidence(Record):
    id: str = Field(default_factory=uid)
    check_id: str
    model_id: str | None
    snapshot_id: str
    claim_id: str | None
    origin: Origin
    level: Literal["model", "implementation_test", "framework_test", "trace_calibration"]
    scope: Scope
    description: str
    assessment: Assessment
    stale_reason: str | None = None
    calibration_id: str | None = None


class Finding(Record):
    id: str = Field(default_factory=uid)
    claim_id: str
    model_id: str
    check_id: str
    stage: Investigation = Investigation.MODEL_ONLY
    origin: Origin
    description: str
    trace_path: str
    investigation_notes: list[str] = []
    replay_check_id: str | None = None
    level: Literal["model_candidate", "implementation_obligation", "implementation_goal"] = "model_candidate"


class Relation(Record):
    id: str = Field(default_factory=uid)
    source: str
    target: str
    kind: Literal["depends_all", "alternative", "supports", "challenges", "maps", "revises", "conditional_on", "boundary"]
    group: str | None = None
    confirmed: bool = False
    rationale: str
    pending: list[str] = []


class Snapshot(Record):
    id: str = Field(default_factory=uid)
    repo: str
    commit: str | None = None
    branch: str | None = None
    dirty: bool | None = None
    files: dict[str, str]
    excluded: list[str]
    created_at: str = Field(default_factory=now)


class Material(Record):
    id: str
    file: str
    start_line: int
    end_line: int
    kind: Literal["document_statement", "interface_statement", "test_expectation", "code_observation", "protocol_candidate"]
    text: str
    content_digest: str


class AuditUnit(Record):
    id: str
    goal_ids: list[str]
    obligation_ids: list[str]
    binding_ids: list[str]
    relation_ids: list[str]
    scope: Scope
    rationale: str
    goal_observable: bool = False
    status: Literal["pending", "selected", "checked", "blocked", "revised"] = "pending"
    previous_id: str | None = None


class Calibration(Record):
    id: str = Field(default_factory=uid)
    model_id: str
    experiment_check_id: str
    check_ids: list[str] = []
    mapping_path: str
    trace_path: str
    status: Literal["not_scheduled", "compatible", "incompatible", "inconclusive", "stale"] = "not_scheduled"
    reason: str
    origin: Origin
    scope: str = "Finite observed traces only; no equivalence proof"


class Revision(Record):
    id: str = Field(default_factory=uid)
    kind: Literal["F1", "F2", "F3", "F4"]
    rationale: str
    evidence_ids: list[str]
    target_ids: list[str]
    relation_ids: list[str] = []
    before: dict
    after: dict
    return_step: Literal["understand", "build", "select", "experiment"]
    status: Literal["applied", "unresolved"] = "applied"


class Capability(Record):
    name: str
    status: Literal["observed_in_code", "probe_confirmed", "unavailable"]
    check_id: str | None
    description: str


class Analysis(Record):
    schema_version: str = "1"
    id: str = Field(default_factory=uid)
    mode: Literal["real", "mock"]
    analysis_mode: Literal["autonomous", "directed", "regression"] = "autonomous"
    config: dict[str, Any]
    snapshot: Snapshot
    claims: list[Claim] = []
    bindings: list[Binding] = []
    models: list[ModelArtifact] = []
    checks: list[CheckRun] = []
    evidence: list[Evidence] = []
    findings: list[Finding] = []
    relations: list[Relation] = []
    completed_steps: list[str] = []
    usage: dict[str, int] = {}
    elapsed_seconds: float = 0
    stop_reason: str = "Not started"
    gaps: list[str] = []
    tools: dict[str, str] = {}
    materials: list[Material] = []
    unexplored: list[str] = []
    units: list[AuditUnit] = []
    calibrations: list[Calibration] = []
    revisions: list[Revision] = []
    capabilities: list[Capability] = []
    selections: list[dict] = []
    discovery_path: str | None = None
    created_at: str = Field(default_factory=now)
    first_model_seconds: float | None = None
    parent_run: str | None = None
    pending_feedback: dict | None = None
    graph_version: int = 0


    def add_evidence(self, evidence: Evidence):
        check = next((c for c in self.checks if c.id == evidence.check_id), None)
        if check is None or check.status != ExecutionStatus.COMPLETED:
            raise ValueError("Evidence requires a completed execution")
        if evidence.snapshot_id != check.snapshot_id or evidence.model_id != check.model_id:
            raise ValueError("Evidence input association mismatch")
        if evidence.origin != check.origin:
            raise ValueError("Evidence origin mismatch")
        if evidence.calibration_id and not any(c.id == evidence.calibration_id and c.model_id == evidence.model_id for c in self.calibrations):
            raise ValueError("Evidence calibration association mismatch")
        if evidence.model_id and not any(m.id == evidence.model_id and m.snapshot_id == evidence.snapshot_id for m in self.models):
            raise ValueError("Evidence model is missing")
        if (evidence.origin == Origin.MOCK or self.mode == "mock") and (evidence.level != "framework_test" or evidence.assessment == Assessment.SUPPORTED):
            raise ValueError("Mock output cannot support correctness")
        self.evidence.append(evidence)

    def invalidate(self, reason: str):
        for calibration in self.calibrations:
            calibration.status = "stale"
        for e in self.evidence:
            e.assessment = Assessment.STALE
            e.stale_reason = reason
        for c in self.claims:
            if c.assessment != Assessment.UNASSESSED:
                c.assessment = Assessment.STALE
