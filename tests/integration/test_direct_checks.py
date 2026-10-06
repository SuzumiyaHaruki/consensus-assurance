"""Actual fixture execution, never a real backend or a production correctness claim."""
import json
import shutil
import subprocess
from pathlib import Path
import pytest
from regression_support import review
from regression_support import setup
from consensus_assurance.core.types import *
from consensus_assurance.core.proposals import *
from consensus_assurance.workflow.direct_checks import save_plan,execute,assess,validate_plan
from consensus_assurance.adapters.runners.experiment import extract_events


@pytest.mark.parametrize('eligible,success,expected',[(False,False,'holds'),(False,True,'violated'),(True,False,'unknown'),(True,True,'unknown')])
def test_necessary_support_oracle_does_not_require_sufficient_completion(eligible,success,expected):
    from consensus_assurance.workflow.observations import monitor_events
    requirements=[EventRequirement(alias='input',event='admitted')]
    prop=ObservableProperty(checker_id='Support',trigger=Comparison(field='event',value='returned'),
        assertion=Comparison(field='state.success',value=False),identity_fields=['operation','context'],
        description='Success requires eligible support')
    monitor=EventMonitor(id='support',checker_id='Support',event='returned',binding_ids=['fixture'],grounding=Grounding(),admission_alias='input',
        applicability_conditions=[Comparison(field='state.eligible_support',value=False)])
    events=[{'event':'admitted','operation':'one','context':'fixed','state':{'eligible_support':eligible}},
        {'event':'returned','operation':'one','context':'fixed','state':{'eligible_support':eligible,'success':success}}]
    assert monitor_events(events,monitor,prop,requirements)['outcome']==expected
    if not eligible:
        assert monitor_events(events[:1],monitor,prop,requirements)['outcome']=='unknown'
        assert monitor_events([events[0],{k:v for k,v in events[1].items() if k!='operation'}],monitor,prop,requirements)['outcome']=='unknown'


