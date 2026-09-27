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
        reachability=[dict(id='reached',operator='Reached',claim_ids=['bounded'],behavior_ids=['call'],fact_ids=['result'],description='An actual increment can occur')])
    raw['observation']=dict(fields=[dict(model_field='value',raw_field='value')],required_events=['initial','step'],description='Actual returned values')
    submission=dict(action='model',unit_id=state['units'][0]['id'],model_path='model.json',behavior_path='Behavior.tla',properties_path='Properties.tla',rationale='Exercise the actual model tools')
    if previous:submission['previous_model_id']=state['models'][-1]['id']
    files={'model.json':json.dumps(raw),'Behavior.tla':behavior,'Properties.tla':properties}
    return submission,files




def test_optional_history_search_then_separate_direct_evidence(tmp_path,tlc):
    from native_support import check_step,review_step
    e,repo=engine_for(tmp_path,[first,model_product,check_step(),review_step(),stop])
    e.verifier=tlc[0]
    state=e.start(repo)
    assert len(state.models)==1,(state.stop_reason,state.native_current)
    assert state.models[0].stage=='model_only'
    search=next(c for c in state.checks if c.action=='model_check')
    assert search.outcome=='counterexample'
    assert state.reachability_results[0].status=='reachable'
    assert not state.calibrations and not any(c.action=='replay' for c in state.checks)
    assert len(state.monitor_results)==1 and state.monitor_results[0]['direct_check_id']
    assert not any(f.stage.value=='reproduced' for f in state.findings)


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
        raw.setdefault('pending_work',[]).append(dict(component='behavior',reason='Unresolved actual branch'))
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


@pytest.mark.parametrize('owner',['candidate','surface'])
def test_pre_obligation_history_search_has_no_invented_claim(tmp_path,tlc,owner):
    from test_native_research import question_step,map_step
    from native_support import partial_map
    def explore(state):
        seed=dict(state,units=[dict(id='unused',scope={'description':'Exploratory call history'})])
        sub,files=model_product(seed)
        sub.pop('unit_id')
        sub['research_ref']=state['question_candidates'][0]['id'] if owner=='candidate' else 'surface:entry'
        raw=json.loads(files['model.json']);raw['checked_claim_ids']=[]
        raw['constraints'][0]['binding_ids']=[]
        for req in raw['reachability']:
            req['claim_ids']=[]
            if owner=='surface':req['behavior_ids']=req['fact_ids']=[]
        files['model.json']=json.dumps(raw)
        return sub,files
    spec=partial_map();spec['surfaces']=[dict(entry_point='entry',disposition='deferred',source_ids=['code'],reason='History discriminator not yet selected')]
    def review_history(state):
        model=state['models'][0]['id']
        return dict(action='review',artifact_id=model,rationale='Review exploratory history only',review_items=[dict(
            target_id=model,aspect='checker_correspondence',status='no_issue_found',source_ids=['code'],
            rationale='The source-derived bounded history proposes a call sequence; it asserts no implementation correctness')]),{}
    def finish(state):
        sub,files=stop(state)
        sub['ref_ids']=[next(c['id'] for c in state['checks'] if c['action']=='model_check')]
        return sub,files
    e,repo=engine_for(tmp_path,[question_step if owner=='candidate' else map_step(spec),explore,review_history,finish]);e.verifier=tlc[0]
    state=e.start(repo)
    assert len(state.models)==1,state.native_current
    assert not state.units and not state.claims and not state.evidence and not state.findings
    assert state.models[0].research_ref and state.models[0].claim_id is None
    from consensus_assurance.workflow.review_contract import target_contract
    assert target_contract(state,state.models[0])['required_material_ids']==['code']
    assert state.semantic_reviews[0].unit_id is None and state.semantic_reviews[0].unit_version is None
    assert not list((e.root/'native-submissions').glob('*/diagnostics.json'))
    assert any(c.action=='model_check' and c.outcome=='counterexample' for c in state.checks)


def test_selected_missing_model_tool_retains_draft_without_claiming_execution(tmp_path):
    from consensus_assurance.adapters.verifiers.tlc import TLCVerifier
    e,repo=engine_for(tmp_path,[first,model_product,stop]);e.verifier=TLCVerifier(str(tmp_path/'missing.jar'))
    state=e.start(repo)
    assert len(state.models)==1 and not state.evidence
    assert not any(c.action=='model_check' for c in state.checks)
    assert any('TLC JAR' in gap for gap in state.gaps)
    assert state.run_stop['reason']=='insufficient_basis'
    assert state.usage['agent_calls']==3 and Path(state.models[0].bundle_path).exists()
