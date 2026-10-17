import json
import sys
from pathlib import Path
import pytest
from consensus_assurance.core.types import ExecutionStatus
from consensus_assurance.adapters.runners.process import ProcessRunner
from consensus_assurance.adapters.storage.files import redact
from consensus_assurance.adapters.storage.snapshot import capture


def test_timeout_and_missing_tool(tmp_path):
    runner = ProcessRunner(tmp_path)
    check = runner.run([sys.executable, "-c", "import time; time.sleep(5)"], tmp_path, "test", "s", .1)
    assert check.status == ExecutionStatus.TIMEOUT
    missing = runner.run(["/does/not/exist"], tmp_path, "test", "s")
    assert missing.status == ExecutionStatus.TOOL_MISSING
    with pytest.raises(ValueError): runner.run([sys.executable], tmp_path.parent, "test", "s")


def test_process_group_cleanup(tmp_path):
    runner = ProcessRunner(tmp_path)
    script = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);print(p.pid,flush=True);time.sleep(30)"
    check = runner.run([sys.executable, "-c", script], tmp_path, "test", "s", .2)
    pid = int(Path(check.stdout).read_text().strip())
    stat = Path(f"/proc/{pid}/stat")
    assert not stat.exists() or stat.read_text().split()[2] == "Z"


def test_secret_redaction():
    assert "abc123456" not in redact('Authorization: Bearer abc123456')
    assert "privatevalue" not in redact('api_key="privatevalue"')


@pytest.mark.parametrize('events,expected', [([], 'not_applicable'), ([{'Action':'run','Test':'TestA'}, {'Action':'skip','Test':'TestA'}], 'not_applicable'), ([{'Action':'run','Test':'TestA'}, {'Action':'pass','Test':'TestA'}], 'tests_passed')])
def test_go_absent_or_skipped_tests_are_not_passed(events, expected):
    import json
    from consensus_assurance.adapters.runners.go_module import GoModuleBackend
    from consensus_assurance.core.types import CheckRun
    check = CheckRun(action='test',cwd='/tmp',snapshot_id='s',status=ExecutionStatus.COMPLETED,exit_code=0)
    GoModuleBackend().parse_test_result(check, '\n'.join(json.dumps(e) for e in events))
    assert check.outcome == expected


@pytest.mark.real
def test_go_cache_reuses_builds_without_reusing_tests_or_exposing_other_runs(tmp_path, go_module):
    import shutil
    from consensus_assurance.adapters.runners.go_module import GoModuleBackend
    from consensus_assurance.adapters.runners.experiment import run_experiment
    if not all(shutil.which(name) for name in ('go', 'bwrap')):pytest.skip('Go and bubblewrap required')
    backend = GoModuleBackend()
    reports = [tmp_path/'baseline/runs/previous/report.md', tmp_path/'runs/previous/report.md']
    for path in reports:
        path.parent.mkdir(parents=True, exist_ok=True);path.write_text('previous research')
    source = '''package service
import ("testing"; "os")
func TestAssuranceCache(t *testing.T) {
    for _, path := range []string{REPORTS} {
        if _, err := os.ReadFile(path); err == nil { t.Fatal("other run became visible") }
    }
    f, err := os.OpenFile("test-executions", os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
    if err != nil { t.Fatal(err) }; defer f.Close(); f.WriteString("x")
    if Step(1, 10) != 2 { t.Fatal("changed source must rebuild") }
}
'''.replace('REPORTS', ','.join(json.dumps(str(p)) for p in reports))
    command = backend.experiment_command();command.insert(2, '-x')
    caches = []
    for group, copies in [('first', 2), ('second', 1)]:
        runner = ProcessRunner(tmp_path/'runs'/group)
        cache = runner.root/'.execution/go-build';caches.append(cache)
        assert not cache.exists()
        for number in range(copies):
            work = runner.root/'experiments'/str(number)/'workspace'
            shutil.copytree(go_module, work)
            (work/'assurance_generated_test.go').write_text(source)
            check = run_experiment(runner, command, work, 'fixture', 120, 'bwrap', adapter=backend)
            assert check.outcome == 'tests_passed', check
            assert check.parameters['go_build_cache'] == str(cache) and any(cache.iterdir())
            assert (work/'test-executions').read_text() == 'x'
            compiled_runtime = any('-p runtime ' in line and '/compile ' in line
                                   for path in (check.stdout, check.stderr) for line in Path(path).read_text().splitlines())
            assert compiled_runtime == (number == 0), 'Fresh cache compiles runtime; later copies reuse it'
        repeated = run_experiment(runner, command, work, 'fixture', 120, 'bwrap', adapter=backend)
        assert repeated.outcome == 'tests_passed' and (work/'test-executions').read_text() == 'xx'
        (work/'value.go').write_text('package service\nfunc Step(value, limit int) int { return 99 }\n')
        changed = run_experiment(runner, command, work, 'fixture', 120, 'bwrap', adapter=backend)
        assert changed.outcome == 'tests_failed', changed
    assert caches[0] != caches[1]
    shutil.rmtree(caches[1]);caches[1].symlink_to(caches[0], target_is_directory=True)
    with pytest.raises(ValueError, match='private directory inside the run'):
        run_experiment(runner, command, work, 'fixture', 120, 'bwrap', adapter=backend)


