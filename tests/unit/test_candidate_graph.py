import copy
import json
from pathlib import Path
import pytest
from consensus_assurance.core.config import Config
from consensus_assurance.core.proposals import (GraphDraft, GraphPatch, Comparison, EventRequirement, EventMonitor,
    ObservationMap, FieldProjection, Feedback)
from consensus_assurance.core.types import Grounding, Scope, CheckRun, ExecutionStatus, Calibration, Origin
from consensus_assurance.registry import assemble
from consensus_assurance.workflow.graph import apply_graph, apply_patch
from consensus_assurance.workflow.graph_diagnostics import validate_grounding
from consensus_assurance.workflow.artifacts import validate_tla
from consensus_assurance.workflow.observations import match_prerequisites, monitor_events
from consensus_assurance.workflow.materials import ReadingPlan, ReadRequest
from regression_support import add_reads
from consensus_assurance.adapters.storage.snapshot import capture
from consensus_assurance.adapters.agents.backend import strict_schema, wire_value
from consensus_assurance.adapters.verifiers.trace import project


def test_default_has_inquiry_without_property_list():
    config=Config()
    assert config.protocol=='none' and config.directed_question is None
    assert assemble(config)[3]==''
    assert assemble(Config(execution_backend='go_module'))[3]==''
    assert assemble(Config(protocol='raft'))[3]  # Explicit reference uses the same workflow.


def test_empty_discovery_is_admissible(prepared):
    _,state,_,_=prepared
    apply_graph(state,GraphDraft(conflicts=[],unexplored=['Producer'],gaps=['Contract unavailable']))
    assert not state.claims and not state.units and 'Contract unavailable' in state.gaps


def test_code_derived_responsibilities_are_candidates(prepared):
    _,state,_,responses=prepared
    graph=GraphDraft.model_validate(responses[1])
    c=graph.claims[1]
    c.source_ids=['counter.py:1:10','limits.py:1:2']
    c.grounding=Grounding(source_ids=c.source_ids,binding_ids=['step_binding','input_binding'],
        derivation='The consumer assumes a positive limit and the producer must establish that precondition',
        applicability='Serial calls in the fixture',unresolved=['No direct documented contract; inferred responsibility'])
    apply_graph(state,graph)
    assert state.claims[1].candidate
    assert state.claims[1].grounding.unresolved
    c.grounding.binding_ids=['step_binding']
    apply_graph(state,graph)
    assert state.claims[1].candidate
    c.grounding.binding_ids=[]
    with pytest.raises(ValueError,match='located implementation binding'): apply_graph(state,graph)







def test_patch_keeps_object_versions_and_unrelated_claims(prepared):
    _,state,_,responses=prepared
    current=state.claims[1]
    changed=GraphDraft.model_validate(responses[1]).claims[1]
    changed.description='Refined responsibility under the same documented configuration'
    patch=GraphPatch(claims=[changed],expected_versions={changed.id:1},rationale='New interpretation')
    with pytest.raises(ValueError,match='F2'): apply_patch(state,patch)
    apply_patch(state,patch,semantic=True)
    assert state.claims[1].version==2 and state.claims[0].version==1
    assert state.graph_history[-1]['record']['description']==current.description
    with pytest.raises(ValueError,match='version'): apply_patch(state,patch,semantic=True)


def test_nonempty_parameters_wire_roundtrip(prepared):
    _,_,bundle,_=prepared
    bundle.scope.parameters={'nodes':3,'network':{'loss':False,'contexts':[1,2]},'label':'非英文数据'}
    schema=bundle.model_json_schema()
    constrained=strict_schema(schema)
    encoded=wire_value(bundle.model_dump(mode='json'),schema)
    restored=type(bundle).model_validate(wire_value(encoded,schema,decode=True))
    assert restored.scope.parameters==bundle.scope.parameters
    assert schema['$defs']['Scope']['properties']['parameters']['type']=='object'
    assert constrained['$defs']['Scope']['properties']['parameters']['type']=='array'


@pytest.mark.parametrize('body',[
    'EXTENDS Naturals\nVARIABLE a\nNext == a\' = [a EXCEPT ![1] = 2]',
    'EXTENDS Naturals\nText == "Java!Print ASSUME IOUtils"\n\\* INSTANCE Unsafe\nX == 1',
    'EXTENDS Naturals\n(* nested (* INSTANCE Evil *) Java!Run *)\nX == 1'])
def test_legal_TLA_updates_strings_and_comments(body):
    validate_tla('---- MODULE Behavior ----\n'+body+'\n====','Behavior')


