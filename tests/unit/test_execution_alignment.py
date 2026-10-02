import json
"""Question-directed execution regressions, independent of target answer keys."""



def test_workspace_delta_reconstructs_inputs(tmp_path):
    from consensus_assurance.adapters.storage.workspace_delta import save_delta,restore
    import shutil
    source=tmp_path/'source';source.mkdir();(source/'target.py').write_text('value = 1\n')
    (source/'old.txt').write_text('removed by execution')
    workspace=tmp_path/'experiment/workspace';shutil.copytree(source,workspace)
    (workspace/'generated.py').write_text('from target import value\n')
    (workspace/'old.txt').unlink()
    manifest=save_delta(source,workspace,'fixture')
    restored=restore(source,manifest,tmp_path/'reconstructed')
    assert (restored/'target.py').read_bytes()==(source/'target.py').read_bytes()
    assert (restored/'generated.py').read_bytes()==(workspace/'generated.py').read_bytes()
    assert not (restored/'old.txt').exists()
    assert not (manifest.parent/'files/target.py').exists()


def test_experiment_archives_inputs_separately_from_runtime_outputs(tmp_path):
    import sys,json,shutil
    from consensus_assurance.adapters.runners.experiment import run_experiment
    from consensus_assurance.adapters.runners.process import ProcessRunner
    from consensus_assurance.adapters.storage.workspace_delta import restore
    source=tmp_path/'source';source.mkdir();(source/'counter.py').write_text('value = 7\n')
    workspace=tmp_path/'experiments/one/workspace';shutil.copytree(source,workspace)
    (workspace/'harness.py').write_text("from counter import value\nfrom pathlib import Path\nPath('produced.txt').write_text(str(value))\n")
    check=run_experiment(ProcessRunner(tmp_path),[sys.executable,'harness.py'],workspace,'fixture',10,'workspace')
    before=workspace.parent/'workspace-delta/manifest.json';after=workspace.parent/'workspace-outcome/manifest.json'
    assert check.exit_code==0 and str(before) in check.artifacts and str(after) in check.artifacts
    assert 'produced.txt' not in json.loads(before.read_text())['changed_files']
    assert 'produced.txt' in json.loads(after.read_text())['changed_files']
    reconstructed=restore(source,before,tmp_path/'inputs')
    assert (reconstructed/'harness.py').read_bytes()==(workspace/'harness.py').read_bytes()
    assert not (reconstructed/'produced.txt').exists()


import pytest
from consensus_assurance.core.proposals import Comparison, EventRequirement
from consensus_assurance.workflow.observations import match_prerequisites


def prerequisites():
    return [EventRequirement(alias='start',event='started'),EventRequirement(alias='change',event='context_changed',conditions=[Comparison(field='operation',reference='start.operation'),Comparison(field='participant',reference='start.participant'),Comparison(field='context',op='ne',reference='start.context')]),EventRequirement(alias='end',event='completed',conditions=[Comparison(field='operation',reference='start.operation'),Comparison(field='participant',reference='start.participant'),Comparison(field='context',reference='change.context')])]


def test_event_identity_and_context_cannot_be_spliced():
    events=[{'event':e,'operation':'a','participant':'p','context':c} for e,c in [('started',1),('context_changed',2),('completed',2)]]
    assert match_prerequisites(events,prerequisites())['status']=='matched'
    events[1]['operation']='other'
    assert match_prerequisites(events,prerequisites())['status']=='not_reached'
    events[1]['operation']='a';del events[2]['context']
    assert match_prerequisites(events,prerequisites())['status']=='unknown'


def test_F4_actual_async_order_is_checked(tmp_path):
    import sys
    from consensus_assurance.adapters.runners.process import ProcessRunner
    from consensus_assurance.adapters.runners.experiment import extract_events
    from consensus_assurance.core.events import match_prerequisites
    from consensus_assurance.core.proposals import EventRequirement, Comparison
    runner = ProcessRunner(tmp_path)
    scripts = [
        "import threading,json; started=threading.Event();changed=threading.Event()\n"
        "def emit(e): print('CA_EVENT '+json.dumps({'event':e,'operation':'one'}),flush=True)\n"
        "def worker():\n emit('started'); started.set(); changed.wait(); emit('completed')\n"
        "thread=threading.Thread(target=worker);thread.start();started.wait();emit('context_changed');changed.set();thread.join()\n",
        "import threading,json\n"
        "def emit(e): print('CA_EVENT '+json.dumps({'event':e,'operation':'one'}),flush=True)\n"
        "def worker(): emit('started');emit('completed')\n"
        "emit('context_changed');thread=threading.Thread(target=worker);thread.start();thread.join()\n"
    ]
    outcomes = []
    requirements=[EventRequirement(alias='started',event='started'),
        EventRequirement(alias='context_changed',event='context_changed',conditions=[Comparison(field='operation',reference='started.operation')]),
        EventRequirement(alias='completed',event='completed',conditions=[Comparison(field='operation',reference='context_changed.operation')])]
    for script in scripts:
        check = runner.run([sys.executable,'-c',script],tmp_path,'experiment','fixture',5)
        assert check.exit_code == 0
        outcomes.append(match_prerequisites(extract_events(check),requirements)['status']=='matched')
    assert outcomes == [True, False]


@pytest.mark.parametrize('variation',['same','context','operation','unrelated_event','future'])
def test_R6_consequence_requires_correlated_participants(variation):
    from consensus_assurance.core.events import match_prerequisites
    from consensus_assurance.core.proposals import EventRequirement, Comparison
    requirement=EventRequirement(alias='producer',event='accepted',conditions=[Comparison(field='participant',value='a')])
    events=[{'participant':'a','event':'accepted','operation':'x','context':1},{'participant':'b','event':'returned','operation':'x','context':1}];index=1
    if variation=='context':events[0]['context']=2
    if variation=='operation':events[0]['operation']='y'
    if variation=='unrelated_event':events[0]['event']='unrelated'
    if variation=='future':events.reverse();index=0
    assert (match_prerequisites(events,[requirement],index,['operation','context'])['status']=='matched') is (variation=='same')
