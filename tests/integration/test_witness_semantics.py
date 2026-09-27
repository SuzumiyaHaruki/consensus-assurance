"""Offline v23 interpretation and generic witness/coverage semantics; no target execution."""
import copy
import json
from pathlib import Path
import pytest
from consensus_assurance.core.proposals import Comparison, EventRequirement, EventMonitor, ObservableProperty
from consensus_assurance.core.types import CheckRun, Grounding
from consensus_assurance.adapters.runners.experiment import extract_events
from consensus_assurance.workflow.direct_checks import load_plan, assess, save_plan, execute
from consensus_assurance.workflow.observations import monitor_events
from test_direct_checks import setup, review


def test_original_v23_seven_events_have_an_independent_outside_control(tmp_path):
    fixture=Path(__file__).parents[1]/'fixtures/v23-verification'
    plan=load_plan(fixture/'plan.json')
    events=extract_events(CheckRun(action='offline',cwd=str(tmp_path),snapshot_id='v23',stdout=str(fixture/'stdout.log')))
    assert len(events)==7
    result=monitor_events(events,plan.monitors[0],plan.observable_properties[0],plan.harness.prerequisites)
    assert result['witness_indices']==result['valid_witness_indices']==[3]
    assert result['outside_applicability_indices']==[6] and result['missing_indices']==[]
    from consensus_assurance.workflow.engine import FRAMEWORK_REVISION
    (tmp_path/'v24-interpretation.json').write_text(json.dumps(dict(framework_revision=FRAMEWORK_REVISION,
        source_revision='native-products-v23',target_executed=False,result=result)))


def inputs():
    prop=ObservableProperty(checker_id='Need',kind='event_implication',trigger=Comparison(field='event',value='result'),
        antecedent=Comparison(field='success',value=True),assertion=Comparison(field='qualified',value=True),
        identity_fields=['operation','generation'],description='Observed success requires actual qualification')
    monitor=EventMonitor(id='need',checker_id='Need',event='result',binding_ids=[],grounding=Grounding(),
        applicability_conditions=[Comparison(field='enabled',value=True),Comparison(field='context',reference='start.context')])
    req=[EventRequirement(alias='start',event='start')]
    events=[dict(event='start',operation='one',generation=1,context='active',enabled=True),
        dict(event='result',operation='one',generation=1,context='active',enabled=True,success=True,qualified=False)]
    return prop,monitor,req,events


@pytest.mark.parametrize('change',['outside','independent_missing','same_missing','identity','prerequisite','result','ambiguous','alias_missing','cross_context'])
def test_existential_witness_is_not_scope_completeness(change):
    p,m,req,events=inputs()
    if change=='outside':events.append(dict(event='result',enabled=False))
    if change=='independent_missing':events.append(dict(events[0],operation='two'))
    if change=='same_missing':events.append({k:v for k,v in events[1].items() if k!='qualified'})
    if change=='identity':events[1].pop('operation')
    if change=='prerequisite':events.pop(0)
    if change=='result':events.pop()
    if change=='ambiguous':events.insert(0,dict(events[0]))
    if change=='alias_missing':events[0].pop('context')
    if change=='cross_context':events[0]['generation']=2
    result=monitor_events(events,m,p,req)
    valid=change in {'outside','independent_missing'}
    assert result['witness_complete']==valid
    assert result['comparison_complete']==(change=='outside')
    assert result['outcome']==('violated' if valid else 'unknown')
    if not result['comparison_complete']:assert result['diagnostics'] and result['limitations']


@pytest.mark.parametrize('rename,reverse',[(False,False),(True,False),(False,True),(True,True)])
def test_identity_renaming_and_independent_operation_order_preserve_witness(rename,reverse):
    p,m,req,a=inputs();b=copy.deepcopy(a)
    for event in b:event['operation']='two'
    b[1]['qualified']=True
    blocks=[b,a] if reverse else [a,b]
    events=sum(blocks,[])
    if rename:
        for event in events:event['operation']='renamed-'+event['operation']
    result=monitor_events(events,m,p,req)
    assert result['outcome']=='violated' and result['comparison_complete']
    observed=events[result['valid_witness_indices'][0]]
    assert observed['operation']==('renamed-one' if rename else 'one')


def test_partial_valid_witness_is_retained_idempotently_without_completing_unit(tmp_path,prepared):
    from consensus_assurance.workflow.modeling import obligation_progress
    e,unit,plan=setup(tmp_path,prepared,True)
    plan.harness.source+="\nprint('CA_EVENT '+json.dumps({'event':'admitted','operation':'other','participant':'local','context':'configured','state':{'input_valid':True}}))\n"
    artifact=save_plan(e,unit,plan,'partial');review(e.state,unit,artifact)
    check=execute(e,artifact);events=extract_events(check)
    first=assess(e.state,unit,artifact,plan,check,events)
    before=(len(e.state.evidence),len(e.state.findings),len(e.state.monitor_results))
    second=assess(e.state,unit,artifact,plan,check,events)
    assert first==second and before==(len(e.state.evidence),len(e.state.findings),len(e.state.monitor_results))==(1,1,1)
    assert second['confirmed'] and not second['bounded_complete'] and second['properties'][0]['limitations']
    assert obligation_progress(e.state,unit)[1]==unit.obligation_ids
    polluted=assess(e.state,unit,artifact,plan,check,events+[dict(event='invalid_observation')])
    assert not polluted['confirmed'] and polluted['parsing_errors']
