"""File-backed investigation products; browsing and editing need no submission."""
from typing import Annotated, Any, Literal, Union
from pydantic import Field, TypeAdapter, field_validator, model_validator
from .proposals import BindingDraft, ClaimDraft, GraphPatch, IssueResolution
from .types import AuditQuestion, Record, SemanticCheck


class SourceRange(Record):
    id: str
    file: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    kind: Literal["document_statement", "interface_statement", "test_expectation", "code_observation", "protocol_candidate"]


class UnderstandingChange(Record):
    rationale: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    preserves: str = Field(default='', description='Why the affected saved interpretations still apply')
    challenges: dict[str, str] = Field(default_factory=dict, description='Candidate IDs and the specific interpretation challenged')


class QuestionUpdate(Record):
    unknowns: list[str]
    resume_conditions: list[str]


class ResearchFeedback(Record):
    ref_ids: list[str] = Field(min_length=1)
    answered: str = Field(min_length=1)
    remaining: list[str]
    rationale: str = Field(min_length=1)
    question_updates: dict[str, QuestionUpdate] = {}

    @field_validator('answered', 'rationale')
    @classmethod
    def substantive(cls, value):
        if not value.strip():
            raise ValueError('Research feedback requires substantive text')
        return value


class ArtifactReviewItem(SemanticCheck):
    target_id: str | None = None


class ResultReview(Record):
    artifact_id: str
    review_items: list[ArtifactReviewItem] = Field(min_length=1)
    resolutions: list[IssueResolution] = []

    @model_validator(mode='after')
    def inherit_target(self):
        for item in self.review_items:
            if item.target_id is None:item.target_id = self.artifact_id
        return self


class Submission(Record):
    rationale: str = Field(min_length=1)
    sources: list[SourceRange] = []
    feedback: ResearchFeedback | None = None
    review: ResultReview | None = None
    map_path: str | None = None
    map_changes: dict[str, UnderstandingChange] = {}
    repair_of: str | None = Field(default=None, description='Retained rejected operation whose draft this submission repairs')


class CandidateSubmission(Submission):
    action: Literal["continue", "pause", "explained", "obligation"]
    candidate_id: str | None = None
    parent_candidate_id: str | None = None
    question: AuditQuestion | dict[str, Any] | None = Field(default=None,
        description='New sourced question, or only changed AuditQuestion fields when candidate_id is supplied')
    resume_conditions: list[str] = []
    obligation: ClaimDraft | None = None
    bindings: list[BindingDraft] = []

    @model_validator(mode="after")
    def shape(self):
        if self.candidate_id and self.parent_candidate_id:
            raise ValueError('Continue a saved Candidate or create a linked child')
        if self.action == 'pause' and (not self.candidate_id or not self.resume_conditions):
            raise ValueError('Pause needs an existing Candidate and concrete resume conditions')
        if self.action != 'pause' and self.resume_conditions:
            raise ValueError('Resume conditions belong to an explicit pause')
        if self.action == 'obligation':
            if not self.obligation or not self.bindings:
                raise ValueError('An obligation needs its claim and source bindings')
        elif self.obligation or self.bindings:
            raise ValueError('Only obligation submissions create a claim and bindings')
        return self


class CheckSubmission(Submission):
    action: Literal["check", "revise_check"]
    unit_id: str | None = None
    candidate: CandidateSubmission | None = None
    plan_path: str
    harness_path: str
    files: dict[str, str] = Field(default_factory=dict, description='Destination path to draft source path for helpers')
    previous_check_id: str | None = None
    revision: GraphPatch | None = Field(default=None,
        description='Optional changes to the previous check\'s claim, bindings or Unit; expected versions protect saved inputs. The controller records the diff and executes the successor.')

    @model_validator(mode="after")
    def shape(self):
        if bool(self.unit_id) == bool(self.candidate):
            raise ValueError('Select an existing Unit or submit a sourced obligation together with its check')
        if self.candidate and self.candidate.action != 'obligation':
            raise ValueError('Combined check requires an obligation Candidate')
        if self.candidate and self.previous_check_id:
            raise ValueError('A new obligation cannot revise another Unit\'s check')
        if (self.action == 'revise_check') != bool(self.previous_check_id):
            raise ValueError('revise_check identifies its previous artifact; check starts an independent scenario')
        if self.revision and not self.previous_check_id:
            raise ValueError('Changing accepted inputs requires revise_check and a fresh execution')
        return self


class ResearchSubmission(Submission):
    action: Literal['research']

    @model_validator(mode='after')
    def shape(self):
        if not any((self.map_path, self.feedback, self.review)):
            raise ValueError('Research needs sourced feedback, a map or an actual result review')
        return self


class ExploreSubmission(Submission):
    action: Literal['explore']
    question: str = Field(min_length=1)
    harness_path: str
    execution_package: str | None = None
    files: dict[str, str] = {}


class StopSubmission(Submission):
    action: Literal['stop']
    scope: Literal['candidate', 'family', 'focus', 'run']
    reason: Literal['bounded_completed', 'insufficient_basis', 'tool_gap', 'resource_limit', 'user_stop', 'no_actionable_direction']
    ref_ids: list[str] = []
    resume_conditions: list[str] = []


PRODUCTS = TypeAdapter(Annotated[Union[CandidateSubmission, CheckSubmission,
    ResearchSubmission, ExploreSubmission, StopSubmission], Field(discriminator='action')])


class AuditSubmission:
    model_validate = staticmethod(PRODUCTS.validate_python)
    model_json_schema = staticmethod(PRODUCTS.json_schema)