@pytest.mark.parametrize('version',['1.23.5','1.26.7'])
@pytest.mark.real
def test_go_actual_failure_phases_in_isolated_copy(tmp_path,go_module,monkeypatch,version):
    import os, shutil
    from consensus_assurance.adapters.runners.go_module import GoModuleBackend
    from consensus_assurance.adapters.runners.experiment import run_experiment
    executable=Path.home()/f'go/pkg/mod/golang.org/toolchain@v0.0.1-go{version}.linux-amd64/bin'
    if not (executable/'go').is_file() or not shutil.which('bwrap'):pytest.skip('Installed toolchain or bubblewrap unavailable; no download')
    monkeypatch.setenv('PATH',str(executable)+os.pathsep+os.environ['PATH'])
    workspace=tmp_path/'workspace';shutil.copytree(go_module,workspace)
    backend=GoModuleBackend(timeout=10);runner=ProcessRunner(tmp_path)
    header='package service\nimport "testing"\n'
    cases=[
        ('package_conflict','package wrong\n','build_or_setup','unknown',False),
        ('compile',header+'func TestAssurance(t *testing.T) { undefined() }\n','build_or_setup','unknown',False),
        ('assertion',header+'func TestAssurance(t *testing.T) { t.Log("CA_EVENT {\\"event\\":\\"observed\\"}"); t.Fatal("actual assertion") }\n','test_failure','tests_failed',True),
        ('panic',header+'func TestAssurance(t *testing.T) { panic("actual panic") }\n','panic_unattributed','tests_failed',True),
        ('absent',header+'func TestOther(t *testing.T) {}\n',None,'not_applicable',False),
        ('skip',header+'func TestAssurance(t *testing.T) { t.Skip("explicitly skipped") }\n',None,'not_applicable',True),
        ('literal',header+'func TestAssurance(t *testing.T) { t.Log("panic: build failed") }\n',None,'tests_passed',True),
        ('startup',header+'import "os"\nfunc TestMain(m *testing.M) { os.Exit(3) }\n', 'execution_unclassified','unknown',False),
    ]
    for label,source,failure,outcome,started in cases:
        (workspace/'assurance_generated_test.go').write_text(source)
        check=run_experiment(runner,backend.experiment_command(),workspace,'local-fixture',120,'bwrap',adapter=backend)
        assert check.parameters.get('failure_class')==failure,(version,label,check,Path(check.stderr).read_text())
        assert check.parameters['test_started']==started and check.outcome==outcome,(label,check)
        if failure=='build_or_setup':assert check.status==ExecutionStatus.ERROR
        if label=='package_conflict':assert 'found packages' in Path(check.stderr).read_text()+Path(check.stdout).read_text()
        if label=='assertion':
            from consensus_assurance.adapters.runners.experiment import extract_events
            assert extract_events(check)[0]['event']=='observed'
    # A runner timeout keeps its own boundary; the parser cannot turn it into a test failure.
    (workspace/'assurance_generated_test.go').write_text(header+'import "time"\nfunc TestAssurance(t *testing.T) { time.Sleep(time.Minute) }\n')
    check=run_experiment(runner,backend.experiment_command(),workspace,'local-fixture',.1,'bwrap',adapter=backend)
    assert check.status==ExecutionStatus.TIMEOUT and 'failure_class' not in check.parameters
    assert not (go_module/'assurance_generated_test.go').exists()


