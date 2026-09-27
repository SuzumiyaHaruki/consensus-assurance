"""Tool selection and timeout boundaries, without a real Codex or target process."""
import json
import subprocess
import sys
import time
from pathlib import Path
import pytest
from consensus_assurance.core.config import Config
from consensus_assurance.registry import assemble
from consensus_assurance.workflow.native import write_schemas, method_text, add_support
from consensus_assurance.adapters.runners.process import ProcessRunner
from consensus_assurance.adapters.runners.experiment import install_harness
from consensus_assurance.core.proposals import Harness


def test_default_direct_schema_and_assembly_do_not_load_target_or_model_method(tmp_path):
    code='''import sys
from consensus_assurance.core.config import Config
from consensus_assurance.registry import assemble
backend, agent, verifier, knowledge = assemble(Config(execution_backend="python",agent_backend="mock"))
assert verifier is None
assert not any("plugins.targets" in name for name in sys.modules)
'''
    subprocess.run([sys.executable,'-c',code],check=True)
    write_schemas(tmp_path)
    schemas=json.loads((tmp_path/'product-schemas.json').read_text())
    assert 'ModelDraft' not in schemas and 'Bundle' not in str(schemas)
    paths,text=method_text()
    assert not any('local-modeling' in path for path in paths)
    assert Config().activity_focus==[]


def test_selected_support_is_captured_once_and_cannot_replace_target(tmp_path):
    backend=assemble(Config(execution_backend='hashicorp_raft',agent_backend='mock'))[0]
    harness=Harness(kind='go_test',source='package raft\n',description='Helper input boundary',semantic_changes=[])
    add_support(backend,harness)
    expected=backend.support_files()
    assert harness.files==expected and len(expected)==1
    with pytest.raises(ValueError,match='replace selected'):add_support(backend,harness)
    with pytest.raises(ValueError,match='replace target'):install_harness(tmp_path,backend.harness_filename,harness,expected)
    install_harness(tmp_path,backend.harness_filename,harness,{})
    assert all((tmp_path/name).read_text()==content for name,content in expected.items())
    harness.files[next(iter(expected))]='package raft\n'
    with pytest.raises(ValueError,match='saved artifact'):install_harness(tmp_path,backend.harness_filename,harness,{})


@pytest.mark.parametrize('limit,action,timeout,remaining',[
    ('total_seconds','native_agent',1,.02),('native_turn_timeout','native_agent',.02,None),('action_timeout','direct_check',.02,None)])
def test_actual_limiting_timeout_is_recorded(tmp_path,limit,action,timeout,remaining):
    runner=ProcessRunner(tmp_path)
    if remaining is not None:runner.deadline=time.monotonic()+remaining
    check=runner.run([sys.executable,'-c','import time; time.sleep(2)'],tmp_path,action,'fixture',timeout)
    assert check.status.value=='timeout' and check.parameters['timeout_limit']==limit
    assert Path(check.stdout).exists() and 'killed' in check.reason