def test_unattributed_failures_and_exact_completed_witness(tmp_path,prepared):
    from copy import deepcopy
    from consensus_assurance.core.submissions import ReviewSubmission
    from consensus_assurance.workflow import direct_checks
    from consensus_assurance.workflow.audit import accept, Inputs
    from consensus_assurance.workflow.transactions import commit_graph
    from consensus_assurance.workflow.reviews import accept_review
    from consensus_assurance.workflow.research import unit_progress
    e,u,p=setup(tmp_path,prepared,True)
    normal=save_plan(e,u,p,'normal');review(e.state,u,normal)
    normal_check=execute(e,normal)
    assert assess(e.state,u,normal,p,normal_check,extract_events(normal_check))['confirmed']
    # Real fixture call returns an out-of-range value, then unrelated local cleanup fails.
    p.harness.source+='\nraise RuntimeError("Independent fixture cleanup failed")\n'
    validate_plan(e.state,u,p,e.implementation)
    a=save_plan(e,u,p,'failed-suffix',previous=normal);review(e.state,u,a)
    c=execute(e,a);events=extract_events(c)
    raw=(Path(c.stdout).read_bytes(),Path(c.stderr).read_bytes())
    assert c.exit_code==1 and c.outcome=='tests_failed'
    before=assess(e.state,u,a,p,c,events)
    assert before['outcome']=='violated' and not before['confirmed'] and not before['reviewed_complete']
    item=e.state.semantic_reviews[-1].items[0].model_copy(deep=True)
    item.execution_attribution=ExecutionAttribution(check_id=c.id,witness_indices={'Range':[1]},failure_stream='stderr',
        failure_lines=(len(raw[1].splitlines()),len(raw[1].splitlines())),harness_lines=(len(p.harness.source.splitlines()),)*2)
    item.rationale='The synchronous source return and independent range comparison completed before a separate raise with no shared target state; no persistence, sampling or reply step depends on that raise.'
    submission=ReviewSubmission(action='review',artifact_id=a.id,rationale='Controlled framework review; not an Agent discovery',review_items=[item.model_dump(mode="json")])
    # Invalid references use the real acceptance function on private states, with no partial review.
    for field,value in [('check_id',normal_check.id),('check_id','invented'),('witness_indices',{'Other':[1]}),
            ('witness_indices',{'Range':[0]}),('witness_indices',{'Range':[999]}),('witness_indices',{}),
            ('failure_lines',(0,1)),('failure_lines',(1,999)),('harness_lines',(999,999))]:
        state=e.state.model_copy(deep=True);bad=submission.model_copy(deep=True)
        setattr(bad.review_items[0].execution_attribution,field,value)
        saved=state.model_dump(mode='json')
        with pytest.raises(ValueError):accept_review(state,bad,'invalid')
        assert state.model_dump(mode='json')==saved
    commit_graph(e,'exact-failure-review',submission.model_dump(mode='json'),
        lambda proxy:accept(proxy,submission,Inputs(e.root/'draft'),'exact-failure-review'))
    result=next(r for r in e.state.monitor_results if r['experiment_check_id']==c.id)
    assert result['confirmed'] and result['bounded_complete'] and result['reviewed_complete']
    assert result['properties'][0]['confirmed_witness_indices']==[1]
    assert direct_checks.obligation_progress(e.state,e.state.units[0])[1]==[]
    assert unit_progress(e.state,u,[a],[result])[0]['record_status']=='assessed'
    assert e.state.checks[-1].exit_code==1 and e.state.checks[-1].outcome=='tests_failed'
    from consensus_assurance.reporting.chinese import render_report
    text=render_report(e.state,e.root).read_text()
    assert '原执行非零退出（1）保留' in text and '独立失败归因' in text
    # Framework state/event variants reuse saved observations, never rerun the target.
    for fault in ('unreviewed','withdrawn','disputed','issue','version','other_execution','wrong_artifact','snapshot',
            'timeout','cancelled','signal','unknown','build','no_tests','not_started','changed_target','unknown_integrity',
            'prerequisite','missing','identity','applicability','holds','parsing','contradiction'):
        state=e.state.model_copy(deep=True);plan=p.model_copy(deep=True);observations=deepcopy(events)
        check=next(x for x in state.checks if x.id==c.id)
        latest=state.semantic_reviews[-1].items[0]
        if fault=='unreviewed':state.semantic_reviews=[]
        elif fault=='withdrawn':latest.execution_attribution=None
        elif fault=='disputed':latest.status='disputed';latest.counterevidence=['The endpoint needs another step']
        elif fault=='issue':state.review_issues.append(ReviewIssue(review_id='challenge',target_id=a.id,target_version=1,
            aspect='checker_correspondence',source_ids=item.source_ids,explanation='Completion still depends on sampling',reason='Concrete new counterevidence',disposition='investigation'))
        elif fault=='version':next(x for x in state.claims if x.id==p.claim_id).version+=1
        elif fault=='other_execution':check.id='new-execution'
        elif fault=='wrong_artifact':check.direct_check_id=normal.id
        elif fault=='snapshot':check.snapshot_id='other-snapshot'
        elif fault in {'timeout','cancelled','build'}:check.status={'timeout':ExecutionStatus.TIMEOUT,'cancelled':ExecutionStatus.CANCELLED,'build':ExecutionStatus.ERROR}[fault]
        elif fault=='signal':check.exit_code=-9
        elif fault=='unknown':check.exit_code=None
        elif fault=='no_tests':check.outcome='not_applicable'
        elif fault=='not_started':check.parameters['test_started']=False
        elif fault=='changed_target':check.parameters['changed_target_files']=['counter.py']
        elif fault=='unknown_integrity':check.parameters.pop('changed_target_files')
        elif fault=='prerequisite':observations[0]['state']['input_valid']=False
        elif fault=='missing':observations[1]['state'].pop('in_range')
        elif fault=='identity':observations[1].pop('operation')
        elif fault=='applicability':plan.monitors[0].applicability_conditions=[Comparison(field='metadata.unknown',value=True)]
        elif fault=='holds':observations[1]['state']['in_range']=True
        elif fault=='parsing':observations.append({'event':'invalid_observation','_ca_observation':{'error':'truncated'}})
        elif fault=='contradiction':observations.append(deepcopy(observations[1]));observations[-1]['state']['in_range']=True
        computed=direct_checks.compute_assessment(state,u,a,plan,check,observations)
        assert not computed['confirmed'] and not computed['reviewed_complete'],fault
    # An independent admitted scenario or checker keeps its debt, without erasing the completed counterexample.
    more=deepcopy(events);more.append({**deepcopy(events[0]),'operation':'second'})
    partial=direct_checks.compute_assessment(e.state,u,a,p,c,more)
    assert partial['confirmed'] and not partial['bounded_complete'] and not partial['reviewed_complete']
    more.append({**deepcopy(events[1]),'operation':'second','state':{'in_range':True}})
    partial=direct_checks.compute_assessment(e.state,u,a,p,c,more)
    assert partial['confirmed'] and not partial['reviewed_complete']  # A holds-only scenario has no failure attribution.
    other=p.model_copy(deep=True)
    other.monitors.append(other.monitors[0].model_copy(update={'id':'other','checker_id':'Other'}))
    other.observable_properties.append(other.observable_properties[0].model_copy(update={'checker_id':'Other'}))
    partial=direct_checks.compute_assessment(e.state,u,a,other,c,events)
    assert partial['properties'][0]['confirmed'] and not partial['properties'][1]['confirmed'] and not partial['reviewed_complete']
    assert (Path(c.stdout).read_bytes(),Path(c.stderr).read_bytes())==raw


