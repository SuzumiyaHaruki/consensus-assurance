from typing import Literal
from pydantic import Field, model_validator
from .types import Record, Scope, ConstraintSource


class ClaimDraft(Record):
    id: str
    kind: Literal["goal", "obligation", "assumption"]
    description: str
    source_ids: list[str] = Field(min_length=1, description="Material IDs supporting this candidate; code alone does not establish required behavior")
    scope: Scope
    pending: list[str]


class BindingDraft(Record):
    id: str
    claim_id: str
    material_id: str
    symbol: str
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
    claims: list[ClaimDraft] = Field(min_length=2, max_length=15)
    bindings: list[BindingDraft] = Field(min_length=1, max_length=20)
    relations: list[RelationDraft] = Field(min_length=1, max_length=30)
    units: list[UnitDraft] = Field(min_length=1, max_length=5, description="Ranked candidate audit units; relationships also affect selection")
    conflicts: list[str]
    unexplored: list[str]
    selection_rationale: str


class FieldProjection(Record):
    model_field: str
    raw_field: str


class ObservationMap(Record):
    fields: list[FieldProjection] = Field(description="Model Obs record field to raw state field mapping; direct scalar projection only")
    required_events: list[str] = Field(description="Event names that must be present for calibration to be conclusive")
    max_internal_steps: int = Field(default=3, ge=0, le=20)
    allow_observed_stutter: bool = True
    description: str


class Harness(Record):
    kind: str = Field(description="Harness kind advertised by the selected implementation adapter")
    source: str = Field(min_length=1, description="Executable experiment source, calling actual target code; no fabricated expected observations")
    description: str
    prerequisite_events: list[str] = Field(description="Ordered events required for candidate replay; not claims that they occurred")
    semantic_changes: list[str] = Field(description="Instrumentation and adaptation differences; never alter protocol logic to create a real finding")


class Bundle(Record):
    description: str
    behavior: str = Field(min_length=1, description="TLA+ MODULE Behavior, with Init, Next, vars, and Obs; implementation behavior only")
    properties: str = Field(min_length=1, description="TLA+ MODULE Properties EXTENDS Behavior, defining obligation and optional goal invariants")
    constants: str = Field(description="TLC constant assignments only; no state/action constraints or invariant overrides")
    invariants: list[str] = Field(min_length=1)
    checked_claim_ids: list[str] = Field(min_length=1)
    initial_state: str
    variables: list[str]
    actions: list[str]
    constraints: list[ConstraintSource]
    scope: Scope
    observation: ObservationMap
    harness: Harness
    uncertainties: list[str]


class Feedback(Record):
    kind: Literal["F1", "F2", "F3", "F4", "unresolved"]
    rationale: str
    evidence_ids: list[str]
    target_ids: list[str]
    relation_ids: list[str]
    new_basis: str = Field(description="For F2, why the old semantic judgment is invalid and what new material establishes")
    graph: Discovery | None
    bundle: Bundle | None
