"""Structured controller diagnostics; wording does not select repair permissions."""
from typing import Literal
from .types import Record


class Diagnostic(Record):
    code: str
    category: Literal['format','location','association','material','semantic','tool','internal']
    task: str = ''
    candidate_version: int = 0
    object_ids: list[str] = []
    paths: list[str] = []
    material_ids: list[str] = []
    message: str
    allowed: list[Literal['representation','association','read','semantic_revision','stop']] = []

    def problem_key(self):
        return self.task+':'+self.code+':'+','.join(sorted(self.object_ids))+':'+','.join(sorted(self.paths))


class DiagnosticError(ValueError):
    def __init__(self,diagnostics):
        self.diagnostics=diagnostics
        super().__init__('; '.join(d.message for d in diagnostics))
