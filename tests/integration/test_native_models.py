"""Native model products with real SANY/TLC and Python; transport is scripted."""
import json
from pathlib import Path
import pytest
from consensus_assurance.core.proposals import ModelDraft
from native_support import ScriptedAgent, first, stop, engine_for, products


def model_product(state, *, draft=True, previous=False, change='technical', replay=False):
    _, plan, _ = products()
    # Deliberately bounded model bug; no claim that the real implementation shares it.
    behavior='''---------------- MODULE Behavior ----------------
EXTENDS Naturals
VARIABLE value
vars == <<value>>
Obs == [value |-> value]
Init == value = 0
Next == IF value < 3 THEN value' = value + 1 ELSE value' = 0
Reached == value = 1
=================================================
'''
    properties='''---------------- MODULE Properties ----------------
EXTENDS Behavior
Bounded == value <= 2
===================================================
'''
    raw=dict(description='Finite local boundary model',behavior='',properties='',constants='',
        invariants=['Bounded'],checked_claim_ids=['bounded'],initial_state='Zero initial value',variables=['value'],
        actions=['Next'],constraints=[dict(constraint='Abstract the actual branch and finite capacity',source_kind='code_observation',source_ids=['code'],binding_ids=['binding'],justification='The two actual branches wrap at capacity')],
        scope=state['units'][0]['scope'],uncertainties=['The model checker bound is intentionally narrower in this tool fixture'],
        reachability=[dict(id='reached',operator='Reached',claim_ids=['bounded'],description='An actual increment can occur')])
    harness='''import json
from target import step
value=0
print('CA_EVENT '+json.dumps({'event':'initial','state':{'value':value}}))
for i in range(4):
    value=step(value,3)
    print('CA_EVENT '+json.dumps({'event':'step','state':{'value':value}}))
'''
    if draft:
        raw['pending_work']=[dict(component='harness',reason='Not assembled'),dict(component='observation',reason='Not projected')]
    else:
        raw['harness']=dict(kind='python',source='',description='Actual calls in a copied fixture',semantic_changes=[])
        raw['observation']=dict(fields=[dict(model_field='value',raw_field='value')],required_events=['initial','step'],description='Actual returned values')
    submission=dict(action='model',unit_id=state['units'][0]['id'],model_path='model.json',behavior_path='Behavior.tla',properties_path='Properties.tla',rationale='Exercise the actual model tools',change=change)
    if previous:submission['previous_model_id']=state['models'][-1]['id']
    files={'model.json':json.dumps(raw),'Behavior.tla':behavior,'Properties.tla':properties}
    if not draft:
        submission['harness_path']='check.py';files['check.py']=harness
    if replay:submission['replay_finding_id']=state['findings'][-1]['id']
    return submission,files


def test_model_draft_search_then_assembly_calibration_and_replay(tmp_path,tlc):
    verifier,_=tlc
    e,repo=engine_for(tmp_path,[first,
        lambda state:model_product(state),
        lambda state:model_product(state,draft=False,previous=True),
        lambda state:model_product(state,draft=False,previous=True,change='F4',replay=True),stop])
    e.verifier=verifier
    e.config.budget.model_checks=8;e.config.budget.reachability_checks=4;e.config.budget.calibration_checks=8
    state=e.start(repo)
    assert len(state.models)==3, (state.stop_reason,state.native_current)
    assert state.models[0].stage=='model_only'
    assert all(Path(m.path).is_file() for m in state.models)
    searches=[c for c in state.checks if c.action=='model_check']
    assert len(searches)==3 and searches[0].outcome=='counterexample'
    assert searches[1].reused_from==searches[0].id
    assert all(c.status.value=='completed' for c in state.checks if c.action=='model_syntax')
    assert state.reachability_results and all(r.status=='reachable' for r in state.reachability_results)
    assert len(state.calibrations)==2 and all(c.status=='compatible' for c in state.calibrations)
    replay=next(c for c in state.checks if c.action=='replay')
    assert replay.exit_code==0 and replay.model_id==state.models[-1].id
    assert state.monitor_results and all(not r['confirmed'] for r in state.monitor_results)
    assert any(f.replay_check_id==replay.id for f in state.findings)


