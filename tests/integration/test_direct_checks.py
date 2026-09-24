"""Actual fixture execution, never a real backend or a production correctness claim."""
import json
import shutil
import subprocess
from pathlib import Path
import pytest
from consensus_assurance.core.types import *
from consensus_assurance.core.proposals import *
from consensus_assurance.core.config import Config
from consensus_assurance.registry import assemble
from consensus_assurance.workflow.engine import Engine,FRAMEWORK_REVISION
from consensus_assurance.workflow.budget import BudgetTracker
from consensus_assurance.workflow.direct_checks import save_plan,execute,assess,validate_plan
from consensus_assurance.workflow.review_contract import target_contract
from consensus_assurance.adapters.runners.experiment import extract_events
from consensus_assurance.adapters.storage.snapshot import capture
from regression_support import read_material


def setup(tmp_path,prepared,broken=False):
    repo,state,_,_=prepared
    if broken:(repo/'counter.py').write_text((repo/'counter.py').read_text().replace('return value + 1 if value < limit else 0','return value + 1'))
    state.snapshot=capture(repo);state.mode='real';state.analysis_mode='regression';state.framework_revision=FRAMEWORK_REVISION
    for i,m in enumerate(state.materials):
        if m.file=='counter.py':
            state.materials[i]=read_material(repo,state.snapshot,ReadRequest(file=m.file,start_line=1,end_line=len((repo/m.file).read_text().splitlines()),reason='Actual fixture source'))
            state.materials[i].id=m.id
    state.file_index={}
    for binding in state.bindings:
        binding.snapshot_id=state.snapshot.id;binding.content_digest=state.snapshot.files[binding.file]
        binding.excerpt='\n'.join((repo/binding.file).read_text().splitlines()[binding.start_line-1:binding.end_line])
    unit=state.units[0];unit.binding_ids=['step_binding']
    unit.scope.excluded.append('Cluster-wide consequences outside this finite call')
    basis=Grounding(source_ids=['counter.py:1:10'],expectation_ids=[next(m.id for m in state.materials if m.file=='README.md')],binding_ids=unit.binding_ids,derivation='Finite legal counter inputs must return within capacity',applicability='One local operation, legal initial value and positive capacity')
    for claim in state.claims:
        claim.pending=[];claim.grounding=basis.model_copy(deep=True)
    unit.audit_question=AuditQuestion(question='Does one legal boundary call preserve the range?',importance='Bounded service result',source_ids=basis.source_ids+basis.expectation_ids,
        disposition='ready_for_check',preferred_check='direct_test',event_paths=['legal input -> actual call -> correlated observed return'],trigger_rationale='Observe actual return and independent range predicate')
    cfg=Config(execution_backend='python',allow_experiments=True,allow_agent_materials=True,execution_isolation='workspace')
    state.config=cfg.model_dump(mode='json')
    e=Engine(cfg,tmp_path/'direct',*assemble(cfg),'');e.state=state;e.budget=BudgetTracker(cfg.budget,state)
    shutil.copytree(repo,e.root/'source');state.active_unit_id=unit.id
    source='''import json
from counter import step
value, limit = 3, 3
def emit(event, **values):
    print('CA_EVENT ' + json.dumps({'event': event, 'operation': 'one', 'participant': 'local', 'context': 'configured', 'state': values}))
emit('admitted', value=value, limit=limit, input_valid=0 <= value <= limit and limit > 0)
returned = step(value, limit)
emit('returned', value=returned, in_range=0 <= returned <= limit)
'''
    identities=['operation','participant','context']
    prop=ObservableProperty(checker_id='Range',trigger=Comparison(field='event',value='returned'),assertion=Comparison(field='state.in_range',value=True),identity_fields=identities,description='Observed result remains in the documented capacity range')
    monitor=EventMonitor(id='range',checker_id='Range',event='returned',
        binding_ids=unit.binding_ids,grounding=basis)
    plan=DirectCheckPlan(description='One actual boundary call',claim_id=unit.obligation_ids[0],binding_ids=unit.binding_ids,
        harness=Harness(kind='python',source=source,description='Actual fixture call and independent bound observation',semantic_changes=['Emit actual event values after the target call'],legality=basis,
            prerequisites=[EventRequirement(alias='start',event='admitted',conditions=[Comparison(field='state.input_valid',value=True)])]),
        monitors=[monitor],observable_properties=[prop])
    return e,unit,plan


