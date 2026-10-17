import asyncio
import shutil
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from baseline import codex, local_exec, runner
from baseline.__main__ import Config, load_config, load_target, main, read_yaml, validate_selection


from support.baseline import SESSION, PROJECT, make_repo, configuration, events
RECONNECT_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/recovered_reconnect.jsonl"


def test_configuration_paths_and_neutral_target(tmp_path):
    c = load_config(PROJECT / "configs/baseline/deepseek.yaml")
    assert Path(c.target_config) == PROJECT / "configs/targets/hashicorp_raft.yaml"
    assert Path(c.codex_provider.model_catalog_path).read_bytes() == (PROJECT / "configs/providers/deepseek-flash.models.json").read_bytes()
    local = configuration(tmp_path)
    target = validate_selection(local)
    assert "DO_NOT_INHERIT" not in json.dumps(target) and "budget" not in target
    assert "harness_path" not in target
    local.repo_path = None
    with pytest.raises(ValueError, match="repo_path"):
        validate_selection(local)


@pytest.mark.parametrize("update", [{"unknown": True}, {"budget": {"agent_calls": -1}},
    {"budget": {"total_seconds": float("nan")}}, {"allow_experiments": "true"},
    {"codex_provider": {"id": "other", "base_url": "https://example.org", "env_key": "HOME"}},
    {"auth_mode": "api_key", "api_key_env": "HOME"}, {"agent_model": "--bad"}])
def test_invalid_config_rejected(update):
    values = {"target_config": "target.yaml", "agent_model": "chosen-model", "agent_reasoning_effort": "high",
              "auth_mode": "codex_login", **update}
    with pytest.raises(ValueError):
        Config.model_validate(values)


def test_duplicate_and_secret_config_errors(tmp_path, capsys):
    path = tmp_path / "bad.yaml"
    path.write_text("agent_model: a\nagent_model: b\n")
    with pytest.raises(ValueError, match="Duplicate"):
        read_yaml(path)
    path.write_text("target_config: target.yaml\nagent_model: model\nagent_reasoning_effort: high\nauth_mode: codex_login\napi_key: private-value\n")
    assert main(["run", "--config", str(path)]) == 2
    assert "private-value" not in capsys.readouterr().err


def test_no_paid_call_without_authorization(tmp_path, monkeypatch):
    c = configuration(tmp_path)
    path = tmp_path / "local.yaml"
    monkeypatch.setattr(runner, "run", lambda *a, **k: pytest.fail("Must not start model run"))
    c.allow_experiments = False
    path.write_text(yaml.safe_dump(c.model_dump()))
    assert main(["run", "--config", str(path)]) == 2


@pytest.mark.parametrize('custom', [False, True])
def test_client_authentication_keeps_credentials_out_of_tool_environment(tmp_path, monkeypatch, custom):
    config = configuration(tmp_path)
    if not custom:
        config.codex_provider = None
        config.api_key_env = 'BASELINE_NATIVE_TEST_KEY'
    monkeypatch.setattr(codex.shutil, 'which', lambda _: sys.executable)
    monkeypatch.setenv('HTTPS_PROXY', 'http://proxy.example.invalid:7890')
    monkeypatch.setenv('UNRELATED_SECRET', 'private')
    monkeypatch.delenv(config.credential_name, raising=False)
    client = codex.Codex(config, tmp_path/'client', {}, time.monotonic()+10)
    try:
        assert 'HTTPS_PROXY' in client.environment and 'UNRELATED_SECRET' not in client.environment
        with pytest.raises(ValueError, match='Missing credential'):
            client.authenticate()
        monkeypatch.setenv(config.credential_name, 'credential-canary')
        client.authenticate()
        key = config.credential_name if custom else 'CODEX_API_KEY'
        assert client.environment[key] == 'credential-canary'
        assert not {'HTTPS_PROXY', key, 'UNRELATED_SECRET'} & client.tool_environment.keys()
        assert 'credential-canary' not in json.dumps(client.settings)
    finally:
        client.close()


