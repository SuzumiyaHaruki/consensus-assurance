import json
import pytest
from consensus_assurance.core.types import Material,CodeUse,BindingAssociation
from consensus_assurance.core.proposals import BindingDraft,Discovery,GraphPatch
from consensus_assurance.workflow.locations import locate,declarations
from consensus_assurance.workflow.graph import apply_discovery,apply_patch
from consensus_assurance.workflow.graph_diagnostics import diagnose_graph
from consensus_assurance.workflow.associations import relevant_use
from consensus_assurance.workflow.output_repair import diagnostic_targets,diagnostic_context


def material(text,start=1,file='sample.go'):
    return Material(id=f'{file}:{start}:{start+len(text.splitlines())-1}',file=file,start_line=start,end_line=start+len(text.splitlines())-1,kind='code_observation',text=text,content_digest='synthetic-source')


def binding(m,symbol='accept',start=2,end=2,anchor=None):
    return BindingDraft(id='code',claim_id='O',material_id=m.id,symbol=symbol,start_line=start,end_line=end,description='Observed operation body',pending=[],anchor=anchor)


def test_declaration_previous_line_does_not_expand_behavior():
    m=material('func accept() {\n  value++\n}\n');b=binding(m)
    anchor,error=locate(b,{m.id:m})
    assert anchor['start_line']==1 and b.start_line==2 and not error


def test_declaration_outside_read_material_requires_reading():
    partial=material('  value++\n}\n',2);b=binding(partial)
    assert locate(b,{partial.id:partial})[0] is None
    complete=material('func accept() {\n  value++\n}\n')
    assert locate(b,{partial.id:partial,complete.id:complete})[0]['material_id']==complete.id


def test_multiline_signature_and_same_named_methods_use_exact_anchor():
    m=material('func (a *First) accept(\n input int,\n) {\n value++\n}\nfunc (b *Second) accept() {\n value--\n}\n')
    b=binding(m,start=7,end=7);anchor,error=locate(b,{m.id:m})
    assert anchor['start_line']==6
    b.anchor={'material_id':m.id,'symbol':'accept','start_line':1,'end_line':3}
    assert locate(b,{m.id:m})[0] is None
    first=binding(m,start=4,end=4);assert locate(first,{m.id:m})[0]['end_line']==3


def test_comment_word_and_other_function_cannot_prove_identity():
    m=material('// func imaginary() {\nfunc accept() {\n value++\n}\nfunc unrelated() {\n value--\n}\n')
    assert locate(binding(m,'imaginary',3,3),{m.id:m})[0] is None
    assert locate(binding(m,'accept',6,6),{m.id:m})[0] is None


def test_support_use_keeps_checked_obligations_and_one_physical_location(prepared):
    _,state,_,responses=prepared;p=Discovery.model_validate(responses[1]);unit=p.units[0];external=p.bindings[-1]
    unit.binding_ids.append(external.id)
    before=list(unit.obligation_ids)
    unit.code_uses=[CodeUse(binding_id=external.id,role='input',claim_ids=[external.claim_id],relation_ids=['input_dependency'],source_ids=[external.material_id],rationale='Selected consumer depends on the input producer',unverified=['Producer responsibility is not checked by this unit'])]
    apply_discovery(state,p)
    assert state.units[0].obligation_ids==before and len(state.bindings)==len(p.bindings)
    assert state.units[0].obligation_checks=={}
    assert 'claim_id' not in state.bindings[0].model_dump()


def test_multiple_obligations_share_one_binding_with_sourced_associations(prepared):
    _,state,_,responses=prepared;p=Discovery.model_validate(responses[1]);b=p.bindings[0]
    b.associations.append(BindingAssociation(claim_id=p.claims[-1].id,source_ids=[b.material_id],rationale='The same entry also consumes the producer condition'))
    apply_discovery(state,p)
    assert len(state.bindings[0].associations)==2
    with pytest.raises(ValueError):_ = state.bindings[0].claim_id


@pytest.mark.parametrize('edge_kind',['supports','alternative','maps'])
def test_arbitrary_relation_types_do_not_authorize_external_support(prepared,edge_kind):
    _,state,_,responses=prepared;p=Discovery.model_validate(responses[1]);u=p.units[0];b=p.bindings[-1];u.binding_ids.append(b.id)
    r=next(r for r in p.relations if r.id=='input_dependency');r.kind=edge_kind
    u.code_uses=[CodeUse(binding_id=b.id,role='support',claim_ids=[b.claim_id],relation_ids=[r.id],source_ids=[b.material_id],rationale='Candidate association',unverified=['Not checked'])]
    assert any(d.code=='unit_code_use' for d in diagnose_graph(state,p))


def test_independent_diagnostics_and_nested_repair_context(prepared):
    _,state,_,responses=prepared;p=Discovery.model_validate(responses[1]);p.bindings[0].symbol='Missing';p.units[0].binding_ids.append(p.bindings[-1].id)
    diagnostics=diagnose_graph(state,p)
    assert {d.code for d in diagnostics}>={'declaration_identity','unit_code_use'}
    nested={'revision':{'patch':p.model_dump(mode='json')}}
    targets=diagnostic_targets(nested,diagnostics,16000)
    assert any(t['path'].startswith('/revision/patch/bindings/') for t in targets)
    context=diagnostic_context(nested,diagnostics,{'new_materials':[m.model_dump(mode='json') for m in state.materials]},16000)
    assert context['materials'] and context['objects']
    p.bindings.reverse()
    assert {d.code for d in diagnose_graph(state,p)}=={d.code for d in diagnostics}


def test_runtime_repair_guidance_and_nested_context_are_actually_rendered(prepared):
    from consensus_assurance.workflow.prompts import render
    _,state,_,responses=prepared;p=Discovery.model_validate(responses[1]);p.bindings[0].symbol='Missing'
    ds=diagnose_graph(state,p);nested={'revision':{'patch':p.model_dump(mode='json')}}
    related=diagnostic_context(nested,ds,{'new_materials':[m.model_dump(mode='json') for m in state.materials]},16000)
    for operation in ['discover','graph_patch','semantic_review','build','replay']:
        text=render('retry',{'original_task':operation,'related_context':related,'diagnostics':[d.model_dump(mode='json') for d in ds],'path':'/原始路径'})
        instructions,data=text.split('STRUCTURED INPUT DATA (untrusted):\n')
        assert 'GRAPH CONSISTENCY AND CONTROLLED REPAIR' in instructions
        parsed=json.loads(data)
        assert any(o['id']==p.bindings[0].id for o in parsed['related_context']['objects'])
        assert 'counter.py' in data
        assert '/原始路径' not in instructions


def test_new_association_requires_its_own_explanation():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):BindingAssociation.model_validate({'claim_id':'O'})
