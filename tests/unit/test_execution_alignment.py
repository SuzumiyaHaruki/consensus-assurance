import json
"""Question-directed execution regressions, independent of target answer keys."""
from types import SimpleNamespace
from consensus_assurance.core.types import AuditQuestion, ConstraintSource

from consensus_assurance.workflow.artifacts import validate_bundle
from consensus_assurance.core.proposals import GraphDraft
from test_graph_mutations import controller


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
