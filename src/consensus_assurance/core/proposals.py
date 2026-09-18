from typing import Literal
from pydantic import Field, model_validator
from .types import AssociatedCode, Record, Scope, ConstraintSource, Grounding, CheckerSpec, ReadRequest, ConsensusAuditSpec, SemanticCheck, AuditQuestion, ReachabilityRequirement


class ClaimDraft(Record):
    id: str
    kind: Literal["obligation", "assumption"]
    description: str
    source_ids: list[str] = Field(min_length=1, description="Located materials; file kinds do not establish normative authority")
    scope: Scope
    pending: list[str]
    grounding: Grounding = Grounding()


class BindingDraft(AssociatedCode):
    id: str
    material_id: str
    symbol: str = Field(description="Source symbol tied to a verified declaration, interface member or explicitly declared call-site anchor. The behavior range may be a narrow internal snippet. Do not substitute arbitrary words from the excerpt.")
    start_line: int
    end_line: int
    description: str
    pending: list[str]


class RelationDraft(Record):
    id: str
    source: str
    target: str
    kind: Literal["depends_all", "conditional_on", "boundary"]
    group: str | None
    rationale: str
    pending: list[str]
    grounding: Grounding = Grounding()


class UnitDraft(Record):
    audit_question: AuditQuestion | None = None
    id: str
    obligation_ids: list[str] = Field(min_length=1, max_length=1)
    binding_ids: list[str] = Field(min_length=1)
    relation_ids: list[str] = Field(default_factory=list)
    scope: Scope
    rationale: str


class GraphDraft(Record):
    """Unbounded aggregate shape; batch limits belong to agent proposals."""
    claims: list[ClaimDraft] = []
    bindings: list[BindingDraft] = []
    relations: list[RelationDraft] = []
    units: list[UnitDraft] = []
    conflicts: list[str] = []
    unexplored: list[str] = []
    gaps: list[str] = []


class Discovery(Record):
    understanding: str
    audit_spec: ConsensusAuditSpec
    reading_requests: list[ReadRequest] = Field(default_factory=list, max_length=8)


class DescriptiveIssue(Record):
    object_ids: list[str] = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    reason: str


class Derivation(Record):
    obligation: ClaimDraft | None = None
    bindings: list[BindingDraft] = []
    dependencies: list[RelationDraft] = []
    context_claims: list[ClaimDraft] = []
    audit_question: AuditQuestion
    selection_rationale: str
    reading_requests: list[ReadRequest] = Field(default_factory=list, max_length=8)
    descriptive_issues: list[DescriptiveIssue] = []


class FieldProjection(Record):
    model_field: str
    raw_field: str
    source: Literal["state", "event", "metadata"] = "state"


class ObservationMap(Record):
    fields: list[FieldProjection] = Field(description="Model Obs record field to raw state field mapping; direct scalar projection only")
    required_events: list[str] = Field(description="Event names that must be present for calibration to be conclusive")
    max_internal_steps: int = Field(default=3, ge=0, le=20)
    allow_observed_stutter: bool = True
    description: str


class Comparison(Record):
    field: str
    op: Literal["eq", "ne"] = "eq"
    value: str | int | bool | None = None
    reference: str | None = None


class EventRequirement(Record):
    alias: str
    event: str
    conditions: list[Comparison] = []


class ObservableProperty(Record):
    checker_id: str
    kind: Literal["event_assertion", "stable_support"] = "event_assertion"
    trigger: Comparison
    assertion: Comparison
    identity_fields: list[str] = []
    history_field: str | None = None
    description: str


class ObservationChange(Record):
    change_index: int = Field(ge=0)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    binding_ids: list[str] = Field(min_length=1)
    rationale: str


class EventMonitor(Record):
    id: str
    checker_id: str
    event: str
    identity_fields: list[str]
    conditions: list[Comparison] = []
    assertion: Comparison
    binding_ids: list[str]
    grounding: Grounding
    applicability_conditions: list[Comparison] = []
    property: ObservableProperty | None = None




class Harness(Record):
    kind: str = Field(description="Harness kind advertised by the selected implementation adapter")
    source: str = Field(min_length=1, description="Executable experiment source, calling actual target code; no fabricated expected observations")
    description: str
    prerequisite_events: list[str] = Field(description="Ordered events required for candidate replay; not claims that they occurred")
    semantic_changes: list[str] = Field(description="Instrumentation and adaptation differences; never alter protocol logic to create a real finding")
    prerequisites: list[EventRequirement] = []
    legality: Grounding = Grounding()
    legal_conditions: list[Comparison] = []
    observation_changes: list[ObservationChange] = []