def test_source_capture_commit_cleanliness_and_links(tmp_path):
    repo = make_repo(tmp_path / "repo")
    (repo / "AGENTS.md").write_text("UNTRUSTED")
    (repo / "outside").symlink_to(tmp_path / "private")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=T", "-c", "user.email=t@example.invalid",
                    "commit", "-qm", "Excluded inputs"], check=True)
    out = tmp_path / "source"
    result = runner.capture_source(repo, out, time.monotonic() + 30)
    assert result["commit"] and "go.mod" in result["files"]
    assert set(result["excluded"]) == {"AGENTS.md", "outside"}
    assert not (out / ".git").exists()
    (repo / "fixture.txt").write_text("dirty")
    with pytest.raises(ValueError, match="clean Git"):
        runner.capture_source(repo, tmp_path / "other", time.monotonic() + 30)
    assert (repo / "fixture.txt").read_text() == "dirty"


@pytest.mark.parametrize("kwargs,status", [({}, "completed"), ({"tool_failure": True}, "completed"),
    ({"error": "quota exceeded"}, "external_error"), ({"error": "stream disconnected"}, "external_error"),
    ({"final": "RUN_BLOCKED: Access is unavailable."}, "run_blocked"),
    ({"final": 'The retained output says "I cannot assist with this request."'}, "completed"),
    ({"final": None}, "external_blocker_needs_review"), ({"completed": False}, "external_blocker_needs_review"),
    ({"identity": "00000000-0000-4000-8000-000000000002"}, "session_mismatch")])
def test_native_events_and_only_top_level_errors(tmp_path, kwargs, status):
    result = codex.decode(tmp_path, events(tmp_path, **kwargs), SESSION)
    assert result["status"] == status
    assert result["usage_semantics"] == "unverified_do_not_sum"


@pytest.mark.parametrize("ending,status", [("recovered", "completed"), ("failed", "external_error"),
    ("incomplete", "external_error"), ("nonzero_exit", "external_error")])
def test_reconnect_notification_and_terminal_outcome(tmp_path, ending, status):
    # Excerpt from the 2026-10-08 19:28 HashiCorp run; no model call is replayed.
    items = [json.loads(line) for line in RECONNECT_FIXTURE.read_text().splitlines()]
    session = items[0]["thread_id"]
    result = events(tmp_path)
    if ending == "incomplete":
        items.pop()
    elif ending == "failed":
        items.append({"type": "turn.failed", "error": {"message": "stream disconnected"}})
    elif ending == "nonzero_exit":
        result["exit_code"] = 1
    (tmp_path / "stdout.jsonl").write_text("".join(json.dumps(item) + "\n" for item in items))
    result = codex.decode(tmp_path, result, session)
    assert result["status"] == status
    assert "Reconnecting... 1/5" in result["diagnostic"]["message"]


def test_non_json_and_startup_failure_are_retained(tmp_path):
    result = events(tmp_path)
    with (tmp_path / "stdout.jsonl").open("a") as stream:
        stream.write("broken event\n")
    decoded = codex.decode(tmp_path, result)
    assert decoded['status'] == 'completed' and decoded['invalid_jsonl_lines'] == 1
    (tmp_path / "stdout.jsonl").write_text("")
    (tmp_path / "stderr.log").write_text("authentication required")
    result = codex.decode(tmp_path, {"status": "completed", "exit_code": 1})
    assert result["status"] == "external_error" and result["failure_kind"] == "login_required"


@pytest.mark.parametrize('identity', ['opaque/session-1', '', None, 42])
def test_session_identity_is_opaque_and_exact(tmp_path, identity):
    result = codex.decode(tmp_path, events(tmp_path, identity=identity), identity)
    assert result['status'] == ('completed' if identity == 'opaque/session-1' else 'external_blocker_needs_review')


@pytest.mark.parametrize('event', [{'type':'refusal'}, {'type':'item.completed','item':{'type':'refusal'}}])
def test_native_refusal_still_stops_a_completed_turn(tmp_path, event):
    result = events(tmp_path)
    with (tmp_path/'stdout.jsonl').open('a') as stream:stream.write(json.dumps(event)+'\n')
    assert codex.decode(tmp_path, result)['status'] == 'external_blocker_needs_review'


