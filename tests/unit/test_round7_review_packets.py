"""Responses derive required aspects solely from the rendered task packet."""
import json
import pytest
from consensus_assurance.core.proposals import ReviewReply
from consensus_assurance.core.types import InquiryTask
from consensus_assurance.workflow.inquiry import task_context,validate_review,enqueue
from consensus_assurance.workflow.task_packet import prepare,receipt
from consensus_assurance.workflow.prompts import render
from consensus_assurance.workflow.reviews import readiness
from consensus_assurance.workflow.output_repair import apply_replacements,diagnostic_targets,OutputRepair
from consensus_assurance.workflow.repair_policy import validate_representation
from consensus_assurance.core.diagnostics import DiagnosticError
from test_round6_boundaries import controller


def respond(packet):
    items=[]
    for c in packet['review_contract']:
        assert c['object_type'] and c['version'] and c['questions']
        for aspect in c['required_aspects']:
            assert c['questions'][aspect]
            items.append({'target_id':c['target_id'],'aspect':aspect,'status':'no_issue_found','source_ids':c['required_material_ids'],
                'explanation':'The actual supplied source supports this scoped synthetic responsibility',
                'alternatives':'An alternative mechanism can satisfy the same obligation',
                'counterexample_reasoning':'A failure would require the dependency to be broken under allowed conditions','limitations':[]})
    return ReviewReply(items=items,limitations=[])


def packet_for(e,ids):
    task=enqueue(e.state,'review','Check supplied objects','packet-test',target_ids=ids)
    e.state.active_inquiry_id=task.id
    packet,t=prepare(e,'semantic_review',task_context(e,task))
    prompt=render('semantic_review',packet)
    receipt(e,'semantic_review',packet,prompt,ReviewReply,t)
    return task,json.loads(prompt.split('STRUCTURED INPUT DATA (untrusted):\n')[1])


def test_every_actual_object_type_uses_packet_policy(tmp_path,prepared):
    from consensus_assurance.workflow.artifacts import save_bundle
    repo,state,bundle,_=prepared;e=controller(tmp_path,state)
    goal=state.claims[0].model_copy(deep=True);goal.id='environment';goal.kind='assumption';state.claims.append(goal)
    model=save_bundle(e.root,state,state.units[0],bundle,e.implementation)
    seen=set()
    for obj in [*state.claims,*state.bindings,*state.relations,*state.units,model]:
        task,packet=packet_for(e,[obj.id]);reply=respond(packet)
        validate_review(state,task,reply)
        seen.add(packet['review_contract'][0]['object_type'])
        assert not packet['catalogue'] and packet['file_lookup']
        assert len([o for key in ('target_objects','claims','bindings','units','relations') for o in packet.get(key,[]) if o['id']==obj.id])==1
    assert seen=={'goal','obligation','assumption','binding','relation','unit','model'}


def test_missing_binding_aspect_appends_without_erasing_dispute(tmp_path,prepared):
    _,state,_,_=prepared;e=controller(tmp_path,state);task,packet=packet_for(e,[state.bindings[0].id])
    good=respond(packet);bad=good.model_copy(deep=True)
    bad.items[0].aspect='applicability';bad.items[0].status='disputed';bad.items[0].limitations=['Responsibility remains uncertain']
    with pytest.raises(DiagnosticError) as caught:validate_review(state,task,bad)
    targets=diagnostic_targets(bad.model_dump(mode='json'),caught.value.diagnostics,16000)
    repair=OutputRepair(replacements=[{'path':'/items/-','value_json':good.items[0].model_dump_json()}],rationale='Add the missing substantive decomposition; retain the original dispute')
    fixed=apply_replacements(bad.model_dump(mode='json'),targets,repair)
    validate_representation(bad.model_dump(mode='json'),fixed,targets,{})
    validate_review(state,task,ReviewReply.model_validate(fixed))
    assert fixed['items'][0]['status']=='disputed'
    removed={**fixed,'items':[fixed['items'][1]]}
    with pytest.raises(ValueError,match='negative'):validate_representation(bad.model_dump(mode='json'),removed,targets,{})


def test_task_attachment_does_not_leak_and_unseen_source_rejected(tmp_path,prepared):
    from consensus_assurance.core.types import Material
    _,state,_,_=prepared;e=controller(tmp_path,state)
    other=Material(id='unrelated',file='unrelated.txt',start_line=1,end_line=1,text='Unrelated private task context',kind='document_statement',content_digest='synthetic')
    state.materials.append(other);state.attached_material_ids.append(other.id);state.task_attachments['inquiry:other']=[other.id]
    task,packet=packet_for(e,[state.bindings[0].id])
    assert other.id not in [m['id'] for m in packet['materials']]
    reply=respond(packet);reply.items[0].source_ids.append(other.id)
    with pytest.raises(DiagnosticError) as caught:validate_review(state,task,reply)
    assert caught.value.diagnostics[0].code=='review_unavailable_source'


def test_relation_packet_includes_both_endpoint_sources(tmp_path,prepared):
    _,state,_,_=prepared;e=controller(tmp_path,state);edge=state.relations[0]
    task,packet=packet_for(e,[edge.id]);contract=packet['review_contract'][0]
    assert edge.source in contract['dependency_versions'] and edge.target in contract['dependency_versions']
    assert set(contract['required_material_ids'])<={m['id'] for m in packet['materials']}


def test_receipt_counts_actual_prompt_and_prepared_schema_files(tmp_path,prepared):
    from pathlib import Path
    _,state,_,_=prepared;e=controller(tmp_path,state);task,packet=packet_for(e,[state.bindings[0].id])
    r=state.packet_receipts[-1];prompt=render('semantic_review',packet)
    assert r['prompt_chars']==len(prompt) and r['prompt_bytes']==len(prompt.encode())
    assert r['wire_schema_chars']==len((e.root/'packets'/(r['id']+'.schema.json')).read_text())
    assert r['material_ids']==task.material_ids