def test_assessment_refresh_preserves_unaffected_results(tmp_path,prepared,monkeypatch):
    from consensus_assurance.workflow import direct_checks
    e,u,p=setup(tmp_path,prepared,True)
    artifacts=[save_plan(e,u,p,key) for key in ('first','second')]
    for a in artifacts:
        review(e.state,u,a)
        c=execute(e,a)
        assess(e.state,u,a,p,c,extract_events(c))
    before=e.state.model_copy(deep=True)
    for change in ('source','review','issue','claim','binding','unit'):
        e.state=before.model_copy(deep=True)
        if change=='source':e.state.materials.append(e.state.materials[0].model_copy(update={'id':'additional-source'}))
        elif change=='review':e.state.semantic_reviews[0].items[0].status='disputed'
        elif change=='issue':
            e.state.review_issues.append(ReviewIssue(review_id='challenge',target_id=artifacts[0].id,target_version=1,
                aspect='checker_correspondence',source_ids=u.audit_question.source_ids,explanation='Return boundary remains disputed',
                disposition='investigation',reason='Check actual observation ownership'))
        else:
            objects = {'claim':e.state.claims,'binding':e.state.bindings,'unit':e.state.units}[change]
            selected = {'claim':p.claim_id,'binding':u.binding_ids[0],'unit':u.id}[change]
            next(o for o in objects if o.id==selected).version+=1
        parsed=[]
        def events(check):
            parsed.append(check.direct_check_id)
            return extract_events(check)
        monkeypatch.setattr(direct_checks,'extract_events',events)
        direct_checks.refresh_assessments(e.state,{a.id for a in artifacts},before=before)
        semantic = change in {'claim','binding','unit'}
        assert parsed==([] if change=='source' else [a.id for a in artifacts] if semantic else [artifacts[0].id])
        records={r['direct_check_id']:r for r in e.state.monitor_results}
        assert records[artifacts[0].id]['confirmed']==(change=='source')
        assert records[artifacts[1].id]['confirmed']==(not semantic)
        expected=e.state.model_copy(deep=True)
        direct_checks.refresh_assessments(expected,{a.id for a in artifacts})
        assert expected.monitor_results==e.state.monitor_results
        assert expected.evidence==e.state.evidence and expected.findings==e.state.findings
        if semantic:
            assert all(e.assessment==Assessment.STALE for e in e.state.evidence)
            assert all(f.stage==Investigation.INCONCLUSIVE for f in e.state.findings)