def test_f1_changes_search_inputs_and_preserves_checker(tmp_path,tlc):
    verifier,_=tlc
    def revision(state):
        submission,files=model_product(state,previous=True,change='F1')
        files['Behavior.tla']=files['Behavior.tla'].replace('value < 3','value < 2')
        return submission,files
    e,repo=engine_for(tmp_path,[first,lambda state:model_product(state),revision,stop])
    e.verifier=verifier;e.config.budget.model_checks=6
    state=e.start(repo)
    assert len(state.models)==2,(state.stop_reason,state.native_current)
    old,new=state.models
    assert Path(old.checker_path).read_text()==Path(new.checker_path).read_text()
    assert old.search_fingerprint!=new.search_fingerprint
    searches=[c for c in state.checks if c.action=='model_check']
    assert [c.outcome for c in searches]==['counterexample','holds']
    assert not searches[-1].reused_from
    assert state.revisions[-1].kind=='F1'


def test_incomplete_core_and_actual_syntax_error_can_be_repaired(tmp_path,tlc):
    verifier,_=tlc
    def incomplete(state):
        sub,files=model_product(state)
        raw=json.loads(files['model.json'])
        raw['pending_work'].append(dict(component='behavior',reason='Unresolved actual branch'))
        files['model.json']=json.dumps(raw)
        return sub,files
    def syntax_error(state):
        sub,files=model_product(state)
        files['Behavior.tla']=files['Behavior.tla'].replace('Next == IF','Next == IF (')
        return sub,files
    e,repo=engine_for(tmp_path,[first,incomplete,syntax_error,
        lambda state:model_product(state,previous=True),stop])
    e.verifier=verifier;e.config.budget.model_checks=6
    state=e.start(repo)
    assert len(state.models)==2,(state.stop_reason,state.native_current)
    syntax=[c for c in state.checks if c.action=='model_syntax']
    assert len(syntax)==2 and syntax[0].outcome=='unknown' and syntax[1].exit_code==0
    assert len([c for c in state.checks if c.action=='model_check'])==1
    assert Path(state.models[0].path).is_file()
    assert len(list((e.root/'native-submissions').glob('*/diagnostics.json')))==1


