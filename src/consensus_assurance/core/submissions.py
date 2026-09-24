"""File-backed research products; native browsing and editing need no submission."""
from typing import Annotated, Literal, Union
from pydantic import Field, TypeAdapter, model_validator
from .proposals import BindingDraft, ClaimDraft, EncodingRevision, IssueResolution
from .types import AuditQuestion, Record, SemanticCheck


class SourceRange(Record):
    id: str
    file: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    kind: Literal["document_statement", "interface_statement", "test_expectation", "code_observation", "protocol_candidate"]


class Submission(Record):
    rationale: str = Field(min_length=1)
    sources: list[SourceRange] = []


class CandidateSubmission(Submission):
    action: Literal["continue", "pause", "explained", "obligation"]
    candidate_id: str | None = None
    parent_candidate_id: str | None = None
    question: AuditQuestion
    resume_conditions: list[str] = []
    counterevidence_resolution: str = ""
    obligation: ClaimDraft | None = None
    bindings: list[BindingDraft] = []

    @model_validator(mode="after")
    def shape(self):
        if self.candidate_id and self.parent_candidate_id:
            raise ValueError("Continue an existing candidate or fork from a parent; do not express both")
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
        return self


class ModelSubmission(Submission):
    action: Literal["model"]
    unit_id: str
    model_path: str
    behavior_path: str
    properties_path: str
    harness_path: str | None = None
    files: dict[str, str] = {}
    previous_model_id: str | None = None
    encoding_revision: EncodingRevision | None = None
    change: Literal["technical", "F1", "F4"] = "technical"
    replay_finding_id: str | None = None


class ResearchSubmission(Submission):
    action: Literal["research"]
    map_path: str | None = None
    graph_path: str | None = None
    scope_path: str | None = None

    @model_validator(mode="after")
    def shape(self):
        if sum(bool(p) for p in (self.map_path, self.graph_path, self.scope_path)) != 1:
            raise ValueError("Research submission needs exactly one map, graph addition or scoped update")
        return self


class SemanticSubmission(Submission):
    action: Literal["semantic_revision"]
    unit_id: str
    feedback_path: str


class ReviewSubmission(Submission):
    action: Literal["review"]
    artifact_id: str
    review_items: list[SemanticCheck] = Field(min_length=1)
    resolutions: list[IssueResolution] = []


class ExploreSubmission(Submission):
    action: Literal["explore"]
    question: str = Field(min_length=1)
    harness_path: str
    files: dict[str, str] = {}


class StopSubmission(Submission):
    action: Literal["stop"]


PRODUCTS = TypeAdapter(Annotated[Union[CandidateSubmission, CheckSubmission, ModelSubmission,
    ResearchSubmission, SemanticSubmission, ReviewSubmission, ExploreSubmission, StopSubmission],
    Field(discriminator="action")])


class NativeSubmission:
    model_validate = staticmethod(PRODUCTS.validate_python)
    model_json_schema = staticmethod(PRODUCTS.json_schema)