@pytest.mark.parametrize('identity,previous,completed,event,allowed', [
    (SESSION, None, False, None, True), (SESSION, SESSION, True, None, True),
    ('changed', SESSION, False, None, False), ('', None, False, None, False),
    (SESSION, SESSION, False, {'type':'thread.started','thread_id':'changed'}, False),
    (SESSION, SESSION, False, {'type':'turn.failed','error':{'message':'service error'}}, False),
    (SESSION, SESSION, True, {'type':'refusal'}, False),
    (SESSION, SESSION, False, {'type':'error','message':'permission denied'}, False),
])
def test_timeout_continuation_checks_identity_and_failures(tmp_path, identity, previous, completed, event, allowed):
    result = events(tmp_path, identity=identity, completed=completed, final=None, tool_failure=True)
    if event:
        with (tmp_path/'stdout.jsonl').open('a') as stream:stream.write(json.dumps(event)+'\n')
    result.update(status='timeout', exit_code=-9)
    decoded = codex.decode(tmp_path, result, previous)
    assert decoded['status'] == 'timeout' and decoded['continuable_timeout'] is allowed


@pytest.mark.parametrize('shape', ['absent','empty','nonempty','file','symlink','dangling','fifo','denied'])
def test_reserved_paths_remove_only_real_empty_directories(tmp_path, monkeypatch, shape):
    client = object.__new__(codex.Codex)
    client.work, client.config = tmp_path, SimpleNamespace(allow_agent_materials=False)
    path = tmp_path/'.codex'
    (tmp_path/'.agents').mkdir()
    if shape in {'empty','nonempty','denied'}:path.mkdir()
    if shape == 'nonempty':(path/'config.toml').write_text('retained')
    if shape == 'file':path.write_text('retained')
    if shape in {'symlink','dangling'}:path.symlink_to(tmp_path/('.agents' if shape=='symlink' else 'missing'))
    if shape == 'fifo':os.mkfifo(path)
    if shape == 'denied':
        monkeypatch.setattr(Path, 'rmdir', lambda p: (_ for _ in ()).throw(PermissionError(13, 'Permission denied', str(p))))
    before = path.lstat() if shape != 'absent' else None
    with pytest.raises(ValueError, match='Model transmission' if shape in {'absent','empty'} else 'Pre-invocation reserved path') as error:
        client.turn(tmp_path/'turn', 'Unused', 1, None)
    if shape in {'absent','empty'}:assert not path.exists() and not (tmp_path/'.agents').exists()
    else:
        assert str(path) in str(error.value) and path.lstat() == before
        if shape == 'nonempty':assert (path/'config.toml').read_text() == 'retained'


def test_delta_deletions_modes_and_unsafe_files(tmp_path):
    work, changes = tmp_path / "work", tmp_path / "changes"
    work.mkdir()
    (work / "keep").write_text("before")
    (work / "gone").write_text("gone")
    previous, _ = runner.file_inventory(work)
    (work / "keep").write_text("after")
    (work / "keep").chmod(0o755)
    (work / "gone").unlink()
    (work / "escape").symlink_to("/etc/passwd")
    (work / ".env").write_text("excluded")
    (work / ".runtime").mkdir()
    (work / ".runtime/cache").write_text("cache")
    os.link(work / "keep", work / "hardlink")
    result = runner.save_changes(work, changes, previous)
    manifest = json.loads((changes / "manifest.json").read_text())
    assert not result and set(manifest["excluded"]) == {"escape", ".env", ".runtime", "hardlink", "keep"}
    (work / "hardlink").unlink()
    result = runner.save_changes(work, tmp_path / "safe", previous)
    assert result["keep"]["mode"] == 0o755
    assert (tmp_path / "safe/files/keep").read_text() == "after"


