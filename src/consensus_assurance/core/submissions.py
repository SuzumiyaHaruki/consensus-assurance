"""File-backed research products; Codex browsing and editing need no submission."""
from typing import Annotated, Literal, Union
from pydantic import Field, TypeAdapter, field_validator, model_validator
from .proposals import BindingDraft, ClaimDraft, EncodingRevision, IssueResolution
from .types import AuditQuestion, Record, SemanticCheck


class SourceRange(Record):
    id: str
    file: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    kind: Literal["document_statement", "interface_statement", "test_expectation", "code_observation", "protocol_candidate"]


class UnderstandingChange(Record):
    impact: Literal["clarification", "meaning", "dependency"]
    rationale: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    preserves: str = Field(default='', description='Shared sourced explanation of why the existing propositions, premises and observations still apply')
    challenges: dict[str, str] = Field(default_factory=dict, description='Saved Candidate IDs and the concrete premise or interpretation challenged by this knowledge')


class QuestionUpdate(Record):
    unknowns: list[str]
    resume_conditions: list[str]


class ResearchFeedback(Record):
    """New sourced answers and next discriminators; historical remaining is not current pending work."""
    ref_ids: list[str] = Field(min_length=1)
    answered: str = Field(min_length=1)
    remaining: list[str]
    understanding: Literal["updated", "unchanged", "deferred"] | None = Field(default=None,
        description="Research understanding across turns, not a declaration that this submission changes the map")
    rationale: str = Field(min_length=1)
    question_updates: dict[str, QuestionUpdate] = {}

    @field_validator('answered', 'rationale')
    @classmethod
    def substantive(cls, value):
        if not value.strip():
            raise ValueError('Research feedback requires substantive text')
        return value


class Submission(Record):
    rationale: str = Field(min_length=1)
    sources: list[SourceRange] = []
    feedback: ResearchFeedback | None = None
    repair_of: str | None = Field(default=None, description="Rejected operation ID whose complete draft this submission repairs")


class MappedSubmission(Submission):
    map_path: str | None = None
    map_changes: dict[str, UnderstandingChange] = {}
    reconnect_questions: dict[str, AuditQuestion] = Field(default_factory=dict,
        description="Optional explicit question reconnections; changing an accepted Unit proposition still requires F2/F3")


class CandidateSubmission(MappedSubmission):
    action: Literal["continue", "pause", "explained", "obligation"]
    candidate_id: str | None = None
    parent_candidate_id: str | None = None
    question: AuditQuestion
    resume_conditions: list[str] = []
    result_implications: dict[Literal["holds", "violated", "incomplete"], str] = {}
    obligation: ClaimDraft | None = None
    bindings: list[BindingDraft] = []

    @model_validator(mode="after")
    def shape(self):
        if self.candidate_id and self.parent_candidate_id:
            raise ValueError("Continue an existing candidate or fork from a parent; do not express both")
        if self.parent_candidate_id and (set(self.result_implications) != {"holds", "violated", "incomplete"}
                or not all(v.strip() for v in self.result_implications.values())):
            raise ValueError("A child must explain each bounded result's effect and inference limits on its parent")
        if self.action == "pause" and (not self.candidate_id or not self.resume_conditions):
            raise ValueError("Pause needs an existing candidate and concrete resume conditions")
        if self.action != "pause" and self.resume_conditions:
            raise ValueError("Resume conditions belong to an explicit pause")
        if self.action == "obligation":
            if not self.obligation or not self.bindings:
                raise ValueError("An obligation needs its claim and source bindings")
        elif self.obligation or self.bindings:
            raise ValueError("Only obligation submissions create a claim and bindings")
        return self


class CheckSubmission(Submission):
    action: Literal["check", "revise_check"]
    unit_id: str | None = None
    candidate: CandidateSubmission | None = None
    plan_path: str
    harness_path: str
    files: dict[str, str] = Field(default_factory=dict, description="Destination path to draft source path for helpers")
    previous_check_id: str | None = None
    repair_issue_ids: list[str] = Field(default_factory=list,
        description="Exact issues whose driver premises the new harness legality answers; admission does not resolve them")
    encoding_revision: EncodingRevision | None = None

    @model_validator(mode="after")
    def shape(self):
        if bool(self.unit_id) == bool(self.candidate):
            raise ValueError("Select an existing unit or create one explicit obligation, not both")
        if self.candidate and self.candidate.action != "obligation":
            raise ValueError("Combined check requires an obligation candidate")
        if self.candidate and self.previous_check_id:
            raise ValueError("A new obligation cannot revise another unit's check")
        if self.action == "revise_check" and not self.previous_check_id:
            raise ValueError("A revision needs its previous artifact")
        if self.encoding_revision and not self.previous_check_id:
            raise ValueError("Encoding correction needs its previous artifact")
        if self.repair_issue_ids and (not self.previous_check_id or self.encoding_revision):
            raise ValueError("Driver premise repair needs an ordinary revision of a previous check")
        return self


class ResearchSubmission(MappedSubmission):
    action: Literal["research"]
    graph_path: str | None = None
    scope_path: str | None = None

    @model_validator(mode="after")
    def shape(self):
        if self.graph_path and self.scope_path or not any((self.map_path, self.graph_path, self.scope_path, self.feedback)):
            raise ValueError("Research needs sourced feedback, a map, graph addition or scoped update; a map may accompany one graph operation")
        return self


class SemanticSubmission(MappedSubmission):
    action: Literal["semantic_revision"]
    unit_id: str
    feedback_path: str


class ArtifactReviewItem(SemanticCheck):
    target_id: str | None = None


class ReviewSubmission(Submission):
    action: Literal["review"]
    artifact_id: str
    review_items: list[ArtifactReviewItem] = Field(min_length=1, max_length=30)
    resolutions: list[IssueResolution] = []

    @model_validator(mode='after')
    def inherit_target(self):
        for item in self.review_items:
            if item.target_id is None:item.target_id = self.artifact_id
        return self


class ExploreSubmission(Submission):
    action: Literal["explore"]
    question: str = Field(min_length=1)
    harness_path: str
    files: dict[str, str] = {}


class StopSubmission(Submission):
    action: Literal["stop"]
    scope: Literal["candidate", "family", "focus", "run"]
    reason: Literal["bounded_completed", "insufficient_basis", "tool_gap", "resource_limit", "user_stop", "no_actionable_direction"]
    ref_ids: list[str] = []
    resume_conditions: list[str] = []


PRODUCTS = TypeAdapter(Annotated[Union[CandidateSubmission, CheckSubmission,
    ResearchSubmission, SemanticSubmission, ReviewSubmission, ExploreSubmission, StopSubmission],
    Field(discriminator="action")])


class AuditSubmission:
    model_validate = staticmethod(PRODUCTS.validate_python)
    model_json_schema = staticmethod(PRODUCTS.json_schema)
