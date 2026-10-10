from typing import Literal
from pydantic import Field
from .types import AssociatedCode, BindingAssociation, Record, Scope, Grounding, AuditQuestion, Concern


class ClaimDraft(Record):
    """A sourced requirement under explicit conditions, not the script for one experiment."""
    id: str
    kind: Literal["obligation", "assumption"]
    concern: Concern = "implementation_semantics"
    description: str = Field(description="Required relation across applicable objects and contexts; keep test instance IDs and timings in the check unless they determine applicability")
    source_ids: list[str] = Field(min_length=1, description="Located materials; file kinds do not establish normative authority")
    scope: Scope
    pending: list[str]
    grounding: Grounding = Grounding()


class BindingDraft(AssociatedCode):
    associations: list[BindingAssociation] = Field(default_factory=list, description="In a combined obligation, omitted associations are derived from its claim")
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
    candidate_id: str | None = None
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


class Comparison(Record):
    field: str
    op: Literal["eq", "ne"] = "eq"
    value: str | int | bool | None = None
    reference: str | None = None


class EventRequirement(Record):
    alias: str
    event: str
    conditions: list[Comparison] = Field(default_factory=list,description="Prerequisite conditions; alias references declare causal predecessors, list position does not")


class ObservableProperty(Record):
    checker_id: str
    kind: Literal["event_assertion", "event_implication"] = "event_assertion"
    trigger: Comparison
    assertion: Comparison
    antecedent: Comparison | None = None
    identity_fields: list[str] = Field(default_factory=list,description="Independent operation identity shared by prerequisites and result; never the value being compared or a context expected to change")
    description: str


class EventMonitor(Record):
    id: str
    checker_id: str
    event: str
    binding_ids: list[str]
    grounding: Grounding
    applicability_conditions: list[Comparison] = []
    admission_alias: str | None = Field(default=None,
        description="Prerequisite alias identifying admitted operations whose completion must be observed; may depend on earlier prerequisites, never on the result or array order")


class Harness(Record):
    execution_package: str | None = Field(default=None, description="Optional single local Go package or Rust crate directory; the controller fixes the effective package at acceptance")
    files: dict[str, str] = Field(default_factory=dict, description="Additional generated files with relative destinations and fixed source text")
    kind: str = Field(description="Harness kind advertised by the configured execution backend")
    source: str = Field(min_length=1, description="Executable experiment source, calling actual target code; no fabricated expected observations")
    description: str
    semantic_changes: list[str] = Field(description="Instrumentation and adaptation differences; never alter protocol logic to create a real finding")
    prerequisites: list[EventRequirement] = []
    legality: Grounding = Grounding()


class GraphPatch(Record):
    claims: list[ClaimDraft] = Field(default_factory=list,max_length=15)
    bindings: list[BindingDraft] = Field(default_factory=list,max_length=20)
    relations: list[RelationDraft] = Field(default_factory=list,max_length=30)
    units: list[UnitDraft] = Field(default_factory=list,max_length=5)
    expected_versions: dict[str, int] = {}
    rationale: str = ""
    gaps: list[str] = []


class ConditionDisposition(Record):
    condition_id: str | None = Field(default=None, description="Stable ID from the supplied condition records; preferred for new output")
    condition: str = Field(default="", description="Legacy exact-text reference; do not paraphrase it to bypass unresolved conditions")
    applies_to: Literal['old_judgment','current_judgment','independent_scope']
    rationale: str = Field(min_length=1, description="Explain the responsibility and range to which this condition applies, preserving counterevidence")
    source_ids: list[str] = Field(min_length=1)


class IssueResolution(Record):
    condition_dispositions: list[ConditionDisposition] = []
    issue_id: str
    source_ids: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list,
        description="Accepted execution, artifact, evidence or review IDs answering this issue; Material IDs belong in source_ids")
    rationale: str = Field(description="Why actual evidence answers this specific issue; describing current behavior alone is insufficient")
    residual_issue_ids: list[str] = Field(description="Other independent open issues that remain; never the resolved issue or its unresolved children")
    scope_limitations: list[str] = Field(description="Independent boundaries retained by the related review item")


class DirectCheckPlan(Record):
    """Concrete investigation of an accepted requirement; execution determines the observed result."""
    description: str = Field(description="This check’s discriminator, prefix, controls and observations; reference the accepted claim rather than restating it")
    claim_id: str = Field(default="", description="Omission selects the accepted Unit obligation")
    binding_ids: list[str] = Field(default_factory=list, description="Omission selects the Unit bindings")
    harness: Harness
    monitors: list[EventMonitor] = Field(min_length=1)
    observable_properties: list[ObservableProperty] = Field(min_length=1, description="Direct route supports event_assertion and event_implication. Correlate prerequisite fields by alias; observe prerequisites and results from the same legal history. Unsupported general temporal properties must remain an explicit limitation.")
    uncertainties: list[str] = []
