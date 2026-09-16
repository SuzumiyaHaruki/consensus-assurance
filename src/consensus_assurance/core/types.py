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


class ReadRequest(Record):
    file: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    reason: str


class CoveragePoint(Record):
    sequence_required: bool = False
    id: str
    phase: Literal["establish", "maintain", "use", "handoff", "recover", "other"]
    source_ids: list[str] = Field(min_length=1)
    binding_ids: list[str] = []
    claim_ids: list[str] = []
    question: str
    unknowns: list[str] = []


class AuditQuestion(Record):
    question: str
    importance: str
    source_ids: list[str] = Field(min_length=1)
    participants: list[str] = []
    objects: list[str] = []
    contexts: list[str] = []
    event_paths: list[str] = []
    points: list[CoveragePoint] = []
    trigger_rationale: str


class ReachabilityRequirement(Record):
    sequence: list[str] = []
    identity_operator: str | None = None
    id: str
    operator: str
    claim_ids: list[str] = Field(min_length=1)
    point_ids: list[str] = []
    description: str


class ReachabilityResult(Record):
    model_id: str
    requirement_id: str
    check_id: str
    status: Literal["reachable", "unreachable", "unknown"]
    search_fingerprint: str
    reason: str


class ResponsibilityHandoff(Record):
    covered_by_unit_ids: list[str] = []
    no_separate_check_reason: str = ""
    target_id: str
    source_ids: list[str] = Field(min_length=1)
    description: str


class Responsibility(Record):
    id: str
    description: str
    source_ids: list[str] = Field(min_length=1)
    entry_points: list[str] = []
    claim_ids: list[str] = []
    handoffs: list[ResponsibilityHandoff] = []
    questions: list[str] = []
    applicability: str
    version: int = 1


class InquiryTask(Record):
    admitted: bool = False
    preparation_failures: int = 0
    parent_task_id: str | None = None
    child_task_ids: list[str] = []
    requested_aspects: dict[str, list[str]] = {}
    expected_contribution: str = ""
    context_receipt_id: str | None = None
    context_dependencies: dict = {}
    read_plan_id: str | None = None
    repair_session: dict | None = None
    resolution_issue_ids: list[str] = []
    id: str = Field(default_factory=uid)
    kind: Literal["explore", "review"]
    reason: str
    trigger: str
    responsibility_ids: list[str] = []
    target_ids: list[str] = []
    target_versions: dict[str, int] = {}
    unit_id: str | None = None
    model_id: str | None = None
    requests: list[ReadRequest] = []
    status: Literal["pending", "running", "completed", "blocked"] = "pending"
    stage: Literal["read", "analyze", "done"] = "read"
    added_material_ids: list[str] = []
    stop_reason: str = ""
    check_id: str | None = None
    unit_version: int | None = None
    material_ids: list[str] = []
    superseded_by: str | None = None


class SemanticCheck(Record):
    scope_limitations: list[str] = Field(default_factory=list, description="Independent scope boundaries, not unresolved conditions needed for this judgment; never relabel contrary evidence here")
    target_id: str
    aspect: Literal["applicability", "decomposition", "checker_correspondence"]
    status: Literal["no_issue_found", "needs_reading", "disputed", "revision_needed"]
    source_ids: list[str] = Field(min_length=1)
    explanation: str
    alternatives: str
    counterexample_reasoning: str
    limitations: list[str] = []


class SemanticReview(Record):
    context_receipt_id: str | None = None
    context_dependencies: dict = {}
    id: str = Field(default_factory=uid)
    task_id: str
    check_id: str
    model_id: str | None = None
    target_versions: dict[str, int]
    material_ids: list[str]
    items: list[SemanticCheck]
    revision_id: str | None = None
    origin: Literal["agent", "mock"]
    unit_id: str | None = None
    unit_version: int | None = None
    supersedes_task_ids: list[str] = []
    resolves_issue_ids: list[str] = []
    resolution_rationale: str = ""


