import copy,json
import pytest
from consensus_assurance.core.proposals import ConditionDisposition,GraphPatch
from consensus_assurance.workflow.feedback import apply_feedback
from consensus_assurance.workflow.output_repair import diagnostic_targets
from consensus_assurance.workflow.prompts import loaded_resources,render,manifest
from test_round5_boundaries import revision_for
from test_round9_failures import archived,reply
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


@pytest.mark.parametrize('nested',[False,True])
def test_reordered_scope_diagnostics_address_original_proposal(nested):
    s=archived();p=GraphPatch.model_validate(reply('f6577be6da9a47f68581404d750a55d6-graph_patch'));p.bindings.reverse()
    u=next(u for u in s.units if u.id=='U_commit')
    # Force a genuinely external support use with no selected directed chain.
    p.units[0].code_uses[-1].role='support'
    with pytest.raises(ValueError) as exc:validate_scope_update(s,from_patch(s,u,p))
    raw=p.model_dump(mode='json');targets=diagnostic_targets({'revision':{'patch':raw}} if nested else raw,exc.value.diagnostics,100000)
    path=('/revision/patch' if nested else '')+'/units/0/code_uses'
    assert any(t['path']==path and t['exists'] for t in targets)
    for t in targets:
        if '/bindings/' in t['path']:assert t['exists']


def test_manifest_applies_same_domain_method_to_first_build_and_revisions():
    expected={'skills/local-modeling/guide.md','skills/local-modeling/references/context-history.md'}
    for kind in ['build','F1','F3','technical','diagnose']:
        loaded=loaded_resources(kind,{})
        assert expected<=set(loaded['paths']) and len(loaded['paths'])==len(set(loaded['paths']))
        text=render(kind,{},'Identify support and its actual context')
        assert 'pending' in text and 'Identify support and its actual context' in text
    assert set(manifest()['tasks'])=={'read','discover','build','retry','diagnose','F1','F2','F3','F4','targeted_read','graph_patch','replay','technical','explore','semantic_review','consequence','scope_review','harness'}