class ScriptedClient:
    instances = []
    statuses = ["completed", "completed", "completed"]

    def __init__(self, config, root, target, deadline):
        self.root, self.calls = root, []
        self.instances.append(self)

    def prepare(self):
        return {"test_double": True}

    def authenticate(self):
        pass

    def close(self):
        pass

    def turn(self, folder, prompt, timeout, session):
        state = json.loads((self.root / "run.json").read_text())
        assert state["stop"] == "running" and state["phase"] == "model_audit"
        index = len(self.calls)
        if index:
            assert session == SESSION
            assert (self.root / "work/note.txt").read_text() == "first turn"
            assert "Continue the same authorized audit" in prompt
        else:
            assert session is None
            (self.root / "work/note.txt").write_text("first turn")
            for name, text in {'reproduction/check.py':'print(42)\n', 'reproduction/output.txt':'42\n', '.runtime/cache':'disposable'}.items():
                path = self.root/'work'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
            assert 'work/.runtime is disposable' in prompt
        self.calls.append((timeout, session))
        (self.root / "work/report.md").write_text(f"report {index + 1}")
        result = events(folder, tool_failure=True)
        result["status"] = self.statuses[index]
        return codex.decode(folder, result, session)


@pytest.mark.parametrize("statuses,stop,turns,report", [
    (["completed"] * 3, "agent_call_limit", 3, "report 3"),
    (["completed", "timeout", "completed"], "agent_call_limit", 3, "report 3"),
    (["completed", "cancelled"], "cancelled", 2, "report 1"),
    (["external_error"], "external_error", 1, None)])
def test_continuing_run_and_completed_report_retention(tmp_path, statuses, stop, turns, report):
    c = configuration(tmp_path)
    class Client(ScriptedClient):
        pass
    Client.statuses = statuses
    result = runner.run(c, load_target(c), client_factory=Client)
    assert result["stop"] == stop
    root = Path(result["run_dir"])
    record = json.loads((root / "run.json").read_text())
    assert len(record["turns"]) == turns
    if report:
        assert (root / record["last_completed_report"]).read_text() == report
    else:
        assert record["last_completed_report"] is None
    assert not (root / "work/.git").exists()
    assert not (root / 'work/.runtime').exists()
    for name in ('check.py','output.txt'):
        assert (root/'work/reproduction'/name).read_bytes() == (root/'turns/0001/changes/files/reproduction'/name).read_bytes()
    assert (root / "run.json").stat().st_mode & 0o200
    assert (root / f"turns/{turns:04d}/changes/files/report.md").exists()


@pytest.mark.parametrize('during_execution', [False, True])
def test_preparation_counts_and_total_timeout_survives_turn_accounting(tmp_path, monkeypatch, during_execution):
    c = configuration(tmp_path)
    c.budget.total_seconds, c.budget.agent_turn_timeout = 10.0, 8.0
    clock = [100.0]
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    class Client(ScriptedClient):
        statuses = ["timeout"]
        def prepare(self):
            clock[0] += 0 if during_execution else 3
            return {}
        def turn(self, *args):
            result = super().turn(*args)
            if during_execution:
                clock[0] = 110
                result['timeout_limit'] = 'total_seconds'
            return result
    result = runner.run(c, load_target(c), client_factory=Client)
    assert Client.instances[-1].calls[0][0] == (8 if during_execution else 7)
    assert result["stop"] == "total_deadline"


def test_unchanged_report_reuses_completed_delta_before_later_timeout(tmp_path):
    class Client(ScriptedClient):
        statuses = ['completed', 'completed', 'timeout']
        def turn(self, *args):
            result = super().turn(*args)
            if len(self.calls) == 2:
                (self.root/'work/report.md').write_text('report 1')
            return result
    config = configuration(tmp_path)
    result = runner.run(config, load_target(config), client_factory=Client)
    root = Path(result['run_dir'])
    record = json.loads((root/'run.json').read_text())
    assert result['stop'] == 'agent_call_limit'
    assert record['last_completed_report'] == 'turns/0001/changes/files/report.md'
    assert (root/record['last_completed_report']).read_text() == 'report 1'
    assert not (root/'turns/0002/changes/files/report.md').exists()
    assert not list((root/'turns').glob('*/report.md'))
    assert (root/'turns/0003/changes/files/report.md').read_text() == 'report 3'


