from consensus_assurance.workflow.history import import_record
import json
import pytest
from consensus_assurance.core.types import Analysis,InquiryTask
from consensus_assurance.core.proposals import ReviewReply,ConditionDisposition
from consensus_assurance.core.diagnostics import DiagnosticError
from consensus_assurance.workflow.repair_policy import classify_conditions,condition_records,validate_representation
from consensus_assurance.workflow.output_repair import diagnostic_context,diagnostic_targets,all_materials
from consensus_assurance.workflow.reviews import validate_resolutions
from test_worksets import ARCHIVE


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


def test_archived_current_conditions_reach_the_actual_repair_context():
    state=Analysis.model_validate(__import__("consensus_assurance.workflow.history",fromlist=["import_record"]).import_record(json.loads((ARCHIVE/'state.json').read_text())))
    folder=ARCHIVE/'agent/68dd6b52f1bb4ec18cae6428a2ef75f0-semantic_review'
    raw=json.loads((folder/'decoded-response.json').read_text())
    context=json.loads((folder/'prompt.txt').read_text().split('STRUCTURED INPUT DATA (untrusted):\n')[1])
    task=InquiryTask.model_validate(import_record(context['task']));task.material_ids=[m['id'] for m in all_materials(context)]
    reply=ReviewReply.model_validate(import_record(raw))
    with pytest.raises(DiagnosticError) as caught:validate_resolutions(state,task,reply)
    d=caught.value.diagnostics[0]
    assert d.code in {'condition_missing','condition_extra','condition_duplicate'}
    assert d.details['current_items'] and d.details['issue']['id']
    targets=diagnostic_targets(raw,[d],16000)
    assert targets and 'condition_dispositions' in targets[0]['path']
    repaired_context=diagnostic_context(raw,[d],context,16000)
    problem=next(o['current_condition_problem'] for o in repaired_context['objects'] if 'current_condition_problem' in o)
    assert problem['expected_conditions']==d.details['expected_conditions']
    assert problem['current_items']==d.details['current_items']
    assert json.loads((folder/'decoded-response.json').read_text())==raw


def test_metadata_correction_keeps_the_negative_substance():
    before={'items':[{'target_id':'binding','aspect':'checker_correspondence','status':'disputed','source_ids':['code'],'limitations':['Unresolved caller'],'rationale':'Unknown consumer contract'}]}
    after=json.loads(json.dumps(before));after['items'][0]['aspect']='decomposition'
    validate_representation(before,after,[{'path':'/items/0'}],{})
    after['items'][0]['status']='no_issue_found'
    with pytest.raises(ValueError):validate_representation(before,after,[{'path':'/items/0'}],{})


def test_read_followup_keeps_only_affected_target_aspect_and_issue(tmp_path,prepared):
    from consensus_assurance.workflow.inquiry import enqueue,apply_task_response
    from consensus_assurance.core.types import CheckRun
    from test_graph_mutations import controller
    _,state,_,_=prepared;e=controller(tmp_path,state);u=state.units[0]
    t=enqueue(state,'review','Inspect selected objects','initial',target_ids=u.obligation_ids+u.obligation_ids,unit_id=u.id)
    c=next(c for c in state.claims if c.id==u.obligation_ids[0]);t.material_ids=c.source_ids
    r=ReviewReply(items=[{'target_id':c.id,'aspect':'decomposition','status':'needs_reading','source_ids':c.source_ids,'limitations':['Producer bound is not yet explained'],'rationale':'Inspect this producer only' + "\n" + 'The caller may establish the bound' + "\n" + 'An unconstrained input changes the behavior'}],
        requests=[{'file':'limits.py','start_line':1,'end_line':2,'reason':'Locate the real producer'}],limitations=[])
    check=CheckRun(action='agent',cwd=str(tmp_path),snapshot_id=state.snapshot.id,origin='mock')
    apply_task_response(e,t.id,r,check)
    follow=next(x for x in state.inquiry_tasks if x.trigger==t.id+':followup')
    assert follow.target_ids==[c.id] and follow.requested_aspects=={c.id:['decomposition']}
    assert follow.resolution_issue_ids==[state.review_issues[-1].id]
