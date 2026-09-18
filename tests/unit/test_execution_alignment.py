import json
"""Question-directed execution regressions, independent of target answer keys."""
from types import SimpleNamespace
from consensus_assurance.core.types import AuditQuestion, ConstraintSource
from consensus_assurance.workflow import inquiry
from consensus_assurance.workflow.artifacts import validate_bundle
from consensus_assurance.core.proposals import GraphDraft
from test_graph_mutations import controller


def test_typed_question_selects_direct_route(prepared):
    from consensus_assurance.workflow.direct_checks import route
    _,state,_,_=prepared
    unit=state.units[0]
    unit.audit_question=AuditQuestion(question='Check actual bounded return',importance='Service result',source_ids=state.claims[0].source_ids,
        trigger_rationale='Call actual implementation, correlate returned value and compare independent oracle',event_paths=['admit -> return -> observe'],
        disposition='ready_for_check',preferred_check='direct_test')
    assert route(unit)=='direct_check'


def test_thin_overview_does_not_enqueue_generic_exploration(tmp_path,prepared):
    _,state,_,responses=prepared;e=controller(tmp_path,state)
    proposal=GraphDraft.model_validate(responses[1])
    inquiry.enqueue(e.state,'spec_refine','Read selected dependency','initial_reading',requests=[])
    assert not any(t.trigger=='initial_breadth' or t.trigger.startswith(('responsibility:','handoff:')) for t in state.inquiry_tasks)


def test_binding_review_contains_selected_current_unit(tmp_path,prepared):
    _,state,_,_=prepared;e=controller(tmp_path,state);unit=state.units[0];unit.version=2
    task=inquiry.enqueue(state,'review','Selected association','explicit',target_ids=unit.binding_ids,unit_id=unit.id)
    packet=inquiry.task_context(e,task)
    assert packet['selected_unit']==unit.model_dump(mode='json')


def test_constraint_cites_material_and_selected_binding(prepared):
    from consensus_assurance.plugins.implementations.toy.adapter import ToyImplementation
    _,state,bundle,_=prepared;unit=state.units[0];binding=state.bindings[0]
    bundle.constraints=[ConstraintSource(constraint='Actual step',source_kind='code_observation',source_ids=[binding.material_id],binding_ids=[binding.id],justification='Actual transition source')]
    validate_bundle(state,unit,bundle,ToyImplementation())


def test_selected_exploration_dependency_uses_depth(tmp_path,prepared):
    _,state,_,_=prepared;e=controller(tmp_path,state);unit=state.units[0]
    task=inquiry.enqueue(state,'spec_refine','Selected producer discriminator','dependency',unit_id=unit.id)
    assert inquiry.read_purpose(task)=='depth'


def test_default_method_only_comes_from_manifest():
    from consensus_assurance.workflow.prompts import render,loaded_resources
    text=render('discover',{})
    assert 'APPLICABLE INQUIRY GUIDANCE' not in text
    assert 'system.md' in loaded_resources('discover',{})['paths']
    assert 'tasks/discover.md' in loaded_resources('discover',{})['paths']
    assert 'APPLICABLE INQUIRY GUIDANCE' in render('discover',{},'Explicit extra target guidance')


def test_workspace_delta_reconstructs_inputs(tmp_path):
    from consensus_assurance.adapters.storage.workspace_delta import save_delta,restore
    import shutil
    source=tmp_path/'source';source.mkdir();(source/'target.py').write_text('value = 1\n')
    (source/'old.txt').write_text('removed by execution')
    workspace=tmp_path/'experiment/workspace';shutil.copytree(source,workspace)
    (workspace/'generated.py').write_text('from target import value\n')
    (workspace/'old.txt').unlink()
    manifest=save_delta(source,workspace,'fixture')
    restored=restore(source,manifest,tmp_path/'reconstructed')
    assert (restored/'target.py').read_bytes()==(source/'target.py').read_bytes()
    assert (restored/'generated.py').read_bytes()==(workspace/'generated.py').read_bytes()
    assert not (restored/'old.txt').exists()
    assert not (manifest.parent/'files/target.py').exists()


def test_constraint_repair_supplies_graph_objects_not_source_requests(prepared):
    import pytest
    from consensus_assurance.plugins.implementations.toy.adapter import ToyImplementation
    from consensus_assurance.workflow.output_repair import diagnostic_context,diagnostic_targets
    _,state,bundle,_=prepared;unit=state.units[0]
    bundle.constraints[0].binding_ids=[]
    with pytest.raises(ValueError) as caught:validate_bundle(state,unit,bundle,ToyImplementation())
    diagnostic=caught.value.diagnostics[0]
    assert diagnostic.allowed==['representation']
    assert diagnostic.details['selected_bindings'][0]['associations']
    targets=diagnostic_targets({'bundle':bundle.model_dump(mode='json')},[diagnostic],16000)
    assert {t['path'] for t in targets}=={'/bundle/constraints/0/source_ids','/bundle/constraints/0/binding_ids'}
    packet=diagnostic_context({'bundle':bundle.model_dump(mode='json')},[diagnostic],
        {'unit':unit.model_dump(mode='json'),'bindings':[b.model_dump(mode='json') for b in state.bindings]},16000)
    assert set(unit.binding_ids)<={o['id'] for o in packet['objects']}
    from consensus_assurance.workflow.output_repair import apply_replacements,OutputRepair,Replacement
    with pytest.raises(ValueError):
        apply_replacements({'bundle':bundle.model_dump(mode='json')},targets,OutputRepair(replacements=[Replacement(path='/bundle/constraints/0/source_kind',value_json='"model_assumption"')],rationale='Not an authorized citation repair'))
    bundle.constraints[0].binding_ids=['not_selected']
    with pytest.raises(ValueError):validate_bundle(state,unit,bundle,ToyImplementation())