def review(state,unit,artifact):
    # Explicit controlled semantic input; real execution is tested separately.
    contract=target_contract(state,artifact)
    state.semantic_reviews.append(SemanticReview(task_id='controlled',check_id='controlled',target_versions={artifact.id:artifact.version},context_dependencies={artifact.id:contract},
        material_ids=contract['required_material_ids'],items=[SemanticCheck(target_id=artifact.id,aspect='checker_correspondence',status='no_issue_found',source_ids=contract['required_material_ids'],rationale='The fixture contract, actual call, prerequisites and independent oracle agree within the supplied local scope')],origin='mock'))


def test_completion_is_independent_of_forbidden_response_access(tmp_path):
    from consensus_assurance.workflow.observations import monitor_events
    from consensus_assurance.core.events import match_prerequisites
    import sys
    repo=tmp_path/'isolated';repo.mkdir()
    script='''import json
from future_fixture import consume
class Future:
    def __init__(self): self.error_seen=False; self.response_seen=False; self.bad_order=False
    def Error(self): self.error_seen=True; return RuntimeError("failed")
    def Response(self): self.bad_order=not self.error_seen; self.response_seen=True; return object()
def emit(name, **values):
    print("CA_EVENT " + json.dumps({"event":name,"operation":"one","participant":"local","context":"failed future","state":values}))
future=Future()
emit("admitted",ready=True)
consume(future)
emit("completed",done=True,valid=future.error_seen and not future.bad_order and not future.response_seen)
'''
    requirements=[EventRequirement(alias='start',event='admitted',conditions=[Comparison(field='state.ready',value=True)])]
    prop=ObservableProperty(checker_id='Order',trigger=Comparison(field='event',value='completed'),assertion=Comparison(field='state.valid',value=True),identity_fields=['operation','participant','context'],description='Failed completion is handled without consuming an invalid response')
    monitor=EventMonitor(id='order',checker_id='Order',event='completed',binding_ids=['fixture'],grounding=Grounding())
    for source,expected in [('def consume(future):\n    if future.Error() is None: future.Response()\n','holds'),('def consume(future):\n    future.Response()\n    future.Error()\n','violated')]:
        (repo/'future_fixture.py').write_text(source)
        completed=subprocess.run([sys.executable,'-c',script],cwd=repo,capture_output=True,text=True,timeout=5,check=True)
        events=[json.loads(line.removeprefix('CA_EVENT ')) for line in completed.stdout.splitlines()]
        assert match_prerequisites(events,requirements)['status']=='matched'
        assert monitor_events(events,monitor,prop,requirements)['outcome']==expected
    assert monitor_events(events[:1],monitor,prop,requirements)['outcome']=='unknown'
    missing=events[1].copy();missing.pop('operation')
    assert monitor_events([events[0],missing],monitor,prop,requirements)['outcome']=='unknown'


@pytest.mark.parametrize('eligible,success,expected',[(False,False,'holds'),(False,True,'violated'),(True,False,'unknown'),(True,True,'unknown')])
def test_necessary_support_oracle_does_not_require_sufficient_completion(eligible,success,expected):
    from consensus_assurance.workflow.observations import monitor_events
    requirements=[EventRequirement(alias='input',event='admitted')]
    prop=ObservableProperty(checker_id='Support',trigger=Comparison(field='event',value='returned'),
        assertion=Comparison(field='state.success',value=False),identity_fields=['operation','context'],
        description='Success requires eligible support')
    monitor=EventMonitor(id='support',checker_id='Support',event='returned',binding_ids=['fixture'],grounding=Grounding(),
        applicability_conditions=[Comparison(field='state.eligible_support',value=False)])
    events=[{'event':'admitted','operation':'one','context':'fixed','state':{'eligible_support':eligible}},
        {'event':'returned','operation':'one','context':'fixed','state':{'eligible_support':eligible,'success':success}}]
    assert monitor_events(events,monitor,prop,requirements)['outcome']==expected
    if not eligible:
        assert monitor_events(events[:1],monitor,prop,requirements)['outcome']=='unknown'
        assert monitor_events([events[0],{k:v for k,v in events[1].items() if k!='operation'}],monitor,prop,requirements)['outcome']=='unknown'