@pytest.mark.parametrize('interruption', ['preparation', 'raw_output', 'action_result'])
def test_target_recovery_retains_reservation_and_never_replays_unknown_outcome(tmp_path, monkeypatch, interruption):
    from support.audit import engine_for
    from consensus_assurance.workflow.errors import Blocked
    import consensus_assurance.workflow.engine as module
    engine, repo = engine_for(tmp_path, [])
    engine.start(repo, plan_only=True)
    marker = engine.root / 'target-starts'
    command = [sys.executable, '-c', 'from pathlib import Path; '
               f'p=Path({str(marker)!r}); p.write_text(p.read_text()+"x" if p.exists() else "x")']
    interrupted = False
    checkpoint, write_json, write_text = engine.checkpoint, module.write_json, Path.write_text

    def interrupt_checkpoint(event):
        nonlocal interrupted
        checkpoint(event)
        if interruption == 'preparation' and event == 'action_started' and not interrupted:
            interrupted = True
            raise KeyboardInterrupt('Fixture stops before target start')

    def interrupt_result(path, value):
        nonlocal interrupted
        if interruption == 'action_result' and path.name == 'result.json' and not interrupted:
            interrupted = True
            raise OSError(28, 'Fixture action-result storage failure')
        return write_json(path, value)

    def interrupt_output(path, *args, **kwargs):
        nonlocal interrupted
        if interruption == 'raw_output' and path.name == 'stdout.log' and not interrupted:
            interrupted = True
            raise OSError(28, 'Fixture raw-output storage failure')
        return write_text(path, *args, **kwargs)

    engine.checkpoint = interrupt_checkpoint
    monkeypatch.setattr(module, 'write_json', interrupt_result)
    monkeypatch.setattr(Path, 'write_text', interrupt_output)
    def run():
        return engine.action('experiment_execute', 'experiments',
            lambda: engine.runner.run(command, engine.workspace(), 'experiment', engine.state.snapshot.id),
            {'experiment_id': 'fixture', 'operation_id': 'submitted'})

    with pytest.raises(KeyboardInterrupt if interruption == 'preparation' else OSError):
        run()
    identity = engine.state.pending_action.id
    assert engine.state.usage['experiments'] == 1
    assert marker.exists() == (interruption != 'preparation')
    if interruption == 'raw_output':
        with pytest.raises(Blocked, match='outcome is unknown'):
            run()
        assert engine.state.pending_action.status == 'outcome_unknown'
    else:
        assert run()['exit_code'] == 0
    assert marker.read_text() == 'x'
    assert engine.state.pending_action.id == identity and engine.state.usage['experiments'] == 1


def test_storage_failure_is_not_rejection_or_budget_stop_and_secondary_write_cannot_mask_it(tmp_path, monkeypatch, capsys):
    from support.audit import combined, engine_for
    import consensus_assurance.workflow.audit as audit
    engine, repo = engine_for(tmp_path, [combined])
    write_json, save = audit.write_json, engine.store.save
    failed = False

    def fail_acceptance(path, value):
        nonlocal failed
        if path.name == 'accepted.json':
            failed = True
            raise OSError(28, 'First storage failure')
        return write_json(path, value)

    def fail_checkpoint(state, event):
        if failed:
            raise OSError(5, 'Secondary checkpoint failure')
        return save(state, event)

    monkeypatch.setattr(audit, 'write_json', fail_acceptance)
    monkeypatch.setattr(engine.store, 'save', fail_checkpoint)
    state = engine.start(repo)
    assert 'First storage failure' in state.stop_reason
    assert 'save_acceptance' in state.stop_reason
    assert 'Secondary' not in state.stop_reason and 'budget' not in state.stop_reason.lower()
    assert state.run_stop['reason'] == 'tool_gap'
    assert state.current_submission['phase'] == 'accepted'
    assert not list((engine.root / 'submissions').glob('*/diagnostics.json'))
    assert not state.usage.get('experiments')
    message = capsys.readouterr().err
    assert 'First storage failure' in message and 'semantic_operation_committed' in message


