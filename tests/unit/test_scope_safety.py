"""Scope refinement preserves semantics, full graph checks and historical applicability."""
import pytest
from regression_support import dependency
from consensus_assurance.workflow.graph import apply_patch
from consensus_assurance.core.types import AuditQuestion


def test_new_binding_still_requires_real_symbol_and_association(dependency_prepared):
    state,patch,_=dependency(dependency_prepared);patch.bindings[0].symbol='imaginary'
    before=state.model_dump()
    with pytest.raises(ValueError):apply_patch(state,patch,semantic=True)
    assert state.model_dump()==before


@pytest.mark.parametrize('return_type',['interface{}','struct{ Value int }'])
def test_go_accessor_return_type_braces_do_not_hide_actual_body(return_type):
    from consensus_assurance.core.types import Material
    from consensus_assurance.core.proposals import BindingDraft
    from consensus_assurance.workflow.locations import locate
    source='func (x *Result) Response() '+return_type+' {\n    return x.response\n}\n'
    material=Material(id='actual',file='future.go',start_line=1,end_line=3,text=source.rstrip('\n'),content_digest='synthetic',kind='code_observation')
    b=BindingDraft(id='accessor',associations=[dict(claim_id='O',source_ids=['actual'],rationale='Selected fixture operation')],material_id='actual',symbol='Response',start_line=1,end_line=3,description='Accessor',pending=[])
    anchor,error=locate(b,{'actual':material})
    assert anchor and anchor['start_line']==1,error


def test_go_named_slice_groups_only_contiguous_matching_receiver_methods():
    from consensus_assurance.core.types import Material
    from consensus_assurance.workflow.locations import declarations
    text='type Scores []int\n\nfunc (s Scores) Len() int { return len(s) }\nfunc other() {}\nfunc (s Scores) Less(i, j int) bool { return s[i] < s[j] }'
    m=Material(id='source',file='sort.go',start_line=1,end_line=5,text=text,content_digest='synthetic',kind='code_observation')
    d=next(d for d in declarations(m) if d['symbol']=='Scores' and d['kind']=='declaration')
    assert d['start']==1 and d['end']==3
