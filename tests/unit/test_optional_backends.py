"""Tool selection and timeout boundaries, without a real Codex or target process."""
import ast
import json
import subprocess
import sys
import time
from pathlib import Path
import pytest
from consensus_assurance.core.config import Config
from consensus_assurance.registry import assemble
from consensus_assurance.workflow.audit import write_schemas, method_text, add_support
from consensus_assurance.adapters.runners.process import ProcessRunner
from consensus_assurance.adapters.runners.experiment import install_harness
from consensus_assurance.core.proposals import Harness


def test_default_direct_schema_and_assembly_do_not_load_target_or_model_method(tmp_path):
    root=Path(__file__).resolve().parents[2]/'src/consensus_assurance'
    for package in ('core','workflow'):
        for path in (root/package).rglob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node,ast.ImportFrom):assert 'plugins' not in (node.module or '').split('.')
                if isinstance(node,ast.Import):assert all('plugins' not in a.name.split('.') for a in node.names)
    code='''import sys
from consensus_assurance.core.config import Config
from consensus_assurance.registry import assemble
backend, agent, knowledge = assemble(Config(execution_backend="python",agent_backend="mock"))
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
    ('total_seconds','agent_turn',1,.02),('agent_turn_timeout','agent_turn',.02,None),('action_timeout','direct_check',.02,None)])
def test_actual_limiting_timeout_is_recorded(tmp_path,limit,action,timeout,remaining):
    runner=ProcessRunner(tmp_path)
    if remaining is not None:runner.deadline=time.monotonic()+remaining
    check=runner.run([sys.executable,'-c','import time; time.sleep(2)'],tmp_path,action,'fixture',timeout)
    assert check.status.value=='timeout' and check.parameters['timeout_limit']==limit
    assert Path(check.stdout).exists() and 'killed' in check.reason


def test_retired_tools_cannot_be_requested_or_loaded(tmp_path, monkeypatch):
    from consensus_assurance.core.submissions import AuditSubmission
    from consensus_assurance.cli import load_config
    from consensus_assurance.reporting.chinese import render_report
    from audit_support import engine_for, first, check_step, review_step
    import importlib.abc
    class NoModelModules(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if 'adapters.verifiers' in fullname or fullname.rsplit('.',1)[-1] in {'modeling','artifacts','inputs'}:
                raise AssertionError('Retired module imported: ' + fullname)
    monkeypatch.setattr(sys, 'meta_path', [NoModelModules(), *sys.meta_path])
    monkeypatch.setenv('PATH', str(tmp_path/'no-external-tools'))
    monkeypatch.setenv('TLC_JAR', '/missing/unused.jar')
    assert load_config() == Config()
    for legacy in ({'verifier_backend':'tlc'}, {'verifier_backend':'none'}, {'tlc_jar':'missing'}, {'budget':{'model_checks':1}}):
        with pytest.raises(ValueError, match='no longer supported'):Config.model_validate(legacy)
    with pytest.raises(ValueError):AuditSubmission.model_validate({'action':'model','rationale':'Removed product'})
    paths, method = method_text()
    assert 'local_model' not in method and '- model:' not in method
    e, repo = engine_for(tmp_path, [first, check_step(), review_step()])
    e.config.budget.agent_calls = 3
    state = e.start(repo)
    before = state.model_dump(mode='json')
    assert state.units[0].status == 'checked'
    assert not (e.root/'models').exists() and not (e.root/'model-method.md').exists()
    render_report(state, e.root)
    resumed = e.resume()
    assert len(resumed.direct_checks) == len(before['direct_checks']) == 1
    assert resumed.usage == before['usage']


@pytest.mark.parametrize('selection',[
    {'execution_package':'/tmp'}, {'execution_package':'../outside'}, {'execution_package':'-args'},
    {'execution_package':'./...'}, {'execution_package':'. ./internal/core'}, {'execution_package':'.;true'},
    {'execution_package':'example.org/other'}, {'execution_package':'internal/escape'},
    {'execution_package':'internal/child'}, {'execution_package':'internal/core/value.go'},
    {'files':{'value.go':'helper.go'}}, {'files':{'go.work':'helper.go'}},
    {'files':{'internal/core/go.mod':'helper.go'}},
    {'execution_package':'internal/core','files':{'internal/core/assurance_generated_test.go':'helper.go'}},
    {'files':{'internal/child/helper.go':'helper.go'}}, {'files':{'vendor/modules.txt':'helper.go'}},
])
def test_package_boundaries_match_preflight_and_admission_without_execution(tmp_path,go_module,selection,monkeypatch):
    import shutil
    from consensus_assurance.adapters.runners.go_module import GoModuleBackend
    from consensus_assurance.workflow.audit import validate_submission, Inputs, prepare_submission
    from consensus_assurance.core.submissions import AuditSubmission
    from audit_support import engine_for
    from consensus_assurance.core.types import Analysis
    from consensus_assurance.adapters.storage.snapshot import capture
    from consensus_assurance.workflow.budget import BudgetTracker
    engine,repo=engine_for(tmp_path,[])
    shutil.copytree(go_module,repo,dirs_exist_ok=True)
    nested=repo/'internal/child';nested.mkdir();(nested/'go.mod').write_text('module example.org/child\n')
    (nested/'value.go').write_text('package child\n')
    engine.implementation=GoModuleBackend();engine.config.execution_backend='go_module'
    engine.state=Analysis(mode='mock',config=engine.config.model_dump(mode='json'),snapshot=capture(repo,engine.root/'source'))
    engine.budget=BudgetTracker(engine.config.budget,engine.state)
    shutil.copytree(engine.root/'source',engine.root/'agent-source')
    # Captured snapshots normally exclude links; both validation paths must still reject a damaged source view.
    for folder in ('source','agent-source'):(engine.root/folder/'internal/escape').symlink_to(tmp_path,target_is_directory=True)
    draft=engine.root/'draft';draft.mkdir()
    sub=dict(action='explore',question='Check local placement only',harness_path='check.go',rationale='Boundary control',**selection)
    (draft/'submission.json').write_text(json.dumps(sub));(draft/'check.go').write_text('package service\n')
    (draft/'helper.go').write_text('package service\n')
    monkeypatch.setattr(ProcessRunner,'run',lambda *a,**kw:pytest.fail('Validation cannot execute'))
    saved=engine.state.model_dump(mode='json')
    result=validate_submission(engine.state,engine.root,'submission.json',engine.implementation)
    assert not result['valid'] and result['diagnostics']
    assert engine.state.model_dump(mode='json')==saved
    with pytest.raises(ValueError):prepare_submission(engine,AuditSubmission.model_validate(sub),Inputs(draft),'invalid')
    assert not (engine.root/'experiments').exists() and not engine.state.checks and not engine.state.direct_checks


def test_python_rejects_go_override_and_go_default_path_conflict(tmp_path):
    from consensus_assurance.adapters.runners.python import PythonBackend
    from consensus_assurance.adapters.runners.go_module import GoModuleBackend
    from consensus_assurance.core.config import TargetConfig
    harness=Harness(kind='python',source='print(1)',description='Local check',semantic_changes=[],execution_package='.')
    with pytest.raises(ValueError,match='does not support'):PythonBackend().resolve_harness(harness,tmp_path,{})
    with pytest.raises(ValueError,match='target.harness_path'):
        GoModuleBackend(TargetConfig(execution_package='internal/core',harness_path='assurance_generated_test.go'))