@pytest.mark.parametrize('body',['EXTENDS IOUtils\nX == 1','EXTENDS Naturals\nX == Java!Run(1)','EXTENDS Naturals\nX == INSTANCE Unsafe','EXTENDS Naturals\nASSUME X'])
def test_unsafe_TLA_features_remain_rejected(body):
    with pytest.raises(ValueError): validate_tla('---- MODULE Behavior ----\n'+body+'\n====','Behavior')


def prerequisites():
    return [EventRequirement(alias='start',event='started'),EventRequirement(alias='change',event='context_changed',conditions=[Comparison(field='operation',reference='start.operation'),Comparison(field='participant',reference='start.participant'),Comparison(field='context',op='ne',reference='start.context')]),EventRequirement(alias='end',event='completed',conditions=[Comparison(field='operation',reference='start.operation'),Comparison(field='participant',reference='start.participant'),Comparison(field='context',reference='change.context')])]


def test_event_identity_and_context_cannot_be_spliced():
    events=[{'event':e,'operation':'a','participant':'p','context':c} for e,c in [('started',1),('context_changed',2),('completed',2)]]
    assert match_prerequisites(events,prerequisites())['status']=='matched'
    events[1]['operation']='other'
    assert match_prerequisites(events,prerequisites())['status']=='not_reached'
    events[1]['operation']='a';del events[2]['context']
    assert match_prerequisites(events,prerequisites())['status']=='unknown'


def test_projection_of_events_state_and_metadata():
    mapping=ObservationMap(fields=[FieldProjection(model_field='kind',raw_field='event',source='event'),FieldProjection(model_field='ctx',raw_field='context',source='metadata'),FieldProjection(model_field='value',raw_field='value')],required_events=['initial','step'],description='Explicit event projection')
    events=[{'event':e,'metadata':{'context':1},'state':{'value':i}} for i,e in enumerate(['initial','step'])]
    assert project(events,mapping)[1]=={'kind':'step','ctx':1,'value':1}
    del events[1]['metadata']['context']
    with pytest.raises(ValueError,match='missing'): project(events,mapping)


def test_partial_file_not_marked_fully_explored(tmp_path,prepared):
    repo,state,_,_=prepared
    (repo/'module.rs').write_text('fn begin() {}\nfn upstream() {}\n')
    state.snapshot=capture(repo)
    add_reads(state,repo,ReadingPlan(requests=[ReadRequest(file='module.rs',start_line=1,end_line=1,reason='Initial region')],rationale='Inspect first function'),Config().budget)
    assert state.unread_ranges['module.rs']==[[2,2]]


def test_build_resources_separate_from_read_material(tmp_path):
    repo=tmp_path/'repo';repo.mkdir()
    (repo/'payload.bin').write_bytes(b'\x00\xff\x01')
    (repo/'engine.cpp').write_text('int main() { return 0; }\n')
    (repo/'Makefile').write_text('all:\n\ttrue\n')
    (repo/'credentials.json').write_text('{}')
    snap=capture(repo,tmp_path/'copy')
    assert (tmp_path/'copy/payload.bin').read_bytes()==b'\x00\xff\x01'
    assert 'payload.bin' not in snap.readable_files
    assert {'Makefile','engine.cpp'}<=set(snap.readable_files)
    assert 'credentials.json' not in snap.files and snap.exclusion_reasons


def test_F4_retains_model_search_and_other_unit_history(prepared,tmp_path):
    from consensus_assurance.workflow.artifacts import save_bundle
    from consensus_assurance.workflow.feedback import apply_feedback
    from consensus_assurance.adapters.runners.python import PythonBackend
    _,state,bundle,_=prepared
    model=save_bundle(tmp_path,state,state.units[0],bundle,PythonBackend())
    state.checks.append(CheckRun(id='execution',action='experiment',cwd=str(tmp_path),snapshot_id=state.snapshot.id,status=ExecutionStatus.COMPLETED))
    cal=Calibration(model_id=model.id,experiment_check_id='execution',mapping_path='m',trace_path='t',status='compatible',reason='Observed',origin=Origin.MOCK)
    state.calibrations.append(cal)
    revised=bundle.model_copy(deep=True);revised.harness.description='Reordered experiment only'
    apply_feedback(state,state.units[0],bundle,Feedback(kind='F4',rationale='Prerequisites missed',evidence_ids=['execution'],target_ids=[model.id],relation_ids=[],new_basis='',graph=None,bundle=revised))
    assert cal.status=='compatible' and cal.applicability=='current'


