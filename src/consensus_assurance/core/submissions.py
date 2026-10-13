"""One file-backed update; existing references are explicit, new batch names start with @."""
from typing import Literal
from pydantic import Field, StrictInt
from .types import Record, KnowledgeUse
from .types import EventComparison, EventRequirement, FailureAttribution
from .types import Scope, SourceAnchor


class SourceRange(Record):
    id: str
    file: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    kind: Literal["document_statement", "interface_statement", "test_expectation", "code_observation", "protocol_candidate"]


class QuestionUpdate(Record):
    id: str | None = None
    ref: str | None = None
    question: str | None = None
    source_ids: list[str] | None = None
    hypothesis: str | None = None
    discriminator: str | None = None
    disposition: Literal["active", "paused", "explained", "closed"] | None = None
    parent_id: str | None = None
    knowledge: list[KnowledgeUse] | None = None
    counterevidence: list[str] | None = None
    limitations: list[str] | None = None
    resume_conditions: list[str] | None = None


class KnowledgeUpdate(Record):
    id: str | None = None
    ref: str | None = None
    kind: Literal["behavior", "fact"]
    statement: str = Field(min_length=1)
    conditions: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    executions: dict[str, list[StrictInt]] = {}
    knowledge: list[KnowledgeUse] = []
    changed_premise: str = Field(default="", description="For a correction, explain the semantic difference; empty for unrelated or representational changes")
    affected_uses: list[str] = Field(default_factory=list, description="Saved investigation, experiment or interpretation IDs using the changed premise directly or through recorded knowledge revisions; never inferred from similar words")


class GapUpdate(Record):
    investigation_id: str
    question: str = Field(min_length=1)
    experiment_id: str | None = None


class InterpretationUpdate(Record):
    investigation_id: str
    experiment_id: str | None = None
    source_ids: list[str] = Field(min_length=1)
    executions: dict[str, list[StrictInt]] = {}
    conclusion: Literal["explained", "conditional", "violated", "holds", "unresolved"]
    defect_claim: Literal["asserted", "refuted", "unresolved"] | None = Field(default=None,
        description="Current scoped model defect judgment, independent of execution and comparison results; omitted means no explicit current claim")
    rationale: str = Field(min_length=1)
    answers: dict[str, str | None] = Field(default_factory=dict,
        description="Registered gap ID to its sourced or observed answer; null withdraws an earlier answer with the reason in rationale; omitted IDs keep prior answers")
    knowledge: list[KnowledgeUse] = []
    counterevidence: list[str] = []
    limitations: list[str] = []
    joint_history: str = Field(default="", description="Explain compatibility when associating a separate producer experiment")
    failure_attribution: FailureAttribution | None = None


class ExperimentRequest(Record):
    investigation_id: str
    harness_path: str
    files: dict[str, str] = {}
    execution_package: str | None = None
    source_ids: list[str] = Field(min_length=1)
    anchors: list[SourceAnchor] = []
    scope: Scope
    prefix: str = Field(min_length=1)
    semantic_changes: list[str] = []
    requirement: str | None = None
    responsibility: str = ""
    prerequisites: list[EventRequirement] = []
    comparisons: list[EventComparison] = []
    knowledge: list[KnowledgeUse] = []
    previous_id: str | None = None
    revision_reason: str = ""


class StopRequest(Record):
    reason: Literal["bounded_completed"]
    rationale: str = Field(min_length=1)


class AuditSubmission(Record):
    rationale: str = Field(min_length=1)
    sources: list[SourceRange] = []
    investigations: list[QuestionUpdate] = []
    knowledge: list[KnowledgeUpdate] = []
    gaps: list[GapUpdate] = []
    interpretations: list[InterpretationUpdate] = []
    experiment: ExperimentRequest | None = None
    repeat_experiment_id: str | None = Field(default=None, min_length=1,
        description="Explicitly execute an existing fixed experiment again; rationale explains the purpose; mutually exclusive with experiment and stop")
    stop: StopRequest | None = None