@pytest.mark.parametrize('failure', [None, 'checkpoint', 'cleanup'])
def test_private_build_cleanup_follows_durable_evidence_and_preserves_other_outputs(tmp_path, monkeypatch, failure):
    from support.audit import combined, engine_for
    from consensus_assurance.adapters.runners.cargo_build import cleanup
    engine, repo = engine_for(tmp_path, [combined])
    run, checkpoint = engine.runner.run, engine.checkpoint
    workspace = None

    def prepare_cache(command, cwd, action, *args, **kwargs):
        nonlocal workspace
        if action == 'experiment':
            workspace = cwd
            for directory in ('cargo-target', 'cargo-copy-fixture'):
                path = cwd / '.execution' / directory
                path.mkdir(parents=True)
                (path / 'compiled').write_text('disposable')
            (cwd / '.execution/measurement.txt').write_text('retain')
        return run(command, cwd, action, *args, **kwargs)

    def after_evidence(cwd):
        saved = json.loads((engine.root / 'state.json').read_text())
        assert saved['current_submission']['phase'] == 'executed'
        check = saved['checks'][-1]
        assert (engine.root / 'logs' / check['id'] / 'observations.json').is_file()
        assert (engine.root / 'actions' / check['pending_action_id'] / 'result.json').is_file()
        if failure == 'cleanup':
            raise OSError(13, 'Fixture cache cleanup denied')
        cleanup(cwd)

    def interrupt_checkpoint(event):
        if failure == 'checkpoint' and event == 'audit_execution_completed':
            raise OSError(28, 'Execution checkpoint could not be saved')
        checkpoint(event)

    monkeypatch.setattr(engine.runner, 'run', prepare_cache)
    monkeypatch.setattr(engine.implementation, 'cleanup', after_evidence, raising=False)
    engine.checkpoint = interrupt_checkpoint
    state = engine.start(repo)
    assert len([c for c in state.checks if c.action == 'experiment']) == 1
    assert (workspace / '.execution/measurement.txt').read_text() == 'retain'
    for directory in ('cargo-target', 'cargo-copy-fixture'):
        assert (workspace / '.execution' / directory).exists() == bool(failure)
    if failure == 'cleanup':
        assert any('cleanup denied' in gap for gap in state.gaps)
        assert 'agent_calls budget exhausted' in state.stop_reason
        assert state.checks[-1].outcome == 'tests_passed'


def test_private_build_cleanup_rejects_linked_ancestor(tmp_path):
    from consensus_assurance.adapters.runners.cargo_build import cleanup
    original = tmp_path / 'original' / 'workspace'
    target = original / '.execution/cargo-target'
    target.mkdir(parents=True)
    (tmp_path / 'alias').symlink_to(original.parent, target_is_directory=True)
    with pytest.raises(ValueError, match='linked'):
        cleanup(tmp_path / 'alias' / 'workspace')
    assert target.is_dir()


@pytest.mark.parametrize('raw_receipt', [False, True])
@pytest.mark.real
def test_cargo_completed_receipt_recovers_after_deadline_without_reexecution(tmp_path, rust_workspace, monkeypatch, raw_receipt):
    import shutil
    from support.audit import cargo_engine, combined
    if not shutil.which('cargo') or not shutil.which('bwrap'):
        pytest.skip('Local Cargo and bubblewrap are required; no download')

    def submission(state):
        product, _ = combined(state)
        product['experiment'].update(harness_path='check.rs', requirement=None, anchors=[], comparisons=[],
                                     test_names=['measured'])
        return product, {'check.rs':'#[test] fn measured() { assert_eq!(sample::step(2,3),3); }'}

    engine, repo = cargo_engine(tmp_path, rust_workspace, [submission])
    checkpoint, run = engine.checkpoint, engine.runner.run
    interrupted = False

    def after_result(event):
        nonlocal interrupted
        checkpoint(event)
        if (not raw_receipt and event == 'action_result_saved'
                and engine.state.pending_action.kind == 'experiment_execute' and not interrupted):
            interrupted = True
            raise KeyboardInterrupt('Action result retained')

    def after_raw(*args, **kwargs):
        nonlocal interrupted
        check = run(*args, **kwargs)
        if raw_receipt and check.action == 'experiment' and not interrupted:
            assert check.exit_code == 0, Path(check.stderr).read_text()
            interrupted = True
            raise KeyboardInterrupt('Raw Cargo receipt retained')
        return check

    engine.checkpoint = after_result
    monkeypatch.setattr(engine.runner, 'run', after_raw)
    with pytest.raises(KeyboardInterrupt):
        engine.start(repo)
    action_id = engine.state.pending_action.id
    targets = [path for path in (engine.root / 'logs').glob('*/check.json')
               if json.loads(path.read_text())['action'] == 'experiment']
    assert len(targets) == 1
    check_id = json.loads(targets[0].read_text())['id']
    engine.checkpoint = checkpoint
    engine.state.elapsed_seconds = engine.config.budget.total_seconds
    engine.store.save(engine.state, 'test_deadline_elapsed')
    monkeypatch.setattr(engine.runner, 'run', lambda *args, **kwargs: pytest.fail('Recovery cannot execute a process'))
    state = engine.resume()
    check = next(check for check in state.checks if check.action == 'experiment')
    assert check.id == check_id and check.pending_action_id == action_id
    assert state.usage['experiments'] == 1 and not state.invalidation
    assert state.current_submission['phase'] == 'executed'
    assert (engine.root / 'logs' / check_id / 'observations.json').is_file()
    assert check.parameters['test_selection']['requested'] == ['measured']
    assert check.parameters['test_selection']['observed'] == [{'name':'measured','status':'passed'}]
    if raw_receipt:
        assert check.status == ExecutionStatus.ERROR and check.outcome == 'unknown'
        assert check.parameters['changed_target_files'] is None
    else:
        assert check.outcome == 'tests_passed'
    basis = json.loads(next((engine.root / 'build-inputs/targets').rglob('basis.json')).read_text())
    lock = engine.root / basis['lock']['record']
    lock.write_bytes(lock.read_bytes() + b'\n# changed after execution\n')
    with pytest.raises(ValueError, match='build inputs or tools changed'):
        engine.validate_builds(state.pending_action)