def test_error_context_contains_bounded_original_text(tmp_path,prepared):
    from consensus_assurance.workflow.engine import Engine
    from consensus_assurance.core.config import Config
    config=Config(execution_backend='python',agent_backend='mock')
    engine=Engine(config,tmp_path/'run',*assemble(config),'')
    log=tmp_path/'error.log';original='SyntaxError at source line 1\n'+('x'*30000)+'\nModuleNotFoundError: missing_producer'
    log.write_text(original)
    check=CheckRun(action='experiment',cwd=str(tmp_path),snapshot_id='s',stdout=str(log))
    context=engine.error_context(check)
    assert context['truncated'] and context['original_characters']==len(original)
    assert context['text'].startswith('SyntaxError') and context['text'].endswith('missing_producer')
    assert log.read_text()==original


@pytest.mark.parametrize('module',[None,'module another.example/module\n'])
def test_explicit_module_identity_requires_safe_build_input(tmp_path,module):
    from consensus_assurance.workflow.engine import Engine
    repo=tmp_path/'repo';repo.mkdir()
    if module:(repo/'go.mod').write_text(module)
    config=Config(execution_backend='none',target={'expected_module':'example.org/module'},agent_backend='mock')
    with pytest.raises(ValueError,match='explicit target.expected_module'):
        Engine(config,tmp_path/'run',*assemble(config)).start(repo)


def test_binary_only_build_inputs_are_not_agent_materials(tmp_path):
    from consensus_assurance.workflow.materials import initial_materials
    repo=tmp_path/'repo';repo.mkdir();(repo/'payload.bin').write_bytes(b'data\x00payload')
    snapshot=capture(repo)
    assert snapshot.readable_files==[]
    assert initial_materials(repo,snapshot,Config().budget,'')==[]


def test_F1_changes_only_related_calibration(prepared,tmp_path):
    from consensus_assurance.workflow.artifacts import save_bundle
    from consensus_assurance.workflow.feedback import apply_feedback
    from consensus_assurance.adapters.runners.python import PythonBackend
    _,state,bundle,_=prepared
    model=save_bundle(tmp_path,state,state.units[0],bundle,PythonBackend())
    other=model.model_copy(update={'id':'other-model','unit_id':'other-unit'})
    state.models.append(other)
    state.checks.append(CheckRun(id='observed',action='experiment',cwd=str(tmp_path),snapshot_id=state.snapshot.id,status=ExecutionStatus.COMPLETED))
    for item in [model,other]:
        state.calibrations.append(Calibration(model_id=item.id,experiment_check_id='observed',mapping_path='mapping',trace_path='trace',status='compatible',reason='Earlier execution',origin=Origin.MOCK))
    revised=bundle.model_copy(deep=True);revised.observation.max_internal_steps=4
    apply_feedback(state,state.units[0],bundle,Feedback(kind='F1',rationale='Explicit internal step bound mismatch',evidence_ids=['observed'],target_ids=[model.id],relation_ids=[],new_basis='',graph=None,bundle=revised))
    assert [c.status for c in state.calibrations]==['stale','compatible']
    assert state.checks[-1].status==ExecutionStatus.COMPLETED


def test_conflicting_F2_does_not_turn_error_into_optimization(prepared):
    from consensus_assurance.workflow.feedback import apply_feedback
    _,state,bundle,responses=prepared
    changed=GraphDraft.model_validate(responses[1]).claims[1]
    changed.description='A weaker proposed obligation'
    basis=changed.grounding.model_copy(deep=True);basis.unresolved=[];basis.conflicts=['The current interface still promises the stronger guarantee']
    f=Feedback(kind='F2',rationale='Proposed design tradeoff requires resolving contrary evidence',evidence_ids=[next(m.id for m in state.materials if m.file=='README.md')],target_ids=['step_obligation'],relation_ids=[],old_judgment=state.claims[1].description,new_judgment=changed.description,new_basis='Conflicting design notes',grounding=basis,patch=GraphPatch(claims=[changed],expected_versions={changed.id:1},rationale='Proposed change'),graph=None,bundle=None)
    before=state.claims[1].model_dump()
    from regression_support import declared_changes
    declared_changes(state,f)
    assert apply_feedback(state,state.units[0],bundle,f) is None
    assert state.claims[1].model_dump()==before
    assert state.revisions[-1].status=='unresolved'


def test_malformed_wire_dictionary_is_a_validation_error(prepared):
    _,_,bundle,_=prepared
    schema=bundle.model_json_schema()
    encoded=wire_value(bundle.model_dump(mode='json'),schema)
    encoded['scope']['parameters']=[{'key':['invalid'],'value_json':3}]
    with pytest.raises(ValueError,match='must be strings'):
        wire_value(encoded,schema,decode=True)
