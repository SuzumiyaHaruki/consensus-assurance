import json
import pytest
from consensus_assurance.core.types import Material,BindingAssociation
from consensus_assurance.core.proposals import BindingDraft,GraphDraft,GraphPatch
from consensus_assurance.workflow.locations import locate,declarations
from consensus_assurance.workflow.graph import apply_graph,apply_patch
from consensus_assurance.workflow.graph_diagnostics import diagnose_graph
from consensus_assurance.workflow.associations import relevant_use
from consensus_assurance.workflow.output_repair import diagnostic_targets,diagnostic_context


def material(text,start=1,file='sample.go'):
    return Material(id=f'{file}:{start}:{start+len(text.splitlines())-1}',file=file,start_line=start,end_line=start+len(text.splitlines())-1,kind='code_observation',text=text,content_digest='synthetic-source')


def binding(m,symbol='accept',start=2,end=2,anchor=None):
    return BindingDraft(id='code',associations=[dict(claim_id='O',source_ids=[m.id],rationale='Selected fixture operation')],material_id=m.id,symbol=symbol,start_line=start,end_line=end,description='Observed operation body',pending=[],anchor=anchor)




def test_declaration_outside_read_material_requires_reading():
    partial=material('  value++\n}\n',2);b=binding(partial)
    assert locate(b,{partial.id:partial})[0] is None
    complete=material('func accept() {\n  value++\n}\n')
    assert locate(b,{partial.id:partial,complete.id:complete})[0]['material_id']==complete.id









def test_multiple_obligations_share_one_binding_with_sourced_associations(prepared):
    _,state,_,responses=prepared;p=GraphDraft.model_validate(responses[1]);b=p.bindings[0]
    b.associations.append(BindingAssociation(claim_id=p.claims[-1].id,source_ids=[b.material_id],rationale='The same entry also consumes the producer condition'))
    apply_graph(state,p)
    assert len(state.bindings[0].associations)==2



def test_independent_diagnostics_and_nested_repair_context(prepared):
    _,state,_,responses=prepared;p=GraphDraft.model_validate(responses[1]);p.bindings[0].symbol='Missing';p.units[0].binding_ids.append(p.bindings[-1].id)
    diagnostics=diagnose_graph(state,p)
    assert {d.code for d in diagnostics}>={'declaration_identity','unit_dependency'}
    nested={'revision':{'patch':p.model_dump(mode='json')}}
    targets=diagnostic_targets(nested,diagnostics,16000)
    assert any(t['path'].startswith('/revision/patch/bindings/') for t in targets)
    context=diagnostic_context(nested,diagnostics,{'new_materials':[m.model_dump(mode='json') for m in state.materials]},16000)
    assert context['materials'] and context['objects']
    p.bindings.reverse()
    assert {d.code for d in diagnose_graph(state,p)}=={d.code for d in diagnostics}


def test_runtime_repair_guidance_and_nested_context_are_actually_rendered(prepared):
    from consensus_assurance.workflow.prompts import render
    _,state,_,responses=prepared;p=GraphDraft.model_validate(responses[1]);p.bindings[0].symbol='Missing'
    ds=diagnose_graph(state,p);nested={'revision':{'patch':p.model_dump(mode='json')}}
    related=diagnostic_context(nested,ds,{'new_materials':[m.model_dump(mode='json') for m in state.materials]},16000)
    for operation in ['discover','graph_patch','semantic_review','build','replay']:
        text=render('retry',{'original_task':operation,'related_context':related,'diagnostics':[d.model_dump(mode='json') for d in ds],'path':'/原始路径'})
        instructions,data=text.split('STRUCTURED INPUT DATA (untrusted):\n')
        assert 'Candidate consistency and controlled repair' in instructions
        parsed=json.loads(data)
        assert any(o['id']==p.bindings[0].id for o in parsed['related_context']['objects'])
        assert 'counter.py' in data
        assert '/原始路径' not in instructions


def test_new_association_requires_its_own_explanation():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):BindingAssociation.model_validate({'claim_id':'O'})