class ReviewIssue(Record):
    conditions: list[dict[str, Any]] = []
    resolution_basis: dict = {}
    prior_review_ids: list[str] = []
    parent_issue_id: str | None = None
    needs_recheck: bool = False
    id: str = Field(default_factory=uid)
    review_id: str
    target_id: str
    target_version: int
    aspect: str
    model_id: str | None = None
    source_ids: list[str]
    explanation: str
    disposition: Literal["reading", "revision", "investigation", "blocked"]
    reason: str
    task_ids: list[str] = []
    resolved_by: str | None = None
    resolution_model_id: str | None = None
    resolution_checks: list[str] = []


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


class Grounding(Record):
    behavior_ids: list[str] = []
    expectation_ids: list[str] = []
    binding_ids: list[str] = []
    derivation: str = ""
    applicability: str = ""
    unresolved: list[str] = []
    conflicts: list[str] = []
    alternatives: list[str] = []


class CheckerSpec(Record):
    invariant: str
    claim_id: str
    scope: Scope


class CheckerResult(Record):
    invariant: str
    claim_id: str
    scope: Scope
    outcome: Literal["holds", "violated", "unknown"] = "unknown"
    reason: str = "Not independently completed"


class PendingAction(Record):
    inquiry_id: str | None = None
    logical_input: dict = {}
    id: str = Field(default_factory=uid)
    kind: str
    unit_id: str | None = None
    model_id: str | None = None
    finding_id: str | None = None
    status: Literal["planned", "running", "completed", "outcome_unknown"] = "planned"
    input_path: str | None = None
    check_ids: list[str] = []



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
    grounding: Grounding = Grounding()
    version: int = 1


class CodeAnchor(Record):
    source_ids: list[str] = []
    boundary_complete: bool | None = None
    kind: Literal["declaration", "interface_member", "callsite"] = "declaration"
    material_id: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    symbol: str


class BindingAssociation(Record):
    claim_id: str
    source_ids: list[str]
    rationale: str


class CodeUse(Record):
    binding_id: str
    role: Literal["direct", "input", "support", "environment", "handoff"]
    claim_ids: list[str] = Field(min_length=1)
    relation_ids: list[str] = []
    source_ids: list[str] = Field(min_length=1)
    rationale: str
    unverified: list[str] = []


class AssociatedCode(Record):
    associations: list[BindingAssociation] = Field(min_length=1)
    anchor: CodeAnchor | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_single_claim(cls,value):
        if isinstance(value,dict) and "claim_id" in value:
            value=dict(value);legacy=value.pop("claim_id")
            imported=[{"claim_id":legacy,"source_ids":[value["material_id"]] if value.get("material_id") else [],"rationale":"Imported single-claim mapping; applicability still requires review"}]
            if "associations" in value and [a.get("claim_id") if isinstance(a,dict) else a.claim_id for a in value["associations"]]!=[legacy]:
                raise ValueError("Legacy and current binding associations conflict")
            value.setdefault("associations",imported)
        return value

    @property
    def claim_id(self):
        # Read-only compatibility for historical single-claim consumers.
        if len(self.associations)!=1:raise ValueError("Binding has multiple associations; use associations")
        return self.associations[0].claim_id


class Binding(AssociatedCode):
    material_id: str | None = None
    id: str
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
    version: int = 1

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
    stage: Literal["model_only", "complete"] = "complete"
    pending_components: list[str] = []
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
    checkers: list[CheckerSpec] = []
    graph_versions: dict[str, int] = {}
    reachability_requirements: list[ReachabilityRequirement] = []
    search_inputs: dict[str, Any] = {}
    search_fingerprint: str = ""


class CheckRun(Record):
    id: str = Field(default_factory=uid)
    action: str
    status: ExecutionStatus = ExecutionStatus.NOT_SCHEDULED
    outcome: Literal["holds", "counterexample", "deadlock", "tests_passed", "tests_failed", "unknown", "not_applicable"] = "unknown"
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
    violated_invariant: str | None = None
    checker_results: list[CheckerResult] = []
    pending_action_id: str | None = None
    search_fingerprint: str = ""
    reused_from: str | None = None

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
    search_fingerprint: str = ""
    checker_id: str | None = None
    claim_version: int | None = None
    applicability: Literal["current", "historical_scope", "recheck_required"] = "current"


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
    checker_id: str | None = None
    claim_version: int | None = None
    confirmation_path: str | None = None
    applicability: Literal["current", "historical_scope", "recheck_required"] = "current"


