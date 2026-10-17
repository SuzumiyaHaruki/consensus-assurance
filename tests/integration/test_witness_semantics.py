"""Finite identity, prerequisite and completion semantics under the unified comparison."""
import copy
import json
import pytest
from consensus_assurance.core.types import CheckRun, Comparison, EventComparison, EventRequirement
from consensus_assurance.workflow.observations import compare_events
from consensus_assurance.core.events import match_prerequisites
from consensus_assurance.adapters.runners.experiment import extract_events


def inputs():
    comparison=EventComparison(event='result',identity_fields=['operation','generation'],admission_alias='start',
        antecedent=Comparison(field='success',value=True),assertion=Comparison(field='qualified',value=True),
        applicability_conditions=[Comparison(field='enabled',value=True),Comparison(field='context',reference='start.context')])
    requirements=[EventRequirement(alias='start',event='start')]
    events=[dict(event='start',operation='one',generation=1,context='active',enabled=True),
        dict(event='result',operation='one',generation=1,context='active',enabled=True,success=True,qualified=False)]
    return comparison,requirements,events


@pytest.mark.parametrize('sample,expected,outcome',[
    ({},False,'unknown'), ({'qualified':False},False,'holds'),
    ({'qualified':None},False,'violated'), ({'qualified':None},None,'holds')])
def test_missing_sample_is_unknown_but_null_remains_a_value(sample,expected,outcome):
    comparison,requirements,events=inputs()
    comparison.assertion.value=expected
    events[1].pop('qualified')
    events[1].update(sample or {'sampling_error':'No corresponding endpoint sample'})
    result=compare_events(events,comparison,requirements)
    assert result['outcome']==outcome
    assert result['comparison_complete']==bool(sample)
    if not sample:
        assert result['diagnostics'][0]['identity']=={'operation':'one','generation':1}
        assert not result['valid_witness_indices'] and 1 in result['missing_indices']


@pytest.mark.parametrize('change,success,expected',[
    ('outside',True,'violated'),('outside_only',True,'unknown'),('formal_control',True,'violated'),
    ('independent_missing',True,'violated'),('same_missing',True,'unknown'),
    ('identity',True,'unknown'),('prerequisite',True,'unknown'),('result',True,'unknown'),
    ('ambiguous',True,'unknown'),('alias_missing',True,'unknown'),('cross_context',True,'unknown'),
    ('complete',False,'holds'),('result',False,'unknown'),('identity',False,'unknown'),('prerequisite',False,'unknown')])
def test_existential_witness_is_not_scope_completeness(change,success,expected):
    p,req,events=inputs()
    events[1]['success']=success
    if change=='outside':events.append(dict(event='result',enabled=False))
    if change=='outside_only':events=[dict(event='result',enabled=False)]
    if change=='formal_control':events.append(dict(event='result',operation='control',generation=1,enabled=True,success=True,qualified=True))
    if change=='independent_missing':events.append(dict(events[0],operation='two'))
    if change=='same_missing':events.append({k:v for k,v in events[1].items() if k!='qualified'})
    if change=='identity':events[1].pop('operation')
    if change=='prerequisite':events.pop(0)
    if change=='result':events.pop()
    if change=='ambiguous':events.insert(0,dict(events[0]))
    if change=='alias_missing':events[0].pop('context')
    if change=='cross_context':events[0]['generation']=2
    result=compare_events(events,p,req)
    assert result['witness_complete']==(expected=='violated')
    assert result['comparison_complete']==(change in {'outside','complete'})
    assert result['outcome']==expected
    if change=='outside_only':assert not result['evaluated_indices'] and result['outside_applicability_indices']==[0]
    if not result['comparison_complete'] and change!='outside_only':assert result['diagnostics'] and result['limitations']


@pytest.mark.parametrize('rename,reverse',[(False,False),(True,False),(False,True),(True,True)])
def test_identity_renaming_and_independent_operation_order_preserve_witness(rename,reverse):
    p,req,a=inputs();b=copy.deepcopy(a)
    for event in b:event['operation']='two'
    b[1]['qualified']=True
    blocks=[b,a] if reverse else [a,b]
    events=sum(blocks,[])
    if rename:
        for event in events:event['operation']='renamed-'+event['operation']
    result=compare_events(events,p,req)
    assert result['outcome']=='violated' and result['comparison_complete']
    observed=events[result['valid_witness_indices'][0]]
    assert observed['operation']==('renamed-one' if rename else 'one')

    for event in events:
        if event['event']=='result':event['qualified']=True
    result=compare_events(events,p,req)
    assert result['outcome']=='holds' and result['comparison_complete'] and not result['valid_witness_indices']


