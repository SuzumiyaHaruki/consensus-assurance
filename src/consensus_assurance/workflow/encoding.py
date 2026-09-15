"""Explicit checker-encoding correction preserves the claim and behavior contract."""
import re
from .artifacts import materialize_bundle


def validate_encoding(state,previous,current,repaired,revision):
    if revision.old_model_id!=previous.id or not revision.rationale.strip() or not set(revision.source_ids)<={m.id for m in state.materials}:
        raise ValueError('Encoding correction needs the actual previous model and material rationale')
    if not revision.source_ids:raise ValueError('Encoding correction cannot cite only a failing result')
    current_versions={c.id:c.version for c in state.claims}
    if any(current_versions.get(id)!=version for id,version in previous.graph_versions.items() if id in current_versions):raise ValueError('Claim meaning changed; this is F2, not encoding correction')
    for field in ['behavior','constants','scope','constraints','observable_properties']:
        if getattr(current,field)!=getattr(repaired,field):raise ValueError('Encoding correction cannot change behavior, scope or intended observable property; use F1/F2/F3')
    if current.checker_specs()!=repaired.checker_specs():raise ValueError('Encoding correction changed claim/checker attribution')
    text=materialize_bundle(repaired).properties
    for spec in repaired.checker_specs():
        if re.search(r'(?m)^\s*'+spec.invariant+r'\s*==\s*(?:TRUE|FALSE)\s*$',text):raise ValueError('A constant checker cannot discharge a semantic encoding repair')


def issue_models(state,issue,current):
    old=next((m for m in state.models if m.id==issue.model_id),None)
    lineage=set();parent=current.previous_id
    while parent and parent not in lineage:
        lineage.add(parent);model=next((m for m in state.models if m.id==parent),None);parent=model.previous_id if model else None
    if old is None or old.id not in lineage:return None
    if old.checkers!=current.checkers or old.scope!=current.scope or old.graph_versions!=current.graph_versions:return None
    return old