def test_qualified_interface_member_requires_actual_owner_and_anchor():
    from consensus_assurance.workflow.locations import location_context
    m=material('type First interface {\n Response() int\n}\ntype Second interface {\n Response() int\n}\n')
    b=binding(m,'First.Response',2,2)
    anchor,error=locate(b,{m.id:m})
    assert not error and anchor['symbol']=='First.Response' and anchor['boundary_complete']
    assert [d['start'] for d in location_context(b,{m.id:m})['candidates']]==[2]
    assert locate(binding(m,'Second.Response',2,2),{m.id:m})[0] is None
    assert locate(binding(m,'Unknown.Response',2,2),{m.id:m})[0] is None
    b.anchor={**anchor,'start_line':1}
    assert locate(b,{m.id:m})[0] is None


def test_member_without_acquired_owner_is_not_resolved_by_suffix():
    m=material(' Response() int\n}\n',2)
    assert locate(binding(m,'First.Response',2,2),{m.id:m})[0] is None


def test_declaration_diagnostic_supplies_actual_file_length(prepared):
    _,state,_,responses=prepared
    p=GraphDraft.model_validate(responses[1]);b=p.bindings[0];b.symbol='Unknown'
    m=next(m for m in state.materials if m.id==b.material_id)
    state.file_index[m.file]={'file':m.file,'lines':m.end_line,'content_digest':m.content_digest}
    d=next(d for d in diagnose_graph(state,p) if b.id in d.object_ids)
    assert d.details['file_metadata']==state.file_index[m.file]


@pytest.mark.parametrize('receiver',['r *First','r First','r *First[T]','*First'])
def test_receiver_qualified_method_uses_declared_type(receiver):
    from consensus_assurance.workflow.locations import location_context
    m=material('func ('+receiver+') accept() {\n value++\n}\nfunc (s *Second) accept() {\n value--\n}\n')
    b=binding(m,'First.accept',2,2)
    anchor,error=locate(b,{m.id:m})
    assert not error and anchor['start_line']==1 and anchor['symbol']=='First.accept'
    assert [d['start'] for d in location_context(b,{m.id:m})['candidates']]==[1]
    assert locate(binding(m,'Second.accept',2,2),{m.id:m})[0] is None
    assert locate(binding(m,'r.accept',2,2),{m.id:m})[0] is None
    assert locate(binding(m,'First.accept',5,5),{m.id:m})[0] is None


def test_local_closure_does_not_inherit_surrounding_receiver():
    m=material('func (r *First) accept() {\n work := func() {\n  value++\n }\n}\n')
    assert locate(binding(m,'First.work',3,3),{m.id:m})[0] is None
    assert locate(binding(m,'work',3,3),{m.id:m})[0] is not None


def test_declaration_index_retains_gaps_and_open_boundaries():
    from consensus_assurance.workflow.locations import declaration_index
    first=material('func (r *Service) save() {\n value++\n',10)
    second=material(' value--\n}\n',20)
    index=declaration_index([first,second])
    assert len(index)==1
    d=index[0]['declarations'][0]
    assert d['symbol']=='Service.save' and d['start_line']==10
    assert d['end_line'] is None and d['known_end']==11 and not d['boundary_complete']
    assert index[0]['material_ids']==[first.id]


def test_anchor_correction_does_not_fix_cross_declaration_behavior():
    from consensus_assurance.workflow.locations import location_context
    from consensus_assurance.workflow.repair_policy import validate_representation
    m=material('func save() {\n value++\n}\nfunc discard() {\n value--\n}\n')
    b=binding(m,'save',2,5)
    assert not location_context(b,{m.id:m})['candidates'][0]['contains_behavior']
    original={'bindings':[b.model_dump(mode='json')]}
    b.anchor={'material_id':m.id,'symbol':'save','start_line':1,'end_line':1}
    with pytest.raises(ValueError,match='behavior containment'):
        validate_representation(original,{'bindings':[b.model_dump(mode='json')]},[{'path':'/bindings/0/anchor'}],{'materials':[m.model_dump(mode='json')]})
