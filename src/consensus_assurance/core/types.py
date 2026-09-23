from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator


def uid() -> str:
    return uuid4().hex


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ReadRequest(Record):
    file: str | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    symbol: str | None = Field(default=None, min_length=1, max_length=200)
    literal: str | None = Field(default=None, min_length=1, max_length=200)
    reason: str

    @model_validator(mode="after")
    def source_selector(self):
        if bool(self.symbol)+bool(self.literal)>1:raise ValueError('Select one source lookup kind')
        if self.symbol or self.literal:
            if self.start_line is not None or self.end_line is not None:raise ValueError('Lookup cannot prescribe source line numbers')
        elif not self.file or self.start_line is None or self.end_line is None:
            raise ValueError('Range read requires a file and both line numbers')
        return self

    @model_serializer(mode='wrap')
    def compact(self,handler):
        return {key:value for key,value in handler(self).items() if value is not None}


ActivityClass = Literal["A1", "A2", "A3", "A4", "A5", "A6", "A7"]
Lifecycle = Literal["establishment", "preservation", "consumption", "recovery"]


class TargetProfile(Record):
    system_boundary: str
    protocol_contexts: list[str] = []
    external_interfaces: list[str] = []
    ownership: list[str] = []
    selection_injection: list[str] = []
    variants: list[str] = []
    source_ids: list[str] = []
    unknowns: list[str] = []


class Activity(Record):
    class_id: ActivityClass
    applicability: Literal["applicable", "externalized", "not_applicable", "unknown"]
    purpose: str
    realization_summary: str
    entry_points: list[str] = []
    behavior_ids: list[str] = Field(default_factory=list, json_schema_extra={"x-controller-derived": True}, description="Derived from Behavior.primary_activity")
    variants: list[str] = []
    unknowns: list[str] = []
    source_ids: list[str] = []


class Behavior(Record):
    id: str
    primary_activity: ActivityClass
    execution_owner: str
    protocol_context: str
    trigger: str
    legal_preconditions: list[str] = []
    implementation_guards: list[str] = []
    reads: list[str] = []
    writes: list[str] = []
    durable_effects: list[str] = []
    external_effects: list[str] = []
    important_branches: list[str] = []
    async_boundaries: list[str] = []
    produces_fact_ids: list[str] = []
    consumes_fact_ids: list[str] = []
    cross_activity_effects: dict[ActivityClass, str] = Field(default_factory=dict, description="Activity ID to a concrete semantic effect description; not feeds, Behavior IDs or an inferred fact guarantee")
    existing_protections: list[str] = []
    source_ids: list[str] = Field(min_length=1)
    unknowns: list[str] = []


class Fact(Record):
    id: str
    meaning: str
    identity: dict[str, str]
    established_by: list[str] = Field(default_factory=list, json_schema_extra={"x-controller-derived": True}, description="Derived from Behavior.produces_fact_ids; never infer an unread producer")
    consumed_by: list[str] = Field(default_factory=list, json_schema_extra={"x-controller-derived": True}, description="Derived from Behavior.consumes_fact_ids")
    validity_context: str
    representation: list[str]
    invalidators: list[str] = Field(default_factory=list, description="Existing Behavior IDs only. Unread events or suspected invalidators belong in unknowns.")
    reinterpreters: list[str] = Field(default_factory=list, description="Existing Behavior IDs only, not event descriptions or Activity IDs.")
    durability: str
    recovery: str
    source_ids: list[str] = Field(min_length=1)
    unknowns: list[str] = []


class Surface(Record):
    entry_point: str
    disposition: Literal["mapped", "externalized", "infrastructure", "deferred", "UNCLASSIFIED_PROTOCOL_RESPONSIBILITY"]
    behavior_ids: list[str] = []
    reason: str
    source_ids: list[str] = []
    high_consequence: bool = False


class ConsensusAuditSpec(Record):
    version: int = 1
    target_profile: TargetProfile
    activities: list[Activity] = Field(min_length=7, max_length=7)
    behaviors: list[Behavior] = []
    facts: list[Fact] = []
    surfaces: list[Surface] = []

    @model_validator(mode="before")
    @classmethod
    def derive_indexes(cls, value):
        if not isinstance(value, dict):return value
        import copy
        value=copy.deepcopy(value)
        behaviors=value.get('behaviors',[])
        get=lambda x,k,default=None:x.get(k,default) if isinstance(x,dict) else getattr(x,k,default)
        def derived(collection,fields):
            for i,obj in enumerate(value.get(collection,[])):
                additions={key:build(obj) for key,build in fields.items() if key not in (obj if isinstance(obj,dict) else obj.model_fields_set)}
                if isinstance(obj,dict):obj.update(additions)
                elif additions:value[collection][i]=obj.model_copy(update=additions)
        derived('activities',{'behavior_ids':lambda a:[get(b,'id') for b in behaviors if get(b,'primary_activity')==get(a,'class_id')]})
        derived('facts',{key:(lambda f,edge=edge:[get(b,'id') for b in behaviors if get(f,'id') in get(b,edge,[])]) for key,edge in [('established_by','produces_fact_ids'),('consumed_by','consumes_fact_ids')]})
        return value

    @model_validator(mode="after")
    def seven_coordinates(self):
        if {a.class_id for a in self.activities} != {"A1", "A2", "A3", "A4", "A5", "A6", "A7"}:
            raise ValueError("Specify each of the seven activity classes exactly once")
        return self


