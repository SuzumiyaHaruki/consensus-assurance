import copy,json
import pytest
from consensus_assurance.core.proposals import ConditionDisposition,GraphPatch
from consensus_assurance.workflow.feedback import apply_feedback
from consensus_assurance.workflow.output_repair import diagnostic_targets
from consensus_assurance.workflow.prompts import loaded_resources,render,manifest
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




def test_manifest_applies_same_domain_method_to_first_build_and_revisions():
    expected={'skills/local-modeling/guide.md','skills/local-modeling/references/context-history.md'}
    for kind in ['build','F1','F3','technical','diagnose']:
        loaded=loaded_resources(kind,{})
        assert expected<=set(loaded['paths']) and len(loaded['paths'])==len(set(loaded['paths']))
        text=render(kind,{},'Identify support and its actual context')
        assert 'pending' in text and 'Identify support and its actual context' in text
    assert set(manifest()['tasks'])=={'read','discover','derive','build','retry','diagnose','F1','F2','F3','F4','targeted_read','graph_patch','replay','technical','spec_refine','semantic_review','scope_review','harness','direct_check','question'}
