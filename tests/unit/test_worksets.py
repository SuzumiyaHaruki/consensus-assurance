"""Current worksets must not scale with the audit archive or omit needed source."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from consensus_assurance.core.types import Analysis,SemanticReview,SemanticCheck,ReviewIssue
from consensus_assurance.core.config import Config
from consensus_assurance.adapters.runners.go_module import GoModuleBackend
from consensus_assurance.workflow.discovery import context
from consensus_assurance.workflow.task_packet import prepare,pool_sources
from consensus_assurance.workflow.prompts import render
from test_graph_mutations import controller



def test_mixed_history_projects_only_relevant_items_and_retains_counterevidence(tmp_path,prepared):
    _,s,_,_=prepared;e=controller(tmp_path,s);u=s.units[0];target=u.obligation_ids[0]
    def item(id,status,text):return SemanticCheck(target_id=id,aspect='applicability',status=status,source_ids=s.claims[0].source_ids,rationale=text + "\n" + 'Alternate mechanism possible' + "\n" + 'Actual evidence is required')
    before=len(json.dumps(context(e,u)))
    for n in range(50):
        s.semantic_reviews.append(SemanticReview(task_id='other',check_id='fixture',target_versions={target:1,'unrelated':1},material_ids=[],items=[item(target,'no_issue_found','Same scoped judgment'),item('unrelated','disputed','UNRELATED HISTORY '+str(n)+'x'*3000)],origin='mock'))
    packet=context(e,u)
    assert len(json.dumps(packet))-before<5000
    assert 'UNRELATED HISTORY' not in json.dumps(packet)
    negative=SemanticReview(task_id='negative',check_id='fixture',target_versions={target:1},material_ids=[],items=[item(target,'disputed','Unresolved counterevidence must survive')],origin='mock')
    s.semantic_reviews.append(negative)
    s.review_issues.append(ReviewIssue(review_id=negative.id,target_id=target,target_version=1,aspect='applicability',source_ids=s.claims[0].source_ids,explanation='Unresolved counterevidence must survive',disposition='blocked',reason='Current sourced dispute'))
    s.semantic_reviews.append(SemanticReview(task_id='positive',check_id='fixture',target_versions={target:1},material_ids=[],items=[item(target,'no_issue_found','A later positive claim')],origin='mock'))
    assert 'Unresolved counterevidence must survive' in json.dumps(context(e,u))


def test_review_reading_is_consumed_by_its_unit_but_not_an_unrelated_unit(tmp_path,prepared):
    from consensus_assurance.adapters.storage.snapshot import capture
    from consensus_assurance.workflow.inquiry import enqueue
    from consensus_assurance.workflow.task_packet import receipt
    from consensus_assurance.core.proposals import BuildReply
    import shutil
    repo,state,_,_=prepared
    (repo/'setup_detail.py').write_text('INITIAL_VALUE = 0\n')
    state.snapshot=capture(repo);e=controller(tmp_path,state);shutil.copytree(repo,e.root/'source')
    q={'file':'setup_detail.py','start_line':1,'end_line':1,'reason':'Actual assembly source'}
    e.read([q],plan_id='acquire-before-review')
    unit=e.state.units[0]
    assert not any(m['file']=='setup_detail.py' for m in e.context(unit)['materials'])
    task=enqueue(e.state,'review','Resolve assembly source','assembly',target_ids=[unit.id],unit_id=unit.id)
    e.state.active_inquiry_id=task.id
    e.read([q],plan_id='reattach-during-review')
    e.state.active_inquiry_id=None;e.state.active_unit_id=unit.id
    packet,_=prepare(e,'build',e.context(unit));packet=pool_sources(packet)
    sent=receipt(e,'build',packet,render('build',packet),BuildReply)
    assert 'setup_detail.py:1:1' in sent['material_ids'] and not sent['missing_required_material_ids']
    other=unit.model_copy(deep=True);other.id='independent';e.state.units.append(other)
    assert not any(m['file']=='setup_detail.py' for m in e.context(other)['materials'])


def test_deferred_wake_is_based_on_serializable_dependency_change(tmp_path,prepared):
    from consensus_assurance.workflow.inquiry import pause_unit,wake_changed
    repo,state,_,_=prepared
    from consensus_assurance.adapters.storage.snapshot import capture
    from consensus_assurance.workflow.materials import read_material
    from consensus_assurance.core.types import ReadRequest
    (repo/'setup_detail.py').write_text('START = 0\n');state.snapshot=capture(repo)
    state.materials.append(read_material(repo,state.snapshot,ReadRequest(file='setup_detail.py',start_line=1,end_line=1,reason='Cached but not attached')))
    e=controller(tmp_path,state);unit=state.units[0]
    state.active_unit_id=unit.id;state.next_action='build';unit.status='selected'
    pause_unit(e,'Cached necessary material not attached')
    e.state=Analysis.model_validate(__import__("consensus_assurance.workflow.history",fromlist=["import_record"]).import_record(json.loads(e.state.model_dump_json())))
    e.budget.state=e.state
    assert not wake_changed(e)
    id=e.state.materials[-1].id
    e.state.task_attachments['unit:'+unit.id]=[id]
    assert wake_changed(e)
    assert e.state.active_unit_id==unit.id and e.state.next_action=='build'
    pause_unit(e,'Still lacks a different dependency')
    assert not wake_changed(e)


def test_skill_routing_keeps_behavior_references_and_task_specific_repairs():
    from consensus_assurance.workflow.prompts import loaded_resources,manifest
    for task in ('build','F1','F3','technical','diagnose'):
        paths=loaded_resources(task,{})['paths']
        assert 'skills/consensus-analysis/references/behavior-facts.md' in paths
    assert 'skills/consensus-analysis/references/graph-repair.md' not in loaded_resources('build',{})['paths']
    assert 'activity-classes.md' in ' '.join(loaded_resources('discover',{})['paths'])
    for task in manifest()['tasks']:
        assert 'STRUCTURED INPUT DATA' in render(task,{'original_task':'build'} if task=='retry' else {})


def test_current_model_keeps_unresolved_predecessor_encoding_issue(tmp_path,prepared):
    from consensus_assurance.workflow.artifacts import save_bundle
    from consensus_assurance.adapters.runners.python import PythonBackend
    from consensus_assurance.core.types import ReviewIssue
    _,state,bundle,_=prepared;unit=state.units[0]
    first=save_bundle(tmp_path/'artifacts',state,unit,bundle,PythonBackend())
    second=save_bundle(tmp_path/'artifacts',state,unit,bundle,PythonBackend(),first,'Harness-only continuation')
    state.review_issues.append(ReviewIssue(review_id='old',target_id=first.id,target_version=first.version,aspect='checker_correspondence',model_id=first.id,
        source_ids=state.claims[1].source_ids,explanation='The previous checker may exclude legal completion',disposition='revision',reason='Needs attributed encoding investigation'))
    e=controller(tmp_path,state);state.active_model_id=second.id
    view=e.context(unit)['semantic_view']
    assert view['open_issues'][0]['target_id']==first.id
    assert 'exclude legal completion' in view['open_issues'][0]['explanation']
