"""Metamorphic declaration ownership under different physical reading partitions."""
from pathlib import Path
import json
import pytest
from consensus_assurance.core.types import Material,Analysis
from consensus_assurance.core.proposals import BindingDraft
from consensus_assurance.workflow.locations import locate




def test_contiguous_prefix_can_prove_owner_without_claiming_complete_end():
    text='func (x *State) Handle(\n v int,\n) {\n f := func() { println("}") }\n f()\n'
    def source(id,a,z,version='same'):
        return Material(id=id,file='state.go',start_line=a,end_line=z,text='\n'.join(text.splitlines()[a-1:z]),content_digest=version,kind='code_observation')
    b=BindingDraft(id='b',claim_id='o',material_id='body',symbol='Handle',start_line=5,end_line=5,anchor={'material_id':'head','symbol':'Handle','start_line':1,'end_line':3,'kind':'declaration'},description='A real internal statement',pending=[])
    assert locate(b,{'head':source('head',1,3),'body':source('body',4,5)})[0]
    assert not locate(b,{'head':source('head',1,3),'body':source('body',5,5)})[0]
    assert not locate(b,{'head':source('head',1,3),'body':source('body',4,5,'different')})[0]


@pytest.mark.parametrize('cuts', [[(1,8)],[(1,2),(3,5),(6,8)],[(1,5),(4,8)]])
def test_multiline_signature_and_receiver_identity_survive_read_partition(cuts):
    text='func (x *A) Handle(\n  v int,\n) {\n println(v)\n}\nfunc (x *B) Handle() {\n println(2)\n}'
    materials={str(i):Material(id=str(i),file='state.go',start_line=a,end_line=z,text='\n'.join(text.splitlines()[a-1:z]),content_digest='version',kind='code_observation') for i,(a,z) in enumerate(cuts)}
    body=next(m for m in materials.values() if m.start_line<=4<=m.end_line)
    head=next(m for m in materials.values() if m.start_line==1)
    b=BindingDraft(id='b',claim_id='o',material_id=body.id,symbol='Handle',start_line=4,end_line=4,anchor={'material_id':head.id,'symbol':'Handle','start_line':1,'end_line':3,'kind':'declaration'},description='Only the first receiver is intended',pending=[])
    anchor,error=locate(b,materials);assert anchor,error
    assert anchor['start_line']==1 and anchor['boundary_complete']
    b.anchor.start_line=6;b.anchor.end_line=6
    assert not locate(b,materials)[0]


def test_comment_name_does_not_create_identity_and_interface_is_distinct():
    m=Material(id='code',file='state.go',start_line=1,end_line=5,content_digest='v',kind='code_observation',text='// func Fake() {\ntype Store interface {\n Save(\n  value int) error\n}')
    b=BindingDraft(id='b',claim_id='o',material_id=m.id,symbol='Fake',start_line=1,end_line=1,description='Comment is not code',pending=[])
    assert not locate(b,{m.id:m})[0]
    b.symbol='Store';b.start_line=2;b.end_line=5
    assert locate(b,{m.id:m})[0]




def test_prefix_ending_inside_raw_string_cannot_fabricate_function_end():
    from consensus_assurance.workflow.locations import declarations
    m=Material(id='prefix',file='state.go',start_line=1,end_line=4,kind='code_observation',content_digest='v',text='func Handle() {\n value := `raw\n } fake boundary\n still inside literal')
    definition=next(d for d in declarations(m) if d['symbol']=='Handle' and d['kind']=='declaration')
    assert definition['end'] is None and not definition['closed']