def test_admission_and_independent_prerequisite_permutation():
    prop,requirements,events=inputs()
    requirements.append(EventRequirement(alias='ready',event='ready'))
    events.insert(1,dict(events[0],event='ready'))
    events.append(dict(events[0],operation='unfinished'))
    outcomes=[compare_events(events,prop,order) for order in [requirements,list(reversed(requirements))]]
    for result in outcomes:
        assert result['outcome']=='violated' and result['witness_complete'] and not result['comparison_complete']
        assert result['missing_indices']==[3]
    prop.admission_alias='missing'
    assert compare_events(events,prop,requirements)['outcome']=='unknown'
    assert compare_events([],prop,requirements)['outcome']=='unknown'
    prop.admission_alias='start'
    prop.applicability_conditions.append(Comparison(field='context',reference='ready.context'))
    requirements[1].conditions=[Comparison(field='context',reference='start.context')]
    reversed_events=[events[1],events[0],*events[2:]]
    assert compare_events(reversed_events,prop,requirements)['outcome']=='unknown'
    result=compare_events(events[:3]+[events[0]],prop,requirements)
    assert result['outcome']=='unknown' and result['missing_indices']==[3]


def test_independent_scenario_chains_keep_required_history_and_completion():
    requirements = [EventRequirement(alias='boot',event='boot'), *[
        EventRequirement(alias=mode,event='admit',conditions=[Comparison(field='mode',value=mode),
            Comparison(field='context',reference='boot.context')]) for mode in ('a','b')]]
    events = [dict(event=event,operation=mode,mode=mode,context=1,actual=actual)
        for mode,actual in [('a',0),('b',1)] for event in ('boot','admit','result')]
    def result(mode, values=events):
        prop = EventComparison(event='result',identity_fields=['operation','context'],admission_alias=mode,
            applicability_conditions=[Comparison(field='mode',value=mode)],assertion=Comparison(field='actual',value=1))
        return compare_events(values,prop,requirements)
    assert result('a')['witness_complete'] and result('b')['comparison_complete']
    assert result('b')['outcome']=='holds'
    for values in (events[1:], events[:1]+events[2:], [events[0],*events]):
        assert result('a',values)['outcome']=='unknown'
    incomplete=result('a',events[:2]+events[3:])
    assert incomplete['missing_indices']==[1] and not incomplete['comparison_complete']
    assert result('b',events[1:])['comparison_complete']


@pytest.mark.parametrize('qualified',[False,True])
def test_result_applicability_does_not_filter_admission(qualified):
    prop,requirements,events=inputs()
    events[0]['enabled']=False
    events[1]['qualified']=qualified
    events.append(dict(events[0],operation='unfinished'))
    result=compare_events(events,prop,requirements)
    assert result['missing_indices']==[2] and not result['comparison_complete']
    assert result['outcome']==('unknown' if qualified else 'violated')
    assert result['witness_complete']==(not qualified)


def prerequisites():
    return [EventRequirement(alias='start',event='started'),EventRequirement(alias='change',event='context_changed',conditions=[Comparison(field='operation',reference='start.operation'),Comparison(field='participant',reference='start.participant'),Comparison(field='context',op='ne',reference='start.context')]),EventRequirement(alias='end',event='completed',conditions=[Comparison(field='operation',reference='start.operation'),Comparison(field='participant',reference='start.participant'),Comparison(field='context',reference='change.context')])]


def test_event_identity_and_context_cannot_be_spliced():
    events=[{'event':e,'operation':'a','participant':'p','context':c} for e,c in [('started',1),('context_changed',2),('completed',2)]]
    assert match_prerequisites(events,prerequisites())['status']=='matched'
    events[1]['operation']='other'
    assert match_prerequisites(events,prerequisites())['status']=='not_reached'
    events[1]['operation']='a';del events[2]['context']
    assert match_prerequisites(events,prerequisites())['status']=='unknown'


