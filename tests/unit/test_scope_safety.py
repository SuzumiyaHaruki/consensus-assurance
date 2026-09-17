"""Scope refinement preserves semantics, full graph checks and historical applicability."""
import copy
import pytest
from test_context_failures import dependency
from consensus_assurance.workflow.scope_updates import from_patch,apply_scope_update,validate_scope_update,ScopeAssessment
from consensus_assurance.core.types import AuditQuestion
from consensus_assurance.workflow.graph import apply_patch


@pytest.mark.parametrize('field',['assumptions','excluded','obligation','other_unit','role'])
def test_scope_cannot_smuggle_semantics_or_other_writes(prepared,field):
    state,patch,_=dependency(prepared);unit=state.units[0]
    if field in {'assumptions','excluded'}:getattr(patch.units[0].scope,field).append('All inputs satisfy the obligation')
    elif field=='obligation':
        from consensus_assurance.core.proposals import ClaimDraft
        c=state.claims[1];d=ClaimDraft(**{k:v for k,v in c.model_dump().items() if k in ClaimDraft.model_fields});d.description='A weaker responsibility';patch.claims.append(d)
    elif field=='other_unit':patch.units[0].obligation_ids.append('input_obligation')
    else:
        # A new direct role is not an existing use reinterpretation; make an existing role first.
        old=patch.units[0].code_uses[-1].model_copy(deep=True);old.binding_id='step_binding';old.role='direct';old.relation_ids=[]
        unit.code_uses=[old];patch.units[0].code_uses.insert(0,old.model_copy(update={'role':'support'}))
    before=state.model_dump()
    with pytest.raises(ValueError):apply_scope_update(state,from_patch(state,unit,patch))
    assert state.model_dump()==before


def test_question_refinement_requires_sourced_assessment(prepared):
    state,patch,sources=dependency(prepared);unit=state.units[0]
    q=AuditQuestion(question='Does the result stay inside the legal bound?',importance='A consumer relies on the bound',trigger_rationale='An actual consumer input exercises the bound',source_ids=[state.materials[0].id])
    unit.audit_question=q;patch.units[0].audit_question=q.model_copy(deep=True);patch.units[0].audit_question.event_paths=['Provider normalization precedes counter execution']
    update=from_patch(state,unit,patch)
    assert validate_scope_update(state,update)==['audit_question']
    with pytest.raises(ValueError):apply_scope_update(state,update)
    update.assessment=ScopeAssessment(decision='refinement',source_ids=sources,addressed_fields=['audit_question'],preserved_question=q.question,rationale='The actually read provider refines the input production event without changing the original bounded result',remaining_unknowns=['No production history proof'])
    new=apply_scope_update(state,update)
    assert new.audit_question.question==q.question and new.scope==unit.scope


def test_new_binding_still_requires_real_symbol_and_association(prepared):
    state,patch,_=dependency(prepared);patch.bindings[0].symbol='imaginary'
    before=state.model_dump()
    with pytest.raises(ValueError):apply_scope_update(state,from_patch(state,state.units[0],patch))
    assert state.model_dump()==before


def test_shared_binding_does_not_select_all_associated_obligations(prepared):
    from consensus_assurance.workflow.graph import expand_unit
    _,state,_,_=prepared;b=next(b for b in state.bindings if b.id=='input_binding')
    b.associations.append(b.associations[0].model_copy(update={'claim_id':'step_obligation'}))
    unit=state.units[0];new=expand_unit(state,unit,['input_dependency'])
    assert new.obligation_ids==unit.obligation_ids
    assert 'input_binding' in new.binding_ids and not new.obligation_checks


@pytest.mark.parametrize('return_type',['interface{}','struct{ Value int }'])
def test_go_accessor_return_type_braces_do_not_hide_actual_body(return_type):
    from consensus_assurance.core.types import Material
    from consensus_assurance.core.proposals import BindingDraft
    from consensus_assurance.workflow.locations import locate
    source='func (x *Result) Response() '+return_type+' {\n    return x.response\n}\n'
    material=Material(id='actual',file='future.go',start_line=1,end_line=3,text=source.rstrip('\n'),content_digest='synthetic',kind='code_observation')
    b=BindingDraft(id='accessor',claim_id='O',material_id='actual',symbol='Response',start_line=1,end_line=3,description='Accessor',pending=[])
    anchor,error=locate(b,{'actual':material})
    assert anchor and anchor['start_line']==1,error


def test_go_named_slice_groups_only_contiguous_matching_receiver_methods():
    from consensus_assurance.core.types import Material
    from consensus_assurance.workflow.locations import declarations
    text='type Scores []int\n\nfunc (s Scores) Len() int { return len(s) }\nfunc other() {}\nfunc (s Scores) Less(i, j int) bool { return s[i] < s[j] }'
    m=Material(id='source',file='sort.go',start_line=1,end_line=5,text=text,content_digest='synthetic',kind='code_observation')
    d=next(d for d in declarations(m) if d['symbol']=='Scores' and d['kind']=='declaration')
    assert d['start']==1 and d['end']==3