@pytest.mark.parametrize('variant',['correlated','unreached','incompatible'])
def test_native_replay_assesses_actual_correlated_observations(tmp_path,tlc,variant):
    verifier,_=tlc
    def bundle(state,replay=False):
        sub,files=model_product(state,draft=False,previous=replay,change='F4' if replay else 'technical',replay=replay)
        raw=json.loads(files['model.json']);basis=products()[1]['harness']['legality']
        raw['harness'].update(legality=basis,prerequisites=[dict(alias='start',event='initial',conditions=[dict(field='state.value',value=0)])])
        raw['observable_properties']=[dict(checker_id='Bounded',kind='event_assertion',
            trigger=dict(field='state.value',value=3),assertion=dict(field='state.in_range',value=True),
            identity_fields=['operation'],description='An actual result at three violates the fixture bound of two')]
        raw['monitors']=[dict(id='range',checker_id='Bounded',event='step',binding_ids=['binding'],grounding=basis)]
        raw['observation']['fields'].append(dict(model_field='in_range',raw_field='in_range'))
        files['model.json']=json.dumps(raw)
        files['Behavior.tla']=files['Behavior.tla'].replace('Obs == [value |-> value]','Obs == [value |-> value, in_range |-> value <= 2]')
        files['Properties.tla']='GENERATE_FROM_OBSERVABLE_PROPERTIES'
        files['check.py']=files['check.py'].replace("'state':{'value':value}","'operation':'one','state':{'value':value,'in_range':value <= 2}")
        if replay and variant=='unreached':files['check.py']=files['check.py'].replace('value=0','value=1')
        if replay and variant=='incompatible':files['check.py']=files['check.py'].replace('step(value,3)','step(value,4)')
        return sub,files
    def review(state):
        return dict(action='review',artifact_id=state['models'][-1]['id'],rationale='Controlled fixture correspondence, not autonomous review',
            review_items=[dict(target_id=state['models'][-1]['id'],aspect='checker_correspondence',status='no_issue_found',source_ids=['code','doc'],
                rationale='The shared bound compares the actual result, source contract and correlated initial call; calibration and reached prerequisites remain separate mechanical requirements')]),{}
    e,repo=engine_for(tmp_path,[first,bundle,lambda state:bundle(state,True),review,stop])
    (repo/'README.md').write_text('This explicit regression fixture requires every legal returned value to be at most two.\n')
    e.verifier=verifier;e.config.budget.model_checks=8;e.config.budget.calibration_checks=8
    state=e.start(repo)
    assert len(state.models)==2,(state.stop_reason,state.native_current)
    replay=next(c for c in state.checks if c.action=='replay')
    result=next(r for r in state.monitor_results if r['experiment_check_id']==replay.id)
    calibration=next(c for c in state.calibrations if c.id==result['calibration_id'])
    assert replay.exit_code==0 and not result['confirmed']
    if variant=='unreached':assert result['prerequisites']['status']=='not_reached'
    elif variant=='incompatible':assert calibration.status!='compatible'
    else:
        assert calibration.status=='compatible' and result['prerequisites']['status']=='matched'
        assert result['properties'][0]['outcome']=='violated' and not result['properties'][0]['blockers']
        assert len(result['blockers'])==1 and result['blockers'][0].startswith('Mock, synthetic')


def test_native_f3_preserves_old_unit_and_checks_new_dependency_scope(tmp_path,tlc):
    def expand(state):
        from consensus_assurance.core.types import Analysis
        from consensus_assurance.core.proposals import GraphPatch,BindingDraft,UnitDraft
        from consensus_assurance.workflow.scope_updates import from_patch
        saved=Analysis.model_validate(state);old=saved.units[0]
        binding=BindingDraft(id='producer',material_id='producer-source',symbol='admit',start_line=1,end_line=2,
            associations=[dict(claim_id='bounded',source_ids=['producer-source'],rationale='Actual caller bounds the input')],description='Local supporting input producer',pending=['Producer broader correctness not checked'])
        unit=UnitDraft(**{k:v for k,v in old.model_dump().items() if k in UnitDraft.model_fields})
        unit.binding_ids.append('producer')
        patch=GraphPatch(bindings=[binding],units=[unit],expected_versions={old.id:old.version},rationale='Include the actual supporting producer without adding another checked obligation')
        update=from_patch(saved,old,patch)
        return dict(action='research',scope_path='scope.json',sources=[dict(id='producer-source',file='producer.py',start_line=1,end_line=2,kind='code_observation')],rationale=patch.rationale),{'scope.json':update.model_dump_json()}
    verifier,_=tlc
    e,repo=engine_for(tmp_path,[first,expand,lambda state:model_product(state),stop])
    (repo/'producer.py').write_text('def admit(value):\n    return min(3, max(0, value))\n')
    e.verifier=verifier
    state=e.start(repo)
    assert len(state.units)==2,(state.stop_reason,state.native_current)
    new,old=state.units
    assert new.previous_id==old.id and old.status=='revised'
    assert new.obligation_ids==old.obligation_ids==['bounded']
    assert 'producer' in new.binding_ids and 'producer' not in old.binding_ids
    assert state.models[0].unit_id==new.id
    assert any(c.action=='model_check' and c.status.value=='completed' for c in state.checks)