@pytest.mark.parametrize('failure',['prerequisite','missing','compile','test_failure','disputed','unreviewed','identity','applicability'])
def test_direct_failure_never_confirms(tmp_path,prepared,failure):
    e,u,p=setup(tmp_path,prepared,True)
    if failure=='prerequisite':p.harness.prerequisites[0].event='not_observed'
    if failure=='missing':p.harness.source=p.harness.source.replace('in_range=0 <= returned <= limit','other=0 <= returned <= limit')
    if failure=='compile':p.harness.source+='\ninvalid python syntax!'
    if failure=='test_failure':p.harness.source+='\nraise AssertionError("Observed result outside range")'
    if failure=='identity':p.harness.source=p.harness.source.replace("'operation': 'one'", "'operation': event")
    if failure=='applicability':p.monitors[0].applicability_conditions=[Comparison(field='metadata.unknown',value=True)]
    a=save_plan(e,u,p,'negative')
    if failure!='unreviewed':review(e.state,u,a)
    if failure=='disputed':e.state.semantic_reviews[0].items[0].status='disputed'
    c=execute(e,a);result=assess(e.state,u,a,p,c,extract_events(c))
    assert not result['confirmed'],result
    assert result['outcome']==('unknown' if failure in {'prerequisite','missing','compile','identity','applicability'} else 'violated'),result
    assert not any(f.level=='implementation_obligation' for f in e.state.findings)


def test_new_direct_artifact_does_not_hide_prior_oracle_dispute(tmp_path,prepared):
    e,u,p=setup(tmp_path,prepared,True);old=save_plan(e,u,p,'old');review(e.state,u,old)
    e.state.review_issues.append(ReviewIssue(review_id='old',target_id=old.id,target_version=1,aspect='checker_correspondence',source_ids=u.audit_question.source_ids,explanation='Oracle may use the wrong return boundary',disposition='investigation',reason='Must resolve the specific dispute'))
    new=save_plan(e,u,p,'new');review(e.state,u,new)
    c=execute(e,new);result=assess(e.state,u,new,p,c,extract_events(c))
    assert not result['confirmed'] and any('Open review issue' in x and 'wrong return boundary' in x for x in result['blockers'])


def test_direct_encoding_observation_change_must_be_declared(tmp_path,prepared):
    from consensus_assurance.workflow.encoding import validate_direct_encoding
    e,u,old_plan=setup(tmp_path,prepared);old=save_plan(e,u,old_plan,'observation-old');execute(e,old)
    issue=ReviewIssue(review_id='review',target_id=old.id,target_version=old.version,aspect='checker_correspondence',
        source_ids=u.audit_question.source_ids,explanation='The old observation field is not independent',disposition='blocked',reason='Correct observed input')
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


def test_changed_semantic_input_stales_current_direct_result(tmp_path,prepared):
    e,u,p=setup(tmp_path,prepared,True);artifact=save_plan(e,u,p,'stale-result');review(e.state,u,artifact)
    check=execute(e,artifact);assert assess(e.state,u,artifact,p,check,extract_events(check))['confirmed']
    candidate=QuestionCandidate(question=u.audit_question,obligation_id=u.obligation_ids[0],status='escalated')
    e.state.question_candidates.append(candidate)
    next(c for c in e.state.claims if c.id==artifact.claim_id).version+=1;e.checkpoint('semantic_input_changed')
    current=next(r for r in e.state.monitor_results if r.get('direct_check_id')==artifact.id)
    assert current['outcome']=='violated' and not current['confirmed']
    assert any('semantic inputs changed' in reason for reason in current['blockers'])
    assert e.state.evidence[0].assessment==Assessment.STALE
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
    monitor=EventMonitor(id='value',checker_id='Value',event='output',binding_ids=[],grounding=Grounding())
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
    monitor=EventMonitor(id='value',checker_id='Value',event='output',binding_ids=[],grounding=Grounding())
    outcome=monitor_events(separated,monitor,prop,[EventRequirement(alias='input',event='input')])
    assert outcome['outcome']=='unknown' and outcome['missing_indices']==[1]
    invalid=next(e for e in separated if e['event']=='invalid_observation')
    assert invalid['_ca_observation']['location']['line']=='end-of-stream'
