import pytest
from consensus_assurance.core.types import Material, SourceAnchor
from consensus_assurance.workflow.locations import locate


@pytest.mark.parametrize('return_type',['interface{}','struct{ Value int }'])
def test_go_accessor_return_type_braces_do_not_hide_actual_body(return_type):
    from consensus_assurance.core.types import Material
    from consensus_assurance.core.types import SourceAnchor
    from consensus_assurance.workflow.locations import locate
    source='func (x *Result) Response() '+return_type+' {\n    return x.response\n}\n'
    material=Material(id='actual',file='future.go',start_line=1,end_line=3,text=source.rstrip('\n'),content_digest='synthetic',kind='code_observation')
    b=SourceAnchor(material_id='actual', symbol='Response', start_line=1, end_line=3)
    anchor,error=locate(b,{'actual':material})
    assert anchor and anchor['start_line']==1,error


def test_go_named_slice_groups_only_contiguous_matching_receiver_methods():
    from consensus_assurance.core.types import Material
    from consensus_assurance.workflow.locations import declarations
    text='type Scores []int\n\nfunc (s Scores) Len() int { return len(s) }\nfunc other() {}\nfunc (s Scores) Less(i, j int) bool { return s[i] < s[j] }'
    m=Material(id='source',file='sort.go',start_line=1,end_line=5,text=text,content_digest='synthetic',kind='code_observation')
    d=next(d for d in declarations(m) if d['symbol']=='Scores' and d['kind']=='declaration')
    assert d['start']==1 and d['end']==3
