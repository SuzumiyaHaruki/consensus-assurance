"""Actual TLC and audit artifacts exercise the shared predicate and independent scenarios."""
import json
from pathlib import Path
import sys
import pytest
from audit_support import first, stop, engine_for
from test_audit_models import model_product


def model_review(state):
    artifact=state['models'][-1]['id']
    return dict(action='review',artifact_id=artifact,rationale='Review the finite fixture model only',
        review_items=[dict(target_id=artifact,aspect='checker_correspondence',status='no_issue_found',
            source_ids=['code','doc'],rationale='The local finite bound and source correspondence are explicit; no autonomous construction claim')]),{}


@pytest.mark.parametrize('success,qualified',[(False,False),(False,True),(True,False),(True,True)])
def test_actual_tlc_shared_implication_truth_table_matches_monitor(tmp_path,tlc,success,qualified):
    from consensus_assurance.core.proposals import ModelDraft,EventRequirement
    from consensus_assurance.adapters.verifiers.observable import correspondence
    from consensus_assurance.workflow.observations import monitor_events
    from audit_support import products
    observations=[]
    def bundle(state):
        sub,files=model_product(state,draft=False)
        raw=json.loads(files['model.json'])
        raw['observable_properties']=[dict(checker_id='Bounded',kind='event_implication',
            trigger=dict(field='event',value='returned'),antecedent=dict(field='state.success',value=True),
            assertion=dict(field='state.qualified',value=True),identity_fields=['operation'],description='Success requires qualified support; failure remains permitted')]
        basis=products()[1]['harness']['legality']
        raw['monitors']=[dict(id='implication',checker_id='Bounded',event='returned',admission_alias='start',binding_ids=['binding'],grounding=basis)]
        raw['observation']['fields']=[dict(model_field='event',raw_field='event',source='event'),
            dict(model_field='success',raw_field='success'),dict(model_field='qualified',raw_field='qualified')]
        raw['observation']['required_events']=['returned']
        files['Behavior.tla']=files['Behavior.tla'].replace('Obs == [value |-> value]',
            f'Obs == [event |-> IF value = 0 THEN "admitted" ELSE "returned", success |-> {str(success).upper()}, qualified |-> {str(qualified).upper()}]')
        files['Properties.tla']='GENERATE_FROM_OBSERVABLE_PROPERTIES'
        events=[{'event':'admitted','operation':'one','state':{}},
            {'event':'returned','operation':'one','state':{'success':success,'qualified':qualified}}]
        observations[:] = events
        files['model.json']=json.dumps(raw)
        return sub,files
    def direct(state):
        from audit_support import check_step
        sub,files=check_step()(state)
        plan=json.loads(files['plan.json'])
        _,model_files=bundle(state)
        raw=json.loads(model_files['model.json'])
        plan.update(monitors=raw['monitors'],observable_properties=raw['observable_properties'])
        plan['harness']['prerequisites']=[dict(alias='start',event='admitted')]
        files['plan.json']=json.dumps(plan)
        files['check.py']='\n'.join('print('+repr('CA_EVENT '+json.dumps(event))+')' for event in observations)+'\n'
        return sub,files
    e,repo=engine_for(tmp_path,[first,bundle,direct,model_review,stop]);e.verifier=tlc[0]
    e.config.budget.model_checks=4
    state=e.start(repo)
    assert len(state.models)==1,state.current_submission
    artifact=state.models[0]
    saved=ModelDraft.model_validate_json(Path(artifact.bundle_path).read_text())
    assert correspondence(saved,saved.monitors[0]) is None
    check=next(c for c in state.checks if c.action=='model_check')
    assert check.status.value=='completed'
    violated=success and not qualified
    assert check.outcome==('counterexample' if violated else 'holds')
    from consensus_assurance.adapters.runners.experiment import extract_events
    experiment=next(c for c in state.checks if c.action=='direct_check')
    events=extract_events(experiment)
    monitored=monitor_events(events,saved.monitors[0],saved.observable_properties[0],[EventRequirement(alias='start',event='admitted')])
    assert monitored['outcome']==('violated' if violated else 'holds')
    assert monitor_events(events[:1],saved.monitors[0],saved.observable_properties[0],[EventRequirement(alias='start',event='admitted')])['outcome']=='unknown'
    incomplete=json.loads(json.dumps(events))
    incomplete[-1]['state'].pop('qualified')
    assert monitor_events(incomplete,saved.monitors[0],saved.observable_properties[0],[EventRequirement(alias='start',event='admitted')])['outcome']=='unknown'
    for event in events:event.pop('operation',None)
    assert monitor_events(events,saved.monitors[0],saved.observable_properties[0],[EventRequirement(alias='start',event='admitted')])['outcome']=='unknown'


def test_independent_model_timeout_cannot_be_overwritten_but_revision_can_replace_it(tmp_path,tlc):
    from consensus_assurance.workflow.modeling import obligation_progress
    verifier=tlc[0];actual=verifier.check;attempts=[]
    def one_timeout(runner,model,timeout):
        attempts.append(model.id)
        if len(attempts)==1:
            check=runner.run([sys.executable,'-c','import time; time.sleep(5)'],Path(model.path).parent,
                'model_check',model.snapshot_id,0.1)
            check.model_id=model.id
            return check
        return actual(runner,model,timeout)
    verifier.check=one_timeout
    def model(state,previous=False):
        sub,files=model_product(state,previous=previous)
        files['Properties.tla']=files['Properties.tla'].replace('value <= 2','value <= 3')
        if previous:sub['previous_model_id']=state['models'][0]['id']
        return sub,files
    e,repo=engine_for(tmp_path,[first,model,model,model_review,stop]);e.verifier=verifier
    state=e.start(repo)
    assert len(state.models)==2,state.current_submission
    assert next(c for c in state.checks if c.model_id==state.models[0].id and c.action=='model_check').status.value=='timeout'
    assert obligation_progress(state,state.units[0])[1]==['bounded']
    state.models.reverse()
    assert obligation_progress(state,state.units[0])[1]==['bounded']
    state.models.reverse()
    from consensus_assurance.reporting.chinese import render_report
    text=render_report(state,e.root).read_text()
    assert '执行超时' in text and '有限检查未见违反' in text
    assert all(Path(m.path).name in text for m in state.models)
    # Use a separate finite run to exercise actual artifact lineage replacement of the timed-out model.
    path=tmp_path/'revision';path.mkdir();attempts.clear()
    e,repo=engine_for(path,[first,model,lambda s:model(s,True),model_review,stop]);e.verifier=verifier
    state=e.start(repo)
    assert len(state.models)==2 and state.models[1].previous_id==state.models[0].id
    assert obligation_progress(state,state.units[0])[1]==[],state.units[0]