class ConsequenceWitnessEvent(Record):
    participant: str
    event: str


class ConsequenceObservation(Record):
    identity_fields: list[str] = []
    witness_events: list[ConsequenceWitnessEvent] = []
    claim_id: str
    required_participants: list[str] = Field(min_length=1)
    required_events: list[str] = Field(min_length=1)
    binding_ids: list[str] = Field(min_length=1)
    grounding: Grounding


class ContextScenario(Record):
    description: str = Field(min_length=1,description="Implementation-grounded context dimensions, support lifecycle and interruption boundaries; identify unknowns")
    mode: Literal['local','cross_context']
    binding_ids: list[str] = Field(min_length=1)
    variables: list[str]
    actions: list[str]
    checker_ids: list[str]
    reachability_ids: list[str]
    excluded: list[str] = Field(description="Dimensions or histories not modeled, with implementation-specific reasons; not a guard")


class ModelCore(Record):
    context_analysis: list[ContextScenario] = []
    reachability: list[ReachabilityRequirement] = []
    consequence_observations: list[ConsequenceObservation] = []
    description: str
    behavior: str = Field(min_length=1, description="TLA+ MODULE Behavior, with Init, Next, vars, and Obs; implementation behavior only")
    properties: str = Field(min_length=1, description="TLA+ MODULE Properties EXTENDS Behavior, defining obligation and separately scoped consequence invariants")
    constants: str = Field(description="TLC constant assignments only; no state/action constraints or invariant overrides")
    invariants: list[str] = []
    checked_claim_ids: list[str] = []
    initial_state: str
    variables: list[str]
    actions: list[str]
    constraints: list[ConstraintSource]
    scope: Scope
    uncertainties: list[str]
    checkers: list[CheckerSpec] = []
    monitors: list[EventMonitor] = []
    observable_properties: list[ObservableProperty] = []

    def checker_specs(self):
        if self.checkers:
            if len({c.invariant for c in self.checkers}) != len(self.checkers):
                raise ValueError("Duplicate invariant mapping")
            return self.checkers
        if len(self.checked_claim_ids) == 1 and self.invariants:
            return [CheckerSpec(invariant=i, claim_id=self.checked_claim_ids[0], scope=self.scope) for i in self.invariants]
        raise ValueError("Explicit invariant-to-claim mappings are required; list positions are not a mapping")


class Bundle(ModelCore):
    observation: ObservationMap
    harness: Harness


class ComponentWork(Record):
    component: Literal['behavior', 'properties', 'harness', 'observation']
    reason: str = Field(min_length=1, description="The missing evidence or executable component, not an assumed guarantee")
    requests: list[ReadRequest] = []


class ModelDraft(ModelCore):
    pending_work: list[ComponentWork] = Field(min_length=1, description="Explicit missing components; core behavior gaps prohibit execution")


class HarnessReply(Record):
    harness: Harness | None
    observation: ObservationMap | None
    monitors: list[EventMonitor] = []
    consequence_observations: list[ConsequenceObservation] = []
    gap: str
    requests: list[ReadRequest] = []


class GraphPatch(Record):
    claims: list[ClaimDraft] = Field(default_factory=list,max_length=15)
    bindings: list[BindingDraft] = Field(default_factory=list,max_length=20)
    relations: list[RelationDraft] = Field(default_factory=list,max_length=30)
    units: list[UnitDraft] = Field(default_factory=list,max_length=5)
    expected_versions: dict[str, int] = {}
    rationale: str
    gaps: list[str] = []


class ReplayPlan(Record):
    harness: Harness
    monitors: list[EventMonitor] | None = None
    observation: ObservationMap | None = None
    checker_id: str
    rationale: str


class EncodingRevision(Record):
    old_model_id: str
    source_ids: list[str] = Field(min_length=1)
    rationale: str


class BuildReply(Record):
    reading_purpose: Literal["dependency", "context"] = Field(default="dependency", description="context only requests material attachment; dependency requires grounded scope reconnection before building")
    encoding_revision: EncodingRevision | None = None
    bundle: Bundle | None
    draft: ModelDraft | None = None
    gap: str
    requests: list[ReadRequest] = []


class JudgmentChange(Record):
    target_id: str
    field: Literal["description", "scope", "grounding", "source", "target", "kind", "group", "rationale", "pending", "source_ids", "claim_id", "material_id", "symbol", "start_line", "end_line",  "obligation_ids", "binding_ids", "relation_ids", "audit_question", "associations", "anchor"]
    old_value_json: str
    new_value_json: str


