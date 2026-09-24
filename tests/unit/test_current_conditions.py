import json
import pytest
from consensus_assurance.core.types import Analysis
from consensus_assurance.core.proposals import ReviewReply,ConditionDisposition
from consensus_assurance.core.diagnostics import DiagnosticError
from consensus_assurance.workflow.repair_policy import classify_conditions,condition_records


@pytest.mark.parametrize('shape,code',[('missing','condition_missing'),('extra','condition_extra'),('duplicate','condition_duplicate')])
def test_condition_reference_diagnostics_are_specific_and_do_not_erase_judgment(prepared,shape,code):
    _,state,_,_=prepared;id=state.materials[0].id
    records=condition_records(['Storage durability has not been inspected'],'issue-version-1',[id],'o',1)
    item=ConditionDisposition(condition_id=records[0]['id'],applies_to='independent_scope',rationale='This caller-location question does not establish storage behavior',source_ids=[id])
    dispositions=[] if shape=='missing' else [item,item] if shape=='duplicate' else [item,item.model_copy(update={'condition_id':'wrong'})]
    before=state.model_dump()
    with pytest.raises(DiagnosticError) as caught:
        classify_conditions(state,[r['text'] for r in records],dispositions,[id],records=records,object_ids=['o'])
    d=caught.value.diagnostics[0]
    assert d.code==code and d.details[shape] and d.allowed==['representation']
    assert state.model_dump()==before
    assert classify_conditions(state,[r['text'] for r in records],[item],[id],records=records)==[item]