@pytest.mark.real
def test_nested_go_module_replacements_and_execution(tmp_path):
    from consensus_assurance.adapters.runners.go_module import GoModuleBackend
    from consensus_assurance.adapters.runners.experiment import run_experiment, install_harness
    from consensus_assurance.core.types import Harness
    root=tmp_path/'workspace';root.mkdir()
    (root/'go.mod').write_text('module example.org/root\n\ngo 1.20\n')
    (root/'value.go').write_text('package root\nconst Value = 7\n')
    child=root/'child';child.mkdir()
    (child/'go.mod').write_text('module example.org/child\n\ngo 1.20\nrequire example.org/root v0.0.0\nreplace example.org/root => ../\n')
    (child/'value.go').write_text('package child\n')
    files=capture(root).files
    backend=GoModuleBackend()
    harness=Harness(kind='go_test', execution_package='child', description='Local replacement',semantic_changes=[],
        source='package child\nimport("testing"; r "example.org/root")\nfunc TestAssuranceLocal(t *testing.T){if r.Value!=7{t.Fatal(r.Value)}}\n')
    name=backend.resolve_harness(harness,root,files)
    assert name=='child/assurance_generated_test.go'
    install_harness(root,name,harness,files)
    result=run_experiment(ProcessRunner(tmp_path),backend.experiment_command(harness.execution_package,name),root,'local',60,'bwrap',adapter=backend)
    assert result.outcome=='tests_passed',result
    assert result.parameters['module_directory']=='child' and result.parameters['local_modules']==['.','child']
    assert result.command[result.command.index('-C')+1]=='child'
    (child/'go.mod').write_text('module example.org/child\nreplace example.org/root => ../../outside\n')
    with pytest.raises(ValueError,match='escapes captured'):backend.resolve_harness(harness,root,files)
    (child/'go.mod').write_text('module example.org/child\nreplace example.org/root => ../missing\n')
    with pytest.raises(ValueError,match='captured go.mod'):backend.resolve_harness(harness,root,files)
    (child/'go.mod').write_text('module example.org/child\nreplace example.org/root => ../alias\n')
    (root/'alias').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError,match='escapes captured'):backend.resolve_harness(harness,root,files)
    (root/'go.work').write_text('go 1.20\nuse ./child\n')
    with pytest.raises(ValueError,match='workspaces'):backend.resolve_harness(harness,root,files)


def test_experiment_archives_inputs_separately_from_runtime_outputs(tmp_path):
    import shutil
    from consensus_assurance.adapters.runners.experiment import run_experiment
    from consensus_assurance.adapters.storage.workspace_delta import restore
    source=tmp_path/'source';source.mkdir();(source/'counter.py').write_text('value = 7\n')
    (source/'removed.txt').write_text('Removed from the fixed execution inputs')
    workspace=tmp_path/'experiments/one/workspace';shutil.copytree(source,workspace)
    (workspace/'removed.txt').unlink()
    (workspace/'harness.py').write_text("from counter import value\nfrom pathlib import Path\nPath('produced.txt').write_text(str(value))\n")
    check=run_experiment(ProcessRunner(tmp_path),[sys.executable,'harness.py'],workspace,'fixture',10,'workspace')
    before=workspace.parent/'workspace-delta/manifest.json';after=workspace.parent/'workspace-outcome/manifest.json'
    assert check.exit_code==0 and str(before) in check.artifacts and str(after) in check.artifacts
    assert 'produced.txt' not in json.loads(before.read_text())['changed_files']
    assert 'produced.txt' in json.loads(after.read_text())['changed_files']
    reconstructed=restore(source,before,tmp_path/'inputs')
    assert (reconstructed/'harness.py').read_bytes()==(workspace/'harness.py').read_bytes()
    assert (reconstructed/'counter.py').read_bytes()==(source/'counter.py').read_bytes()
    assert not (reconstructed/'removed.txt').exists()
    assert not (before.parent/'files/counter.py').exists()
    assert not (reconstructed/'produced.txt').exists()