@pytest.mark.parametrize('relationship',['revision','independent','shared_requirement'])
def test_issue_follows_explicit_lineage_or_requirement_not_checker_name(tmp_path,prepared,relationship):
    e,u,p=setup(tmp_path,prepared,True);old=save_plan(e,u,p,'old');review(e.state,u,old)
    e.state.review_issues.append(ReviewIssue(review_id='old',target_id=old.id,target_version=1,aspect='checker_correspondence',source_ids=u.audit_question.source_ids,explanation='Oracle may use the wrong return boundary',disposition='investigation',reason='Must resolve the specific dispute'))
    if relationship=='shared_requirement':e.state.review_issues[0].target_id=p.claim_id
    new=save_plan(e,u,p,'new',previous=old if relationship=='revision' else None);review(e.state,u,new)
    c=execute(e,new);result=assess(e.state,u,new,p,c,extract_events(c))
    assert result['confirmed']==(relationship=='independent')
    assert any('Open review issue' in x and 'wrong return boundary' in x for x in result['blockers'])==(relationship!='independent')


def test_direct_encoding_observation_change_must_be_declared(tmp_path,prepared):
    from consensus_assurance.workflow.encoding import validate_direct_encoding
    e,u,old_plan=setup(tmp_path,prepared);old=save_plan(e,u,old_plan,'observation-old');execute(e,old)
    issue=ReviewIssue(review_id='review',target_id=old.id,target_version=old.version,aspect='checker_correspondence',
        source_ids=u.audit_question.source_ids,explanation='The old observation field is not independent',disposition='blocked',reason='Correct observed input',challenged_components=['observation'])
    e.state.review_issues.append(issue);e.state.active_direct_check_id=old.id
    fixed=old_plan.model_copy(deep=True)
    fixed.harness.source=fixed.harness.source.replace('in_range=0 <= returned <= limit','range_observed=0 <= returned <= limit')
    fixed.harness.semantic_changes.append('Emit the independently computed range observation')
    fixed.observable_properties[0].assertion=Comparison(field='state.range_observed',value=True)
    revision=EncodingRevision(old_direct_check_id=old.id,issue_id=issue.id,source_ids=issue.source_ids,rationale='Use the separately observed result')
    with pytest.raises(ValueError,match='declared'):
        validate_direct_encoding(e.state,old,old_plan,fixed,revision)
    revision.input_changes=['Add an independent range observation to the result event']
    validate_direct_encoding(e.state,old,old_plan,fixed,revision)


@pytest.mark.parametrize('change',['semantic_input','knowledge_challenge'])
def test_changed_interpretation_updates_current_direct_result(tmp_path,prepared,change):
    e,u,p=setup(tmp_path,prepared,True)
    artifact=save_plan(e,u,p,'stale-result');review(e.state,u,artifact)
    check=execute(e,artifact);assert assess(e.state,u,artifact,p,check,extract_events(check))['confirmed']
    original=Path(check.stdout).read_bytes(),Path(artifact.plan_path).read_bytes()
    if change=='semantic_input':
        next(c for c in e.state.claims if c.id==artifact.claim_id).version+=1;e.checkpoint('semantic_input_changed')
    else:
        from consensus_assurance.workflow.audit import accept, Inputs
        from consensus_assurance.workflow.transactions import commit_graph
        from consensus_assurance.core.submissions import ReviewSubmission
        submission=ReviewSubmission(action='review',artifact_id=artifact.id,rationale='New sourced interpretation',
            review_items=[dict(target_id=artifact.id,aspect='checker_correspondence',status='disputed',
                source_ids=u.audit_question.source_ids,rationale='Review the recovered input boundary',
                counterevidence=['The caller boundary remains outside the observed local operation'])])
        commit_graph(e,'knowledge-update',submission.model_dump(mode='json'),
            lambda proxy:accept(proxy,submission,Inputs(e.root/'draft'),'knowledge-update'))
    current=next(r for r in e.state.monitor_results if r.get('direct_check_id')==artifact.id)
    assert current['outcome']=='violated' and not current['confirmed']
    assert any(('semantic inputs changed' if change=='semantic_input' else 'Open review issue') in reason for reason in current['blockers'])
    assert e.state.evidence[0].assessment==(Assessment.STALE if change=='semantic_input' else Assessment.INCONCLUSIVE)
    assert (Path(check.stdout).read_bytes(),Path(artifact.plan_path).read_bytes())==original
    assert len(e.state.monitor_results)==len(e.state.evidence)==len(e.state.findings)==1