def test_late_turn_error_keeps_work_and_previous_handoff(tmp_path):
    c = configuration(tmp_path)
    class Client(ScriptedClient):
        def turn(self, folder, prompt, timeout, session):
            if self.calls:
                (self.root / "work/report.md").write_text("unfinished report")
                raise ValueError("unknown native completion shape")
            return super().turn(folder, prompt, timeout, session)
    result = runner.run(c, load_target(c), client_factory=Client)
    root = Path(result["run_dir"])
    assert result["stop"] == "external_blocker_needs_review"
    assert (root / "turns/0001/changes/files/report.md").read_text() == "report 1"
    assert (root / "turns/0002/changes/files/report.md").read_text() == "unfinished report"
    index = (root/'index.md').read_text()
    assert 'turns/0002/result.json' in index
    assert all('turns/0002/'+name not in index for name in ('stdout.jsonl','stderr.log','final.txt'))


def test_check_env_deadline_does_not_mean_verified(tmp_path, monkeypatch):
    c = configuration(tmp_path)
    ticks = iter([100.0])
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: next(ticks, 300.0)))
    result = runner.check_environment(c, load_target(c))
    assert not result["ok"] and result["stop"] == "total_deadline"


def test_stdio_check_timeout_keeps_controller_timeout_and_restores_authorization(tmp_path):
    client = object.__new__(codex.Codex)
    client.prompt_probe = client.dependency_probe = lambda: None
    client.deadline = time.monotonic() + .05
    client.execution_control = {}
    client.control_path = tmp_path/'control.json'
    client.config = SimpleNamespace(allow_agent_materials=False, allow_experiments=False)
    client.mcp_probe = lambda: asyncio.sleep(1)
    with pytest.raises(TimeoutError, match='MCP compatibility check timed out'):
        client.check_environment()
    assert not json.loads(client.control_path.read_text())['allow_experiments']


@pytest.mark.parametrize("exception", [subprocess.TimeoutExpired(["go", "env", "GOROOT"], 30), TimeoutError()])
@pytest.mark.parametrize("elapsed,stop,ok", [(30, "preflight_or_runtime_error", False), (120, "total_deadline", True)])
def test_preparation_timeout_distinguishes_local_limit_from_total_deadline(tmp_path, monkeypatch, exception, elapsed, stop, ok):
    config = configuration(tmp_path)
    clock = [100.0]
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    class Client(ScriptedClient):
        def prepare(self):
            clock[0] += elapsed
            raise exception
    result = runner.run(config, load_target(config), client_factory=Client)
    assert result["stop"] == stop and result["ok"] is ok
    assert result["reason"]
    assert Client.instances[-1].calls == []


@pytest.mark.parametrize("argv,valid", [(["/bin/printf", "[%s]", ""], True), ([""], False), (["/bin/echo", "\0"], False)])
def test_execution_keeps_empty_arguments_but_rejects_invalid_executable_and_nul(tmp_path, monkeypatch, argv, valid):
    # Only argument handling is under test here; real isolation is covered by test_environment.
    monkeypatch.setattr(local_exec, "isolated_command", lambda argv, *args: argv)
    control = {"work": str(tmp_path), "records": str(tmp_path / "executions"), "turn": "arguments",
               "tool_roots": [], "read_only_roots": [], "environment": {}, "allow_experiments": True,
               "action_timeout": 5, "run_deadline": time.monotonic() + 20}
    if valid:
        result = asyncio.run(local_exec.execute(control, {"argv": argv}, "arguments"))
        assert result["status"] == "completed" and result["exit_code"] == 0
        assert result["argv"] == argv and result["stdout"]["preview"] == "[]"
    else:
        with pytest.raises(ValueError, match="nonempty executable.*NUL"):
            asyncio.run(local_exec.execute(control, {"argv": argv}, "arguments"))


def test_tool_arguments_and_directory_boundary(tmp_path):
    for args in ({'argv':[]}, {'argv':[1]}, {'argv':['true'],'env':{}}, {'argv':['true'],'mounts':['/']},
                 {'argv':['true'],'timeout_seconds':0}):
        with pytest.raises(ValueError):local_exec.Arguments.model_validate(args)
    work=tmp_path/'work';work.mkdir();(work/'outside').symlink_to(tmp_path)
    assert local_exec.validate_directory(work,'.') == work
    for relative in ('..',str(work),'outside','missing'):
        with pytest.raises((ValueError, OSError)):local_exec.validate_directory(work,relative)