def test_selected_read_can_use_protected_depth(tmp_path,prepared):
    from consensus_assurance.workflow.materials import plan_read,material_usage
    from consensus_assurance.adapters.storage.snapshot import capture
    from consensus_assurance.core.types import ReadRequest
    _,state,_,_=prepared;e=controller(tmp_path,state);repo=tmp_path/'material-repo';repo.mkdir()
    (repo/'consumer.py').write_text('value = 1\n'*15)
    state.snapshot=capture(repo)
    used=material_usage(state)['unique_chars'];e.config.budget.material_chars=used+180
    e.config.budget.material_chunks=100
    q=ReadRequest(file='consumer.py',start_line=1,end_line=15,reason='Selected consumer establishes the discriminator')
    broad,_=plan_read(state,repo,[q],e.config.budget,purpose='breadth')
    deep,_=plan_read(state,repo,[q],e.config.budget,purpose='depth')
    assert broad.status=='deferred' and deep.status=='complete'
    assert e.config.budget.material_chars==used+180


def test_core_semantics_review_without_independent_binding_certificate(tmp_path,prepared):
    from consensus_assurance.workflow.reviews import readiness
    from consensus_assurance.workflow.review_contract import target_contract
    from consensus_assurance.core.types import SemanticReview,SemanticCheck,ReviewIssue
    _,s,_,_=prepared;e=controller(tmp_path,s);u=s.units[0]
    inquiry.review_unit(e,u,'explicit_question_review')
    targets={id for t in s.inquiry_tasks for id in t.target_ids}
    assert targets==set(u.obligation_ids+u.obligation_ids+[u.id])
    for obj in s.claims+s.units:
        if obj.id not in targets:continue
        contract=target_contract(s,obj)
        s.semantic_reviews.append(SemanticReview(task_id='fixture',check_id='fixture',target_versions={obj.id:obj.version},context_dependencies={obj.id:contract},material_ids=contract['required_material_ids'],
            items=[SemanticCheck(target_id=obj.id,aspect=a,status='no_issue_found',source_ids=contract['required_material_ids'],rationale='Scoped source basis' + "\n" + 'Alternative ownership' + "\n" + 'A producer may not establish this fact') for a in contract['required_aspects']],origin='mock'))
    assert readiness(s,u)['status']=='reviewed'
    s.review_issues.append(ReviewIssue(review_id='explicit',target_id=u.binding_ids[0],target_version=1,aspect='decomposition',source_ids=s.claims[0].source_ids,explanation='Association may hide an alternate branch',disposition='investigation',reason='Explicit dispute'))
    assert readiness(s,u)['status']!='reviewed'
    inquiry.review_unit(e,u,'explicit_dispute')
    assert any(u.binding_ids[0] in t.target_ids for t in s.inquiry_tasks)






def test_experiment_archives_inputs_separately_from_runtime_outputs(tmp_path):
    import sys,json,shutil
    from consensus_assurance.adapters.runners.experiment import run_experiment
    from consensus_assurance.adapters.runners.process import ProcessRunner
    from consensus_assurance.adapters.storage.workspace_delta import restore
    source=tmp_path/'source';source.mkdir();(source/'counter.py').write_text('value = 7\n')
    workspace=tmp_path/'experiments/one/workspace';shutil.copytree(source,workspace)
    (workspace/'harness.py').write_text("from counter import value\nfrom pathlib import Path\nPath('produced.txt').write_text(str(value))\n")
    check=run_experiment(ProcessRunner(tmp_path),[sys.executable,'harness.py'],workspace,'fixture',10,'workspace')
    before=workspace.parent/'workspace-delta/manifest.json';after=workspace.parent/'workspace-outcome/manifest.json'
    assert check.exit_code==0 and str(before) in check.artifacts and str(after) in check.artifacts
    assert 'produced.txt' not in json.loads(before.read_text())['changed_files']
    assert 'produced.txt' in json.loads(after.read_text())['changed_files']
    reconstructed=restore(source,before,tmp_path/'inputs')
    assert (reconstructed/'harness.py').read_bytes()==(workspace/'harness.py').read_bytes()
    assert not (reconstructed/'produced.txt').exists()
