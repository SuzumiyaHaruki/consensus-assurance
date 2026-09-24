import copy,json
import pytest
from consensus_assurance.core.proposals import ConditionDisposition,GraphPatch
from consensus_assurance.workflow.feedback import apply_feedback
from test_graph_mutations import revision_for
from consensus_assurance.workflow.scope_updates import from_patch,validate_scope_update


@pytest.mark.parametrize('applies_to',['old_judgment','current_judgment','independent_scope'])
def test_F2_attributes_exact_conflict_without_erasing_it(prepared,applies_to):
    _,s,_,_=prepared;id=s.claims[1].id;f=revision_for(s,[id]);f.grounding.conflicts=['The previous statement also constrained object replacement']
    f.condition_dispositions=[ConditionDisposition(condition=f.grounding.conflicts[0],applies_to=applies_to,source_ids=f.evidence_ids,rationale='The source distinguishes update within one object from replacement; this is attributed to the stated judgment, not a claim about all histories')]
    apply_feedback(s,s.units[0],None,f)
    assert s.revisions[-1].status==('unresolved' if applies_to=='current_judgment' else 'applied')
    assert s.revisions[-1].after['grounding']['conflicts']==f.grounding.conflicts
    assert s.claims[1].version==(1 if applies_to=='current_judgment' else 2)


def test_F2_cannot_rename_unaddressed_condition(prepared):
    _,s,_,_=prepared;f=revision_for(s,[s.claims[1].id]);f.grounding.unresolved=['Actual input truth unverified']
    f.condition_dispositions=[ConditionDisposition(condition='Different harmless text',applies_to='old_judgment',source_ids=f.evidence_ids,rationale='Not the actual original question')]
    before=s.model_dump()
    with pytest.raises(ValueError):apply_feedback(s,s.units[0],None,f)
    assert s.model_dump()==before
