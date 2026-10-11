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
    comparison=EventComparison(event='output',identity_fields=['operation'],admission_alias='input',
        assertion=Comparison(field='state.value',reference='input.state.value'))
    outcome=compare_events(separated,comparison,[EventRequirement(alias='input',event='input')])
    assert outcome['outcome']=='unknown' and outcome['missing_indices']==[0,1]
    invalid=next(e for e in separated if e['event']=='invalid_observation')
    assert invalid['_ca_observation']['location']['line']=='end-of-stream'
