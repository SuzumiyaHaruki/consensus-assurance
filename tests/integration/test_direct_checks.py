import json
import shutil
import subprocess
from pathlib import Path
import pytest
from consensus_assurance.core.types import *
from consensus_assurance.adapters.runners.experiment import extract_events

@pytest.mark.real
def test_go_json_fragments_preserve_streams_and_report_incomplete_events(tmp_path):
    from consensus_assurance.workflow.observations import compare_events
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
    raw, _ := json.Marshal(map[string]any{"event":"result", "operation":"one", "t_ms":1300, "payload":strings.Repeat("x", 8192)})
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
    assert result['t_ms']==1300
    completing_line=result['_ca_observation']['location']['line']
    assert result['_ca_observation']['runner_time']==json.loads(completed.stdout.splitlines()[completing_line-1])['Time']
    ordinary=tmp_path/'ordinary.stdout';ordinary.write_text('CA_EVENT '+json.dumps({k:v for k,v in result.items() if not k.startswith('_ca_')})+'\n')
    plain=extract_events(check.model_copy(update={'stdout':str(ordinary)}))[0]
    assert {k:v for k,v in result.items() if not k.startswith('_ca_')}=={k:v for k,v in plain.items() if not k.startswith('_ca_')}
    assert 'runner_time' not in plain['_ca_observation']

    envelopes=[
        {'Action':'output','Package':'p','Test':'A','Output':'CA_EVENT {"event":"input","operation":"same","state":{"value":1}}\n'},
        {'Action':'output','Package':'p','Test':'B','Output':'CA_EVENT {"event":"output","operation":"same","state":{"value":1}}\n'},
        {'Action':'output','Package':'p','Test':'C','Output':'CA_EVENT {"event":"truncated","operation":"same"'},
    ]
    interleaved=tmp_path/'interleaved.stdout';interleaved.write_text('\n'.join(json.dumps(x) for x in envelopes)+'\n')
    separated=extract_events(check.model_copy(update={'stdout':str(interleaved)}))
    comparison=EventComparison(event='output',identity_fields=['operation'],admission_alias='input',
        assertion=Comparison(field='state.value',reference='input.state.value'))
    outcome=compare_events(separated,comparison,[EventRequirement(alias='input',event='input')])
    assert outcome['outcome']=='unknown' and outcome['missing_indices']==[0,1]
    invalid=next(e for e in separated if e['event']=='invalid_observation')
    assert invalid['_ca_observation']['location']['line']=='end-of-stream'


def test_go_event_runner_times_preserve_interleaved_comparisons_and_legacy_output(tmp_path):
    from consensus_assurance.workflow.observations import compare_events
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
