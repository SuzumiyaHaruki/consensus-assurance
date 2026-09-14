from typing import Literal
from pydantic import Field, model_validator
from .types import Record, Scope, ConstraintSource, Grounding, CheckerSpec


class ReadRequest(Record):
    file: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    reason: str


class ClaimDraft(Record):
    id: str
    kind: Literal["goal", "obligation", "assumption"]
    description: str
    source_ids: list[str] = Field(min_length=1, description="Located materials; file kinds do not establish normative authority")
    scope: Scope
    pending: list[str]
    grounding: Grounding = Grounding()


class BindingDraft(Record):
    id: str
    claim_id: str
    material_id: str
    symbol: str = Field(description="One literal symbol spelling present in the referenced excerpt. Qualified names are allowed only when literally present. Do not combine multiple symbols; use separate bindings.")
    start_line: int
    end_line: int
    description: str
    pending: list[str]


class RelationDraft(Record):
    id: str
    source: str
    target: str
    kind: Literal["depends_all", "alternative", "supports", "maps", "conditional_on", "boundary"]
    group: str | None
    rationale: str
    pending: list[str]
    grounding: Grounding = Grounding()


class UnitDraft(Record):
    id: str
    goal_ids: list[str]
    obligation_ids: list[str] = Field(min_length=1)
    binding_ids: list[str] = Field(min_length=1)
    relation_ids: list[str] = Field(min_length=1)
    scope: Scope
    rationale: str
    goal_observable: bool


class Discovery(Record):
    understanding: str
    claims: list[ClaimDraft] = Field(default_factory=list, max_length=15)
    bindings: list[BindingDraft] = Field(default_factory=list, max_length=20)
    relations: list[RelationDraft] = Field(default_factory=list, max_length=30)
    units: list[UnitDraft] = Field(default_factory=list, max_length=5, description="Ranked candidate audit units; relationships also affect selection")
    conflicts: list[str]
    unexplored: list[str]
    selection_rationale: str
    gaps: list[str] = []
    reading_requests: list[ReadRequest] = Field(default_factory=list, max_length=12, description="Executable requests for actual file and line ranges; put unresolved search topics in gaps")


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



class Bundle(Record):
    description: str
    behavior: str = Field(min_length=1, description="TLA+ MODULE Behavior, with Init, Next, vars, and Obs; implementation behavior only")
    properties: str = Field(min_length=1, description="TLA+ MODULE Properties EXTENDS Behavior, defining obligation and optional goal invariants")
    constants: str = Field(description="TLC constant assignments only; no state/action constraints or invariant overrides")
    invariants: list[str] = []
    checked_claim_ids: list[str] = []
    initial_state: str
    variables: list[str]
    actions: list[str]
    constraints: list[ConstraintSource]
    scope: Scope
    observation: ObservationMap
    harness: Harness
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


class GraphPatch(Record):
    claims: list[ClaimDraft] = []
    bindings: list[BindingDraft] = []
    relations: list[RelationDraft] = []
    units: list[UnitDraft] = []
    expected_versions: dict[str, int] = {}
    rationale: str
    gaps: list[str] = []


class ReplayPlan(Record):
    harness: Harness
    monitors: list[EventMonitor] | None = None
    observation: ObservationMap | None = None
    checker_id: str
    rationale: str


class BuildReply(Record):
    bundle: Bundle | None
    gap: str
    requests: list[ReadRequest] = []


class Feedback(Record):
    kind: Literal["F1", "F2", "F3", "F4", "unresolved"]
    rationale: str
    evidence_ids: list[str]
    target_ids: list[str]
    relation_ids: list[str]
    new_basis: str = Field(description="For F2, why the old semantic judgment is invalid and what new material establishes")
    graph: Discovery | None
    bundle: Bundle | None
    patch: GraphPatch | None = None
    old_judgment: str = ""
    new_judgment: str = ""
    grounding: Grounding = Grounding()
    requests: list[ReadRequest] = []