def test_stale_binding_cannot_ground_direct_execution(tmp_path,prepared):
    e,u,p=setup(tmp_path,prepared)
    e.state.bindings[0].snapshot_id='another_snapshot'
    with pytest.raises(ValueError,match='selected source snapshot'):
        validate_plan(e.state,u,p,e.implementation)
    assert not e.state.direct_checks and not e.state.evidence


def test_direct_event_comparison_uses_correlated_raw_fields(tmp_path,prepared):
    e,u,p=setup(tmp_path,prepared)
    source=p.harness.source
    source=source.replace("emit('returned', value=returned, in_range=0 <= returned <= limit)", "emit('returned', value=returned, in_range=0 <= returned <= limit, limit=limit)")
    p.harness.source=source
    p.observable_properties[0].assertion=Comparison(field='state.limit',reference='start.state.limit')
    validate_plan(e.state,u,p,e.implementation)
    a=save_plan(e,u,p,'correlated-fields')
    c=execute(e,a)
    result=assess(e.state,u,a,p,c,extract_events(c))
    assert result['properties'][0]['outcome']=='holds'
    assert result['outcome']=='holds' and not result['confirmed']  # Raw comparison survives an unreviewed conclusion.
    events=extract_events(c)
    assert next(x for x in events if x['event']=='admitted')['state']['value']==3
    assert next(x for x in events if x['event']=='returned')['state']['limit']==3
    p.monitors[0].applicability_conditions=[Comparison(field='state.limit',value=3)]
    with pytest.raises(ValueError,match='cannot filter on the result field'):validate_plan(e.state,u,p,e.implementation)


@pytest.mark.parametrize('change,expected',[
    ('none','holds'),('value','violated'),('identity','unknown'),
    ('missing','unknown'),('ambiguous','unknown'),('order','holds')])
def test_independent_results_correlate_without_filtering_comparison(change,expected):
    from consensus_assurance.workflow.observations import monitor_events
    events=[{'event':kind,'operation':op,'context':0 if kind!='output' else 1,'state':{'value':1}}
        for op in ('a','b') for kind in ('input','ready','output')]
    requirements=[EventRequirement(alias='ready',event='ready'),EventRequirement(alias='input',event='input')]
    prop=ObservableProperty(checker_id='Value',trigger=Comparison(field='event',value='output'),
        assertion=Comparison(field='state.value',reference='input.state.value'),identity_fields=['operation'],description='Actual boundary values')
    monitor=EventMonitor(id='value',checker_id='Value',event='output',binding_ids=[],grounding=Grounding(),admission_alias='input')
    if change=='value':events[2]['state']['value']=2
    if change=='identity':events[0]['operation']='other'
    if change=='missing':del events[2]['operation']
    if change=='ambiguous':events.insert(1,dict(events[0]))
    if change=='order':events[0],events[1]=events[1],events[0]
    result=monitor_events(events,monitor,prop,requirements)
    assert result['outcome']==expected
    if change=='value':assert result['witness_indices']==[2]