@pytest.mark.parametrize('variation',['same','context','operation','unrelated_event','future'])
def test_consequence_requires_correlated_prior_participants(variation):
    requirement=EventRequirement(alias='producer',event='accepted',conditions=[Comparison(field='participant',value='a')])
    events=[{'participant':'a','event':'accepted','operation':'x','context':1},{'participant':'b','event':'returned','operation':'x','context':1}];index=1
    if variation=='context':events[0]['context']=2
    if variation=='operation':events[0]['operation']='y'
    if variation=='unrelated_event':events[0]['event']='unrelated'
    if variation=='future':events.reverse();index=0
    assert (match_prerequisites(events,[requirement],index,['operation','context'])['status']=='matched') is (variation=='same')


def test_go_event_runner_times_preserve_interleaved_comparisons_and_legacy_output(tmp_path):
    first='2026-10-12T02:31:55.481Z'
    middle='2026-10-12T02:31:56.481Z'
    completed='2026-10-12T02:31:57.503Z'
    envelopes=[
        {'Package':'p','Test':'A','Time':first,'Output':'CA_'},
        {'Package':'p','Test':'B','Time':middle,'Output':'CA_EVENT {"event":"input","operation":"same","state":{"value":2}}\n'},
        {'Package':'p','Test':'A','Time':middle,'Output':'EVENT {"event":"input","operation":"same",'},
        {'Package':'p','Test':'A','Time':completed,'Output':'"state":{"value":1},"t_ms":0}\n'},
        {'Package':'p','Test':'B','Time':completed,'Output':'CA_EVENT {"event":"output","operation":"same","state":{"value":2}}\n'},
        {'Package':'p','Test':'A','Output':'CA_EVENT {"event":"output","operation":"same","state":{"value":1}}\n'},
        {'Package':'p','Test':'C','Output':'CA_EVENT {"event":"truncated"'},
        {'Package':'p','Test':'D','Time':middle,'Output':'CA_EVENT {"event":"tail"}'},
    ]
    stdout=tmp_path/'events.stdout'
    stdout.write_text('\n'.join(json.dumps(e) for e in envelopes)+
        '\nCA_EVENT malformed\nCA_EVENT {"event":"plain","t_ms":1300}\n')
    check=CheckRun(action='direct_check',cwd=str(tmp_path),snapshot_id='snapshot',stdout=str(stdout))
    events=extract_events(check)
    assert [e['_ca_stream'] for e in events[:4]]==['["p","B"]','["p","A"]','["p","B"]','["p","A"]']
    assert events[0]['_ca_observation']['runner_time']==middle
    assert events[1]['_ca_observation']=={
        'stream':'["p","A"]','location':{'line':4,'stream':'["p","A"]'},'runner_time':completed}
    assert events[1]['t_ms']==0
    assert events[2]['_ca_observation']['runner_time']==completed
    assert 'runner_time' not in events[3]['_ca_observation']
    invalid=[e for e in events if e['event']=='invalid_observation']
    assert len(invalid)==2 and all('runner_time' not in e['_ca_observation'] for e in invalid)
    assert any(e['_ca_observation']['location']['line']=='end-of-stream' for e in invalid)
    plain=next(e for e in events if e['event']=='plain')
    assert plain['t_ms']==1300 and 'runner_time' not in plain['_ca_observation']
    tail=next(e for e in events if e['event']=='tail')
    assert tail['_ca_observation']=={
        'stream':'["p","D"]','location':{'line':'end-of-stream','stream':'["p","D"]'},'runner_time':middle}
    comparison=EventComparison(event='output',identity_fields=['operation'],admission_alias='input',
        assertion=Comparison(field='state.value',reference='input.state.value'))
    requirements=[EventRequirement(alias='input',event='input')]
    result=compare_events(events,comparison,requirements)
    assert result['outcome']=='holds' and result['comparison_complete']
    assert result['evaluated_indices']==[2,3] and result['missing_indices']==[]
    without_times=[{**e,'_ca_observation':{k:v for k,v in e['_ca_observation'].items() if k!='runner_time'}} for e in events]
    assert compare_events(without_times,comparison,requirements)==result
    unmatched=compare_events([events[0],events[3]],comparison,requirements)
    assert unmatched['outcome']=='unknown' and unmatched['missing_indices']==[0,1]
