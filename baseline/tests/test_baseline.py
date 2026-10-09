import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from baseline import codex, local_exec, runner
from baseline.__main__ import Config, load_config, load_target, main, read_yaml, validate_selection


SESSION = "00000000-0000-4000-8000-000000000001"
PROJECT = Path(__file__).resolve().parents[2]
RECONNECT_FIXTURE = Path(__file__).parent / "fixtures/recovered_reconnect.jsonl"


def make_repo(path, backend="go_module"):
    path.mkdir()
    files = {"go.mod": "module baseline.local/fixture\n\ngo 1.20\n", "sample/value.go":
             "package sample\nfunc Add(a, b int) int { return a + b }\n"} if backend == "go_module" else {
             "Cargo.toml": '[package]\nname = "baseline-smoke"\nversion = "0.1.0"\nedition = "2021"\n',
             "src/lib.rs": "pub fn add(a: i32, b: i32) -> i32 { a + b }\n"}
    for name, text in {**files, 'fixture.txt': 'synthetic source control'}.items():
        file = path/name; file.parent.mkdir(parents=True, exist_ok=True); file.write_text(text)
    for args in (["init", "-q"], ["add", "."], ["-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                                                 "commit", "-qm", "Synthetic input"]):
        subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)
    return path


def configuration(tmp_path, backend="go_module"):
    repo = make_repo(tmp_path / "repo", backend)
    target = tmp_path / "target.yaml"
    target.write_text(yaml.safe_dump({"execution_backend": backend, "target": {"execution_package": "."},
                                      "directed_question": "DO_NOT_INHERIT", "budget": {"experiments": 1}}))
    return Config(target_config=str(target), repo_path=str(repo), agent_model="deepseek-flash",
                  agent_reasoning_effort="high", codex_provider={"id": "deepseek", "base_url": "https://api.deepseek.com",
                    "env_key": "BASELINE_TEST_CREDENTIAL", "model_catalog_path": str(PROJECT / "configs/providers/deepseek-flash.models.json")},
                  auth_mode="api_key", runs_dir=str(tmp_path / "runs"),
                  allow_agent_materials=True, allow_experiments=True,
                  budget={"total_seconds": 120.0, "agent_calls": 3, "agent_turn_timeout": 30.0})


def events(folder, *, final="Partial handoff.", identity=SESSION, error=None, completed=True, tool_failure=False):
    folder.mkdir(exist_ok=True, parents=True)
    items = [{"type": "thread.started", "thread_id": identity}]
    if tool_failure:
        items.append({"type": "item.completed", "item": {"id": "tool_1", "type": "command_execution",
                      "status": "completed", "exit_code": 1, "aggregated_output": "denied; authentication required; refusal"}})
    if error:
        items.append({"type": "turn.failed", "error": {"message": error}})
    if completed:
        items.append({"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}})
    (folder / "stdout.jsonl").write_text("".join(json.dumps(x) + "\n" for x in items))
    (folder / "stderr.log").write_text("")
    if final is not None:
        (folder / "final.txt").write_text(final)
    return {"status": "completed", "exit_code": 0}


def test_configuration_paths_and_neutral_target(tmp_path):
    c = load_config(PROJECT / "baseline/configs/deepseek.example.yaml")
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
    path.write_text(yaml.safe_dump(c.model_dump()))
    monkeypatch.setattr(runner, "run", lambda *a, **k: pytest.fail("Must not start model run"))
    c.allow_experiments = False
    path.write_text(yaml.safe_dump(c.model_dump()))
    assert main(["run", "--config", str(path)]) == 2


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
    (["completed", "timeout"], "turn_timeout", 2, "report 1"),
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
    assert not (root / "run.json").stat().st_mode & 0o222
    assert (root / f"turns/{turns:04d}/changes/files/report.md").exists()


def test_preparation_counts_and_timeout_uses_minimum(tmp_path, monkeypatch):
    c = configuration(tmp_path)
    c.budget.total_seconds, c.budget.agent_turn_timeout = 10.0, 8.0
    clock = [100.0]
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    class Client(ScriptedClient):
        statuses = ["timeout"]
        def prepare(self):
            clock[0] += 3
            return {}
    result = runner.run(c, load_target(c), client_factory=Client)
    assert Client.instances[-1].calls[0][0] == 7
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
    assert result['stop'] == 'turn_timeout'
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
               "action_timeout": 5, "turn_deadline": time.monotonic() + 10, "run_deadline": time.monotonic() + 20}
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


@pytest.mark.parametrize('basis,value', [('requested',1),('action_timeout',2),('agent_turn_timeout',3),('total_seconds',4),('total_seconds',-1)])
def test_local_execution_limit_selection(monkeypatch, basis, value):
    monkeypatch.setattr(local_exec.time,'monotonic',lambda:100)
    control={'action_timeout':20,'turn_deadline':130,'run_deadline':140}
    if basis != 'requested':control[{'agent_turn_timeout':'turn_deadline','total_seconds':'run_deadline'}.get(basis,basis)] = value + (100 if basis in {'agent_turn_timeout','total_seconds'} else 0)
    assert local_exec.remaining(control, value if basis=='requested' else 99) == (max(0,value),basis)


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
    assert 'baseline/tests/test_fixture.py' not in later['retained_source']
    assert later['retained_source']['src/.env']['record'] is None
    assert len(first['reload_inputs']) == 2