class ConditionDisposition(Record):
    condition_id: str | None = Field(default=None, description="Stable ID from the supplied condition records; preferred for new output")
    condition: str = Field(default="", description="Legacy exact-text reference; do not paraphrase it to bypass unresolved conditions")
    applies_to: Literal['old_judgment','current_judgment','independent_scope']
    rationale: str = Field(min_length=1, description="Explain the responsibility and range to which this condition applies, preserving counterevidence")
    source_ids: list[str] = Field(min_length=1)


class Feedback(Record):
    condition_dispositions: list[ConditionDisposition] = []
    kind: Literal["F1", "F2", "F3", "F4", "unresolved"]
    rationale: str
    evidence_ids: list[str]
    target_ids: list[str]
    relation_ids: list[str]
    new_basis: str = Field(description="For F2, why the old semantic judgment is invalid and what new material establishes")
    graph: GraphDraft | None
    bundle: Bundle | None
    patch: GraphPatch | None = None
    changes: list[JudgmentChange] = []
    old_judgment: str = ""
    new_judgment: str = ""
    grounding: Grounding = Grounding()
    requests: list[ReadRequest] = []


class SemanticRevision(Record):
    """Review-time F2 proposal; model/experiment revisions have their own later tasks."""
    kind: Literal['F2'] = 'F2'
    rationale: str
    evidence_ids: list[str]
    target_ids: list[str]
    relation_ids: list[str] = []
    new_basis: str
    patch: GraphPatch
    changes: list[JudgmentChange]
    old_judgment: str
    new_judgment: str
    grounding: Grounding
    condition_dispositions: list[ConditionDisposition] = []
    requests: list[ReadRequest] = []

    @model_validator(mode='before')
    @classmethod
    def import_legacy_feedback(cls,value):
        if isinstance(value,Feedback):value=value.model_dump(mode='json')
        if isinstance(value,dict):
            value=dict(value)
            for name in ('graph','bundle'):
                if value.get(name) is not None:raise ValueError('Semantic review cannot contain a model or full discovery')
                value.pop(name,None)
        return value

    @property
    def graph(self):return None
    @property
    def bundle(self):return None


class SpecRefinement(Record):
    understanding: str
    requests: list[ReadRequest] = Field(default_factory=list, max_length=12)
    audit_spec: ConsensusAuditSpec | None = None
    limitations: list[str]


class IssueResolution(Record):
    condition_dispositions: list[ConditionDisposition] = []
    issue_id: str
    target_version: int
    original_question: str = Field(description="The exact stored issue explanation; preserve stable problem identity")
    source_ids: list[str] = Field(min_length=1)
    rationale: str = Field(description="Why actual evidence answers this specific issue; describing current behavior alone is insufficient")
    residual_issue_ids: list[str] = Field(description="Other independent open issues that remain; never the resolved issue or its unresolved children")
    scope_limitations: list[str] = Field(description="Independent boundaries retained by the related review item")


class ReviewReply(Record):
    resolutions: list[IssueResolution] = []
    resolves_issue_ids: list[str] = []
    supersedes_task_ids: list[str] = []
    resolution_rationale: str = ""
    items: list[SemanticCheck] = Field(min_length=1,max_length=30)
    requests: list[ReadRequest] = Field(default_factory=list,max_length=12)
    revision: SemanticRevision | None = None
    limitations: list[str]


class ConsequenceReply(Record):
    disposition: Literal["investigate", "obligation_only", "defer", "compensation_candidate"]
    rationale: str
    source_ids: list[str] = Field(min_length=1)
    requests: list[ReadRequest] = []
    patch: GraphPatch | None = None
    limitations: list[str]


class QuestionReply(Record):
    revision: SemanticRevision | None = None
    question: AuditQuestion
    explanation: str
    requests: list[ReadRequest] = []
    patch: GraphPatch | None = None


class DirectCheckPlan(Record):
    description: str
    claim_id: str
    scope: Scope
    binding_ids: list[str] = Field(min_length=1)
    harness: Harness
    monitors: list[EventMonitor] = Field(min_length=1)
    observable_properties: list[ObservableProperty] = Field(min_length=1, description="Direct route supports event_assertion only. Use literal trigger/assertion comparisons, shared identity_fields and matching monitor.property; history properties require a local_model fallback.")
    uncertainties: list[str] = []


class DirectCheckReply(Record):
    reading_purpose: Literal["dependency", "context"] = "dependency"
    plan: DirectCheckPlan | None = None
    gap: str
    requests: list[ReadRequest] = []
    fallback: Literal["none", "source_review", "local_model"] = "none"