class Relation(Record):
    id: str = Field(default_factory=uid)
    source: str
    target: str
    kind: Literal["depends_all", "alternative", "supports", "challenges", "maps", "revises", "conditional_on", "boundary"]
    group: str | None = None
    confirmed: bool = False
    rationale: str
    pending: list[str] = []
    grounding: Grounding = Grounding()
    version: int = 1


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
    status: Literal["pending", "selected", "checked", "partial", "blocked", "revised"] = "pending"
    previous_id: str | None = None
    version: int = 1
    boundary_changes: list[str] = []
    obligation_checks: dict[str, list[str]] = {}
    remaining_obligation_ids: list[str] = []
    recheck_reasons: list[str] = []
    semantic_readiness: dict[str, Any] = {}
    audit_question: AuditQuestion | None = None
    code_uses: list[CodeUse] = []
    coverage_intent: list[CoveragePoint] = []
    coverage_limitations: list[str] = []


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
    applicability: Literal["current", "historical_scope", "recheck_required"] = "current"


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
    scope_updates: dict[str, dict] = {}
    milestones: dict[str, str] = {}
    review_reuses: list[dict] = []
    read_plans: dict[str, dict] = {}
    material_allocations: list[dict] = []
    task_attachments: dict[str, list[str]] = {}
    packet_receipts: list[dict] = []
    file_index: dict[str, dict] = {}
    trigger_retry_tasks: list[dict] = []
    framework_revision: str | None = None
    framework_stage: str = "new_run"
    repair_sessions: dict[str, dict] = {}
    attached_material_ids: list[str] = []
    schema_version: str = "2"
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
    pending_output_repair: dict | None = None
    graph_version: int = 0
    graph_history: list[dict] = []
    reading_history: list[dict] = []
    unread_ranges: dict[str, list[list[int]]] = {}
    guidance: list[dict] = []
    active_unit_id: str | None = None
    active_model_id: str | None = None
    active_finding_id: str | None = None
    next_action: str = "select"
    pending_action: PendingAction | None = None
    action_history: list[PendingAction] = []
    targeted_gap: dict | None = None
    monitor_results: list[dict] = []
    responsibilities: list[Responsibility] = []
    responsibility_history: list[dict] = []
    inquiry_tasks: list[InquiryTask] = []
    semantic_reviews: list[SemanticReview] = []
    review_issues: list[ReviewIssue] = []
    reachability_results: list[ReachabilityResult] = []
    consequences: list[dict[str, Any]] = []
    applied_operations: dict[str, dict[str, Any]] = {}
    active_inquiry_id: str | None = None
    inquiry_selections: list[dict] = []
    last_work_kind: str = "local"
    deferred_units: dict[str, dict] = {}




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


    def affect(self, model_ids, reason, historical=False):
        model_ids = set(model_ids)
        for item in [*self.evidence, *self.calibrations, *self.findings]:
            if item.model_id not in model_ids:
                continue
            item.applicability = "historical_scope" if historical else "recheck_required"
            if not historical:
                if isinstance(item, Evidence):
                    item.assessment = Assessment.STALE
                    item.stale_reason = reason
                elif isinstance(item, Calibration):
                    item.status = "stale"
        if not historical:
            affected_units = {m.unit_id for m in self.models if m.id in model_ids}
            for unit in self.units:
                if unit.id in affected_units:
                    if reason not in unit.recheck_reasons:
                        unit.recheck_reasons.append(reason)
                    unit.obligation_checks = {}
                    unit.remaining_obligation_ids = list(unit.obligation_ids)
                    if unit.status in {"checked", "partial", "blocked"}:
                        unit.status = "pending"
        # Executions and their original outcomes never change.
