"""Explicit offline imports only; never normalize fresh backend declarations here."""
import json
from consensus_assurance.core.types import AuditQuestion


def import_question_changes(reply):
    """Return a copy with historical whole-question diffs normalized to this schema."""
    reply=reply.model_copy(deep=True)
    revision=getattr(reply,'revision',None)
    if revision:
        for change in revision.changes:
            if change.field=='audit_question':
                for name in ('old_value_json','new_value_json'):
                    value=json.loads(getattr(change,name))
                    if value is not None:setattr(change,name,AuditQuestion.model_validate(value).model_dump_json())
    return reply