def test_cargo_compiled_seed_is_not_a_dependency_cache(tmp_path, monkeypatch):
    (tmp_path/'manifest.json').write_text('{}')
    client = object.__new__(codex.Codex)
    client.work, client.target = tmp_path, {'execution_backend': 'cargo'}
    client.config = SimpleNamespace(cargo_dependency_cache_dir=str(tmp_path))
    client.local = lambda *args: ({'status': 'completed', 'exit_code': 0}, 'codex fixture')
    monkeypatch.setattr(codex, 'cargo_tool', lambda: Path('/synthetic/tool/bin/cargo'))
    with pytest.raises(ValueError, match='compiled seed directory is not a dependency cache'):
        client.prepare()


@pytest.mark.parametrize('basis,value', [('requested',1),('action_timeout',2),('total_seconds',4),('total_seconds',-1)])
def test_local_execution_limit_selection(monkeypatch, basis, value):
    monkeypatch.setattr(local_exec.time,'monotonic',lambda:100)
    control={'action_timeout':20,'run_deadline':140}
    if basis != 'requested':control['run_deadline' if basis=='total_seconds' else basis] = value + (100 if basis=='total_seconds' else 0)
    assert local_exec.remaining(control, value if basis=='requested' else 99) == (max(0,value),basis)


@pytest.mark.parametrize('mode', ['completed', 'agent_timeout', 'total_timeout', 'stale_clock', 'stdout_only'])
def test_turn_clock_excludes_only_recorded_execution_and_preserves_deadlines(tmp_path, mode):
    control = tmp_path/'private-control.json'
    clock = tmp_path/'private-clock.json'
    runner.write_json(clock, {'elapsed_seconds':0.0})
    runner.write_json(control, {'run_deadline':time.monotonic() + (.8 if mode=='total_timeout' else 10),
                               'execution_clock_path':str(clock)})
    # This subprocess supplies synthetic service timing; the real MCP boundary is tested separately.
    script = '''import json,time
from pathlib import Path
clock=Path(CLOCK)
data=json.loads(clock.read_text())
started=time.monotonic()
data['active']=[started,started+DURATION]
def save():
    temporary=clock.with_suffix('.tmp')
    temporary.write_text(json.dumps(data))
    temporary.replace(clock)
if MODE=='stdout_only':
    print(json.dumps(data),flush=True)
else:
    save()
time.sleep(5 if MODE in {'stdout_only','stale_clock'} else DURATION)
data={'elapsed_seconds':time.monotonic()-started}
save()
print('EXECUTION_RETURNED',flush=True)
time.sleep(5 if MODE=='agent_timeout' else 0)
'''.replace('CLOCK',repr(str(clock))).replace('DURATION',repr(.3 if mode=='stale_clock' else 1.2)).replace('MODE',repr(mode))
    result=codex.process([sys.executable,'-c',script],tmp_path,tmp_path/'logs',.6,
                         env=os.environ.copy(),execution_control=control)
    assert result['status']==('completed' if mode=='completed' else 'timeout')
    output=(tmp_path/'logs/stdout.jsonl').read_text()
    assert ('EXECUTION_RETURNED' in output)==(mode in {'completed','agent_timeout'})
    if mode!='completed':
        assert result['timeout_limit']==('total_seconds' if mode=='total_timeout' else 'agent_turn_timeout')
    assert result['elapsed_seconds'] < (1.2 if mode in {'total_timeout','stale_clock','stdout_only'} else 2.2)


def test_process_timeout_kills_descendant_and_keeps_bytes(tmp_path):
    script = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); print(p.pid,flush=True); time.sleep(60)"
    result = codex.process([sys.executable, "-c", script], tmp_path, tmp_path / "logs", 0.3, env=os.environ.copy())
    assert result["status"] == "timeout"
    pid = int((tmp_path / "logs/stdout.jsonl").read_text())
    state = Path(f"/proc/{pid}/stat")
    assert not state.exists() or state.read_text().split()[2] == "Z"


