from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import uuid4
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr



def uid() -> str:
    return uuid4().hex


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


def distinct_test_names(names):
    if len(set(names)) != len(names) or any(not name or name.strip() != name for name in names):
        raise ValueError("test_names must contain distinct, nonempty exact names")
    return names


TestNames = Annotated[list[StrictStr], Field(min_length=1), AfterValidator(distinct_test_names)]


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


class PendingAction(Record):
    logical_input: dict = {}
    id: str = Field(default_factory=uid)
    kind: str
    status: Literal["planned", "running", "completed", "outcome_unknown"] = "planned"
    input_path: str | None = None
    check_ids: list[str] = []


class CodeAnchor(Record):
    source_ids: list[str] = []
    boundary_complete: bool | None = None
    kind: Literal["declaration", "interface_member", "callsite"] = "declaration"
    material_id: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    symbol: str


class CheckRun(Record):
    experiment_id: str | None = None
    id: str = Field(default_factory=uid)
    action: str
    status: ExecutionStatus = ExecutionStatus.NOT_SCHEDULED
    outcome: Literal["holds", "tests_passed", "tests_failed", "unknown", "not_applicable"] = "unknown"
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
    snapshot_id: str
    parameters: dict[str, Any] = {}
    artifacts: list[str] = []
    pending_action_id: str | None = None

    def transition(self, status: ExecutionStatus):
        allowed = {ExecutionStatus.NOT_SCHEDULED: {ExecutionStatus.RUNNING, ExecutionStatus.TOOL_MISSING, ExecutionStatus.CANCELLED},
                   ExecutionStatus.RUNNING: set(ExecutionStatus) - {ExecutionStatus.NOT_SCHEDULED, ExecutionStatus.RUNNING}}
        if status not in allowed.get(self.status, set()):
            raise ValueError(f"Invalid execution transition: {self.status} -> {status}")
        self.status = status


class Snapshot(Record):
    id: str = Field(default_factory=uid)
    repo: str
    commit: str | None = None
    branch: str | None = None
    dirty: bool | None = None
    files: dict[str, str]
    excluded: list[str]
    created_at: str = Field(default_factory=now)
    readable_files: list[str] | None = None
    exclusion_reasons: dict[str, str] = {}
    submodules: dict[str, str] = {}


class Material(Record):
    id: str
    file: str
    start_line: int
    end_line: int
    kind: Literal["document_statement", "interface_statement", "test_expectation", "code_observation", "protocol_candidate"]
    text: str
    content_digest: str


class KnowledgeUse(Record):
    entry_id: str
    revision: int = Field(ge=1)
    assertion: str = ""


class SourceAnchor(Record):
    material_id: str
    symbol: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    anchor: CodeAnchor | None = None


class Gap(Record):
    id: str
    question: str
    experiment_id: str | None = None
    operation_id: str


class GapAnswer(Record):
    explanation: str = Field(min_length=1)
    resolved: StrictBool


class Investigation(Record):
    id: str
    version: int = 1
    question: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    hypothesis: str = ""
    discriminator: str = ""
    disposition: Literal["active", "paused", "explained", "closed"] = "active"
    parent_id: str | None = None
    knowledge: list[KnowledgeUse] = []
    resume_conditions: list[str] = []
    gaps: list[Gap] = []
    history: list[dict] = []
    operation_id: str


class KnowledgeEntry(Record):
    id: str
    revision: int = 1
    kind: Literal["behavior", "fact"]
    statement: str = Field(min_length=1)
    conditions: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    executions: dict[str, list[int]] = {}
    knowledge: list[KnowledgeUse] = []
    history: list[dict] = []
    operation_id: str


class Interpretation(Record):
    id: str
    investigation_id: str
    experiment_id: str | None = None
    source_ids: list[str] = Field(min_length=1)
    executions: dict[str, list[int]] = {}
    conclusion: Literal["explained", "conditional", "violated", "holds", "unresolved"]
    defect_claim: Literal["asserted", "refuted", "unresolved"] | None = None
    rationale: str = Field(min_length=1)
    answers: dict[str, GapAnswer] = {}
    knowledge: list[KnowledgeUse] = []
    counterevidence: list[str] = []
    limitations: list[str] = []
    joint_history: str = ""
    failure_attribution: dict | None = None
    operation_id: str


class Comparison(Record):
    field: str
    op: Literal["eq", "ne"] = "eq"
    value: str | int | bool | None = None
    reference: str | None = None


class EventRequirement(Record):
    alias: str
    event: str
    conditions: list[Comparison] = []


class EventComparison(Record):
    event: str
    identity_fields: list[str] = Field(min_length=1)
    admission_alias: str
    assertion: Comparison
    antecedent: Comparison | None = None
    applicability_conditions: list[Comparison] = []
    description: str = ""


class Harness(Record):
    kind: str
    source: str = Field(min_length=1)
    files: dict[str, str] = {}
    execution_package: str | None = None
    test_names: TestNames | None = None
    features: list[StrictStr] = []
    default_features: StrictBool = True
    all_features: StrictBool = False
    description: str = ""
    semantic_changes: list[str] = []
    prerequisites: list[EventRequirement] = []


class ExperimentBasis(Record):
    harness: Harness
    source_ids: list[str] = Field(min_length=1)
    anchors: list[SourceAnchor] = []
    scope: Scope
    prefix: str = Field(min_length=1)
    requirement: str | None = None
    responsibility: str = ""
    comparisons: list[EventComparison] = []
    knowledge: list[KnowledgeUse] = []


class FixedExperiment(Record):
    id: str
    investigation_id: str
    version: int = 1
    basis: ExperimentBasis
    snapshot_id: str
    configuration: dict
    harness_filename: str
    operation_id: str
    previous_id: str | None = None
    difference: dict = {}
    revision_reason: str = ""


class FailureAttribution(Record):
    check_id: str
    witness_indices: dict[int, list[StrictInt]]
    failure_stream: Literal["stdout", "stderr"]
    failure_lines: tuple[StrictInt, StrictInt]
    harness_lines: tuple[StrictInt, StrictInt]


class Analysis(Record):
    framework_revision: str | None = None
    id: str = Field(default_factory=uid)
    mode: Literal["real", "mock"]
    analysis_mode: Literal["autonomous", "directed", "regression"] = "autonomous"
    config: dict[str, Any]
    snapshot: Snapshot
    investigations: list[Investigation] = []
    knowledge: list[KnowledgeEntry] = []
    experiments: list[FixedExperiment] = []
    interpretations: list[Interpretation] = []
    materials: list[Material] = []
    checks: list[CheckRun] = []
    agent_session_id: str | None = None
    current_submission: dict[str, Any] = {}
    agent_turns: list[dict[str, Any]] = []
    method_paths: list[str] = []
    usage: dict[str, int] = {}
    elapsed_seconds: float = 0
    stop_reason: str = "Not started"
    run_stop: dict[str, Any] = {}
    gaps: list[str] = []
    tools: dict[str, str] = {}
    created_at: str = Field(default_factory=now)
    pending_action: PendingAction | None = None
    action_history: list[PendingAction] = []
    applied_operations: dict[str, dict[str, Any]] = {}
    invalidation: str | None = None

    def invalidate(self, reason: str):
        self.invalidation = reason