@pytest.mark.real
def test_go_json_fragments_preserve_streams_and_report_incomplete_events(tmp_path):
    from consensus_assurance.workflow.observations import monitor_events
    if not shutil.which('go'):pytest.skip('Go unavailable')
    repo=tmp_path/'go-events';repo.mkdir()
    (repo/'go.mod').write_text('module example.test/events\n\ngo 1.22\n')
    (repo/'event_test.go').write_text(r'''package events
import (
    "encoding/json"
    "fmt"
    "strings"
    "testing"
)
func TestLongEvent(t *testing.T) {
    raw, _ := json.Marshal(map[string]any{"event":"result", "operation":"one", "payload":strings.Repeat("x", 8192)})
    fmt.Println("CA_EVENT " + string(raw))
}
''')
    completed=subprocess.run(['go','test','-json','./...'],cwd=repo,text=True,capture_output=True,check=False)
    assert completed.returncode==0,completed.stderr
    outputs=[json.loads(line).get('Output','') for line in completed.stdout.splitlines() if json.loads(line).get('Test')=='TestLongEvent']
    start=next(i for i,text in enumerate(outputs) if 'CA_EVENT ' in text)
    assert len(outputs[start])<8192 and any('\n' in text for text in outputs[start+1:])
    stdout=tmp_path/'go.stdout';stdout.write_text(completed.stdout)
    check=CheckRun(action='direct_check',cwd=str(repo),snapshot_id='snapshot',stdout=str(stdout),status=ExecutionStatus.COMPLETED,exit_code=0)
    events=extract_events(check)
    result=next(e for e in events if e['event']=='result')
    assert len(result['payload'])==8192 and result['_ca_stream']
    ordinary=tmp_path/'ordinary.stdout';ordinary.write_text('CA_EVENT '+json.dumps({k:v for k,v in result.items() if not k.startswith('_ca_')})+'\n')
    plain=extract_events(check.model_copy(update={'stdout':str(ordinary)}))[0]
    assert {k:v for k,v in result.items() if not k.startswith('_ca_')}=={k:v for k,v in plain.items() if not k.startswith('_ca_')}

    envelopes=[
        {'Action':'output','Package':'p','Test':'A','Output':'CA_EVENT {"event":"input","operation":"same","state":{"value":1}}\n'},
        {'Action':'output','Package':'p','Test':'B','Output':'CA_EVENT {"event":"output","operation":"same","state":{"value":1}}\n'},
        {'Action':'output','Package':'p','Test':'C','Output':'CA_EVENT {"event":"truncated","operation":"same"'},
    ]
    interleaved=tmp_path/'interleaved.stdout';interleaved.write_text('\n'.join(json.dumps(x) for x in envelopes)+'\n')
    separated=extract_events(check.model_copy(update={'stdout':str(interleaved)}))
    prop=ObservableProperty(checker_id='Value',trigger=Comparison(field='event',value='output'),assertion=Comparison(field='state.value',reference='input.state.value'),identity_fields=['operation'],description='Same-stream comparison')
    monitor=EventMonitor(id='value',checker_id='Value',event='output',binding_ids=[],grounding=Grounding(),admission_alias='input')
    outcome=monitor_events(separated,monitor,prop,[EventRequirement(alias='input',event='input')])
    assert outcome['outcome']=='unknown' and outcome['missing_indices']==[0,1]
    invalid=next(e for e in separated if e['event']=='invalid_observation')
    assert invalid['_ca_observation']['location']['line']=='end-of-stream'


def test_independent_scenarios_and_revisions_preserve_direct_progress(tmp_path, prepared):
    from consensus_assurance.workflow.direct_checks import obligation_progress
    from consensus_assurance.workflow.audit import sync_progress
    e, unit, plan = setup(tmp_path, prepared)
    assert obligation_progress(e.state, unit) == ({}, unit.obligation_ids)
    first = save_plan(e, unit, plan, 'first')
    assert obligation_progress(e.state, unit)[1] == unit.obligation_ids
    check = execute(e, first)
    assess(e.state, unit, first, plan, check, extract_events(check))
    assert obligation_progress(e.state, unit)[1] == unit.obligation_ids
    review(e.state, unit, first)
    assess(e.state, unit, first, plan, check, extract_events(check))
    assert obligation_progress(e.state, unit)[1] == []
    # A distinct scenario cannot inherit a completed checker with the same name.
    second = save_plan(e, unit, plan, 'second')
    assert obligation_progress(e.state, unit)[1] == unit.obligation_ids
    repaired = save_plan(e, unit, plan, 'repaired', previous=second)
    check2 = execute(e, repaired)
    review(e.state, unit, repaired)
    assess(e.state, unit, repaired, plan, check2, extract_events(check2))
    assert obligation_progress(e.state, unit)[1] == []
    claim = next(c for c in e.state.claims if c.id == plan.claim_id)
    claim.version += 1
    assert obligation_progress(e.state, unit)[1] == unit.obligation_ids
    empty = unit.model_copy(update={'id':'empty', 'obligation_ids':[]})
    e.state.units.append(empty)
    sync_progress(e)
    assert empty.status == 'pending'