def test_process_cancellation_and_credential_redaction(tmp_path):
    script = ("import os,signal,threading,time; from pathlib import Path; from baseline.codex import process; "
              "threading.Timer(.3,lambda:os.kill(os.getpid(),signal.SIGINT)).start(); "
              "r=process(['/bin/sh','-c','echo sensitive-canary; sleep 60'],Path.cwd(),Path('logs'),30,"
              "env=os.environ.copy(),secrets=['sensitive-canary']); print(r['status'])")
    env = {**os.environ, "PYTHONPATH": str(PROJECT) + ":" + str(PROJECT / "src")}
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0 and "cancelled" in result.stdout
    assert (tmp_path / "logs/stdout.jsonl").read_text().strip() == "[REDACTED_CREDENTIAL]"


def test_implementation_identity_preserves_dirty_and_external_source(tmp_path, monkeypatch):
    project = make_repo(tmp_path/'implementation')
    base = project/'baseline'; base.mkdir()
    (base/'runner.py').write_text('initial input\n')
    runner.git(project, 'add', 'baseline')
    runner.git(project, '-c', 'user.name=T', '-c', 'user.email=t@example.invalid', 'commit', '-qm', 'Implementation')
    monkeypatch.setattr(runner, '__file__', str(base/'runner.py'))
    module = sys.modules['consensus_assurance.adapters.storage.snapshot']
    installed = tmp_path/'installed.py'; installed.write_text('external source\n')
    monkeypatch.setattr(module, '__file__', str(installed))
    root = tmp_path/'record'
    first = runner.implementation_identity(root)
    assert not first['execution_inputs_dirty']
    entry = first['retained_source'][module.__name__.replace('.', '/')+'.py']
    assert entry['source'] == str(installed) and (root/entry['record']).read_bytes() == installed.read_bytes()
    (base/'runner.py').write_text('changed input\n')
    (base/'tests').mkdir(); (base/'tests/test_fixture.py').write_text('not a runtime input')
    (project/'src').mkdir(); (project/'src/.env').write_text('private input')
    runner.git(project, 'add', 'baseline')  # Staged edits are still dirty relative to HEAD.
    later = runner.implementation_identity(root/'later')
    assert later['execution_inputs_dirty'] and later['framework_commit'] == first['framework_commit']
    entry = later['retained_source']['baseline/runner.py']
    assert (root/'later'/entry['record']).read_text() == 'changed input\n'
    assert 'tests/baseline/test_fixture.py' not in later['retained_source']
    assert later['retained_source']['src/.env']['record'] is None
    assert len(first['reload_inputs']) == 2


def test_fixed_submodules_are_shared_and_fail_closed(tmp_path):
    from consensus_assurance.adapters.storage.snapshot import capture
    repo = make_repo(tmp_path/'repo')
    child = make_repo(repo/'nested')
    runner.git(repo, 'add', 'nested')
    runner.git(repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'Fixed child')
    expected = runner.git(child, 'rev-parse', 'HEAD').decode().strip()
    baseline = runner.capture_source(repo, tmp_path/'baseline', time.monotonic()+30)
    ca = capture(repo, tmp_path/'ca')
    assert ca.submodules == baseline['submodules'] == {'nested': expected}
    assert (tmp_path/'ca/nested/go.mod').read_bytes() == (tmp_path/'baseline/nested/go.mod').read_bytes()
    assert not (tmp_path/'ca/nested/.git').exists() and not (tmp_path/'baseline/nested/.git').exists()
    runner.git(child, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '--allow-empty', '-qm', 'Mismatch')
    for call in [lambda:capture(repo), lambda:runner.capture_source(repo,tmp_path/'bad',time.monotonic()+30)]:
        with pytest.raises(ValueError, match='Submodule nested: expected .*actual'):call()
    shutil.rmtree(child)
    for call in [lambda:capture(repo), lambda:runner.capture_source(repo,tmp_path/'missing',time.monotonic()+30)]:
        with pytest.raises(ValueError, match='nested.*missing/uninitialized'):call()
