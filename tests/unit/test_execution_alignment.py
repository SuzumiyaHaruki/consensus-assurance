import json
"""Question-directed execution regressions, independent of target answer keys."""
from consensus_assurance.core.types import ConstraintSource

from consensus_assurance.workflow.artifacts import validate_bundle


def test_constraint_cites_material_and_selected_binding(prepared):
    from consensus_assurance.adapters.runners.python import PythonBackend
    _,state,bundle,_=prepared;unit=state.units[0];binding=state.bindings[0]
    bundle.constraints=[ConstraintSource(constraint='Actual step',source_kind='code_observation',source_ids=[binding.material_id],binding_ids=[binding.id],justification='Actual transition source')]
    validate_bundle(state,unit,bundle,PythonBackend())


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
from consensus_assurance.core.proposals import Comparison, EventRequirement, ObservationMap, FieldProjection
from consensus_assurance.workflow.observations import match_prerequisites
from consensus_assurance.adapters.verifiers.trace import project


def prerequisites():
    return [EventRequirement(alias='start',event='started'),EventRequirement(alias='change',event='context_changed',conditions=[Comparison(field='operation',reference='start.operation'),Comparison(field='participant',reference='start.participant'),Comparison(field='context',op='ne',reference='start.context')]),EventRequirement(alias='end',event='completed',conditions=[Comparison(field='operation',reference='start.operation'),Comparison(field='participant',reference='start.participant'),Comparison(field='context',reference='change.context')])]



def test_event_identity_and_context_cannot_be_spliced():
    events=[{'event':e,'operation':'a','participant':'p','context':c} for e,c in [('started',1),('context_changed',2),('completed',2)]]
    assert match_prerequisites(events,prerequisites())['status']=='matched'
    events[1]['operation']='other'
    assert match_prerequisites(events,prerequisites())['status']=='not_reached'
    events[1]['operation']='a';del events[2]['context']
    assert match_prerequisites(events,prerequisites())['status']=='unknown'



def test_projection_of_events_state_and_metadata():
    mapping=ObservationMap(fields=[FieldProjection(model_field='kind',raw_field='event',source='event'),FieldProjection(model_field='ctx',raw_field='context',source='metadata'),FieldProjection(model_field='value',raw_field='value')],required_events=['initial','step'],description='Explicit event projection')
    events=[{'event':e,'metadata':{'context':1},'state':{'value':i}} for i,e in enumerate(['initial','step'])]
    assert project(events,mapping)[1]=={'kind':'step','ctx':1,'value':1}
    del events[1]['metadata']['context']
    with pytest.raises(ValueError,match='missing'): project(events,mapping)