class AuditQuestion(Record):
    disposition: Literal["explained_by_existing_mechanism", "concrete_suspicion", "needs_specific_evidence", "ready_for_check"] | None = None
    preferred_check: Literal["source_review", "direct_test", "controlled_schedule", "local_model"] | None = None
    requests: list[ReadRequest] = []
    question: str
    importance: str
    source_ids: list[str] = []
    participants: list[str] = []
    objects: list[str] = []
    contexts: list[str] = []
    event_paths: list[str] = []
    activity_classes: list[ActivityClass] = []
    behavior_ids: list[str] = []
    fact_ids: list[str] = []
    obligation_relation_kind: Lifecycle | None = None
    counterevidence: list[str] = []
    unknowns: list[str] = []
    priority: int = Field(default=0, ge=0, le=3, description="System consequence and audit significance, justified in importance; not proof")
    trigger_rationale: str


class QuestionCandidate(Record):
    """Controller continuation; semantic content lives only in AuditQuestion."""
    id: str = Field(default_factory=uid)
    question: AuditQuestion
    history: list[AuditQuestion] = []
    check_ids: list[str] = []
    status: Literal["active", "explained", "escalated", "blocked", "paused"] = "active"
    parent_candidate_id: str | None = None
    fork_reason: str = ""
    stage: Literal["read", "analyze"] = "analyze"
    read_plan_id: str | None = None
    material_ids: list[str] = []
    spec_task_ids: list[str] = []
    stagnation: int = 0
    stop_reason: str = ""
    resume_conditions: list[str] = []
    obligation_id: str | None = None


class ReachabilityRequirement(Record):
    sequence: list[str] = []
    identity_operator: str | None = None
    id: str
    operator: str
    claim_ids: list[str] = Field(min_length=1)
    behavior_ids: list[str] = []
    fact_ids: list[str] = []
    description: str


class ReachabilityResult(Record):
    model_id: str
    requirement_id: str
    check_id: str
    status: Literal["reachable", "unreachable", "unknown"]
    search_fingerprint: str
    reason: str


class InquiryTask(Record):
    surface_entry_points: list[str] = []
    candidate_id: str | None = None
    draft_path: str | None = None
    diagnostics: list[dict] = []
    admitted: bool = False
    preparation_failures: int = 0
    semantic_failures: int = 0
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
    kind: Literal["spec_refine", "review"]
    reason: str
    trigger: str
    activity_classes: list[ActivityClass] = []
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
    target_id: str
    aspect: Literal["applicability", "decomposition", "checker_correspondence"]
    status: Literal["no_issue_found", "needs_reading", "disputed", "revision_needed"]
    source_ids: list[str] = Field(min_length=1)
    rationale: str
    counterevidence: list[str] = []
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
    source_ids: list[str] = Field(default_factory=list, description="Exact IDs of acquired implementation source materials; not Behavior or Binding IDs")
    expectation_ids: list[str] = Field(default_factory=list, description="Exact IDs of acquired materials supporting the expectation; not invented expectation labels. Explain normative applicability in derivation.")
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
    kind: Literal["obligation", "assumption"]
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



class AssociatedCode(Record):
    associations: list[BindingAssociation] = Field(min_length=1)
    anchor: CodeAnchor | None = None


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
    binding_ids: list[str] = []
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


class DirectCheckArtifact(Record):
    id: str = Field(default_factory=uid)
    version: int = 1
    plan_path: str
    harness_path: str
    snapshot_id: str
    unit_id: str
    claim_id: str
    binding_ids: list[str]
    graph_versions: dict[str, int]
    origin: Origin
    scope: Scope
    operation_id: str
    previous_id: str | None = None


class CheckRun(Record):
    direct_check_id: str | None = None
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
    direct_check_id: str | None = None
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
    direct_check_id: str | None = None
    id: str = Field(default_factory=uid)
    claim_id: str
    model_id: str | None = None
    check_id: str
    stage: Investigation = Investigation.MODEL_ONLY
    origin: Origin
    description: str
    trace_path: str
    investigation_notes: list[str] = []
    replay_check_id: str | None = None
    level: Literal["model_candidate", "implementation_candidate", "implementation_obligation", "implementation_consequence"] = "model_candidate"
    checker_id: str | None = None
    claim_version: int | None = None
    confirmation_path: str | None = None
    applicability: Literal["current", "historical_scope", "recheck_required"] = "current"


    @model_validator(mode="after")
    def route_provenance(self):
        if bool(self.model_id) == bool(self.direct_check_id):
            raise ValueError("Finding needs exactly one model or direct-check provenance")
        return self


class Relation(Record):
    id: str = Field(default_factory=uid)
    source: str
    target: str
    kind: Literal["depends_all", "supports", "challenges", "revises", "conditional_on", "boundary"]
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
    obligation_ids: list[str]
    binding_ids: list[str]
    relation_ids: list[str]
    scope: Scope
    rationale: str
    status: Literal["pending", "selected", "checked", "partial", "blocked", "revised"] = "pending"
    previous_id: str | None = None
    version: int = 1
    boundary_changes: list[str] = []
    obligation_checks: dict[str, list[str]] = {}
    remaining_obligation_ids: list[str] = []
    recheck_reasons: list[str] = []
    semantic_readiness: dict[str, Any] = {}
    audit_question: AuditQuestion | None = None
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
    kind: Literal["F1", "F2", "F3", "F4", "encoding"]
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
    question_candidates: list[QuestionCandidate] = []
    direct_checks: list[DirectCheckArtifact] = []
    active_direct_check_id: str | None = None
    question_continuations: dict[str, dict] = {}
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
    derivation_path: str | None = None
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
    audit_spec_path: str | None = None
    audit_spec_version: int = 0
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
        if evidence.direct_check_id != check.direct_check_id:
            raise ValueError("Evidence direct-check association mismatch")
        if evidence.direct_check_id and not any(d.id == evidence.direct_check_id and d.snapshot_id == evidence.snapshot_id for d in self.direct_checks):
            raise ValueError("Evidence direct-check artifact is missing")
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
