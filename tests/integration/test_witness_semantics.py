"""Generic witness and observation coverage semantics; no historical target replay."""
import copy
import pytest
from consensus_assurance.core.proposals import Comparison, EventRequirement, EventMonitor, ObservableProperty
from consensus_assurance.core.types import Grounding
from consensus_assurance.adapters.runners.experiment import extract_events
from consensus_assurance.workflow.direct_checks import assess, save_plan, execute
from consensus_assurance.workflow.observations import monitor_events
from regression_support import setup, review


def inputs():
    prop=ObservableProperty(checker_id='Need',kind='event_implication',trigger=Comparison(field='event',value='result'),
        antecedent=Comparison(field='success',value=True),assertion=Comparison(field='qualified',value=True),
        identity_fields=['operation','generation'],description='Observed success requires actual qualification')
    monitor=EventMonitor(id='need',checker_id='Need',event='result',binding_ids=[],grounding=Grounding(),admission_alias='start',
        applicability_conditions=[Comparison(field='enabled',value=True),Comparison(field='context',reference='start.context')])
    req=[EventRequirement(alias='start',event='start')]
    events=[dict(event='start',operation='one',generation=1,context='active',enabled=True),
        dict(event='result',operation='one',generation=1,context='active',enabled=True,success=True,qualified=False)]
    return prop,monitor,req,events


@pytest.mark.parametrize('change,success,expected',[
    ('outside',True,'violated'),('independent_missing',True,'violated'),('same_missing',True,'unknown'),
    ('identity',True,'unknown'),('prerequisite',True,'unknown'),('result',True,'unknown'),
    ('ambiguous',True,'unknown'),('alias_missing',True,'unknown'),('cross_context',True,'unknown'),
    ('complete',False,'holds'),('result',False,'unknown'),('identity',False,'unknown'),('prerequisite',False,'unknown')])
def test_existential_witness_is_not_scope_completeness(change,success,expected):
    p,m,req,events=inputs()
    events[1]['success']=success
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
    assert result['witness_complete']==(expected=='violated')
    assert result['comparison_complete']==(change in {'outside','complete'})
    assert result['outcome']==expected
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

    for event in events:
        if event['event']=='result':event['qualified']=True
    result=monitor_events(events,m,p,req)
    assert result['outcome']=='holds' and result['comparison_complete'] and not result['valid_witness_indices']


def test_partial_valid_witness_is_retained_idempotently_without_completing_unit(tmp_path,prepared):
    from consensus_assurance.workflow.direct_checks import obligation_progress
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
    from consensus_assurance.reporting.chinese import render_report
    saved=e.state.model_dump(mode='json')
    text=render_report(e.state,e.root).read_text()
    assert '**已确认违反**' in text and '独立场景完整处置：False' in text
    assert '完整反例已确认；另有独立场景覆盖缺口' in text and '对应性意见：no_issue_found' in text
    assert '已确认违反；另有场景尚未完成' in text
    assert '尚未完成复核' not in text and e.state.model_dump(mode='json')==saved
    assert '（未完成）' in text and 'other' in text and second['properties'][0]['limitations'][0] in text
    polluted=assess(e.state,unit,artifact,plan,check,events+[dict(event='invalid_observation')])
    assert not polluted['confirmed'] and polluted['parsing_errors']


def test_admission_and_independent_prerequisite_permutation():
    prop,monitor,requirements,events=inputs()
    requirements.append(EventRequirement(alias='ready',event='ready'))
    events.insert(1,dict(events[0],event='ready'))
    events.append(dict(events[0],operation='unfinished'))
    outcomes=[monitor_events(events,monitor,prop,order) for order in [requirements,list(reversed(requirements))]]
    for result in outcomes:
        assert result['outcome']=='violated' and result['witness_complete'] and not result['comparison_complete']
        assert result['missing_indices']==[3]
    monitor.admission_alias=None
    assert monitor_events(events,monitor,prop,requirements)['outcome']=='unknown'
    assert monitor_events([],monitor,prop,requirements)['outcome']=='unknown'
    monitor.admission_alias='start'
    requirements[1].conditions=[Comparison(field='context',reference='start.context')]
    reversed_events=[events[1],events[0],*events[2:]]
    assert monitor_events(reversed_events,monitor,prop,requirements)['outcome']=='unknown'
    result=monitor_events(events[:3]+[events[0]],monitor,prop,requirements)
    assert result['outcome']=='unknown' and result['missing_indices']==[3]


def test_phase_readiness_does_not_discharge_selected_delivery_contract():
    for fifo,special in [(True,True),(True,False),(False,True)]:
        pending=['earlier'];ready=True
        assert ready and pending
        pending.append('later')
        delivered=[pending.pop(-1 if special else 0),pending.pop(0)]
        prop,monitor,requirements,events=inputs()
        requirements.append(EventRequirement(alias='delivery',event='delivery',
            conditions=[Comparison(field='contract_met',value=True)]))
        observed=dict(events[0],event='delivery',ready=ready,fifo_required=fifo,
            delivered=delivered,contract_met=not fifo or delivered==['earlier','later'])
        events.insert(1,observed)
        result=monitor_events(events,monitor,prop,requirements)
        assert result['outcome']==('unknown' if fifo and special else 'violated')
        assert result['witness_complete']==(not fifo or not special)


@pytest.mark.parametrize('qualified',[False,True])
def test_result_applicability_does_not_filter_admission(qualified):
    prop,monitor,requirements,events=inputs()
    events[0]['enabled']=False
    events[1]['qualified']=qualified
    events.append(dict(events[0],operation='unfinished'))
    result=monitor_events(events,monitor,prop,requirements)
    assert result['missing_indices']==[2] and not result['comparison_complete']
    assert result['outcome']==('unknown' if qualified else 'violated')
    assert result['witness_complete']==(not qualified)
