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

from baseline import codex, runner
from baseline.__main__ import Config, load_config, load_target, main, read_yaml, validate_selection


SESSION = "00000000-0000-4000-8000-000000000001"
PROJECT = Path(__file__).resolve().parents[2]


def make_repo(path, backend="go_module"):
    path.mkdir()
    runner.synthetic_source(path, backend)
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
    assert main(["smoke", "--config", str(path)]) == 2
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
    ({"final": "I cannot assist with this request."}, "external_blocker_needs_review"),
    ({"final": "I’m sorry, but I can’t help with this request."}, "external_blocker_needs_review"),
    ({"final": "I cannot confirm this suspicion yet."}, "completed"),
    ({"final": "我无法确认这个猜测，还需要检查其他路径。"}, "completed"),
    ({"final": "抱歉，无法协助。"}, "external_blocker_needs_review"),
    ({"final": None}, "external_blocker_needs_review"), ({"completed": False}, "external_blocker_needs_review"),
    ({"identity": "00000000-0000-4000-8000-000000000002"}, "session_mismatch")])
def test_native_events_and_only_top_level_errors(tmp_path, kwargs, status):
    result = codex.decode(tmp_path, events(tmp_path, **kwargs), SESSION)
    assert result["status"] == status
    assert result["usage_semantics"] == "unverified_do_not_sum"


def test_non_json_and_startup_failure_are_retained(tmp_path):
    result = events(tmp_path)
    with (tmp_path / "stdout.jsonl").open("a") as stream:
        stream.write("broken event\n")
    assert codex.decode(tmp_path, result)["status"] == "external_blocker_needs_review"
    (tmp_path / "stdout.jsonl").write_text("")
    (tmp_path / "stderr.log").write_text("authentication required")
    result = codex.decode(tmp_path, {"status": "completed", "exit_code": 1})
    assert result["status"] == "external_error" and result["failure_kind"] == "login_required"


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


def test_empty_smoke_handoffs_cannot_pass_compatibility(tmp_path):
    c = configuration(tmp_path)
    class Client(ScriptedClient):
        def turn(self, folder, prompt, timeout, session):
            assert "compatibility" in prompt and "variant\": \"synthetic" in prompt
            self.calls.append((timeout, session))
            return codex.decode(folder, events(folder), session)
    result = runner.run(c, load_target(c), smoke=True, client_factory=Client)
    assert not result["ok"] and result["stop"] == "smoke_call_limit"
    root = Path(result["run_dir"])
    observed = json.loads((root / "inputs/smoke-observations.json").read_text())
    assert observed["observed"]["same_session"] and not observed["complete"]
    record = json.loads((root / "run.json").read_text())
    assert record["config"]["budget"]["agent_calls"] == 2


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
    assert (root / "turns/0001/report.md").read_text() == "report 1"
    assert (root / "turns/0002/changes/files/report.md").read_text() == "unfinished report"


def test_check_env_deadline_does_not_mean_verified(tmp_path, monkeypatch):
    c = configuration(tmp_path)
    ticks = iter([100.0])
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: next(ticks, 300.0)))
    result = runner.check_environment(c, load_target(c))
    assert not result["ok"] and result["stop"] == "total_deadline"


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


def test_cargo_dependency_field_migration(tmp_path):
    c = configuration(tmp_path, 'cargo')
    raw = c.model_dump()
    raw['cargo_seed_cache_dir'] = str(tmp_path / 'old-seed')
    with pytest.raises(ValueError, match='Rename cargo_seed_cache_dir to cargo_dependency_cache_dir'):
        Config.model_validate(raw)
    raw.pop('cargo_seed_cache_dir')
    raw['cargo_dependency_cache_dir'] = str(tmp_path / 'cargo-home')
    assert Config.model_validate(raw).cargo_dependency_cache_dir == raw['cargo_dependency_cache_dir']
    # Historical records remain data; they are not loaded as a new configuration.
    historical = json.loads('{"cargo_seed_cache_dir": "old-cache"}')
    assert historical['cargo_seed_cache_dir'] == 'old-cache'


def test_implementation_identity_tracks_loaded_bytes_and_preserves_start(tmp_path, monkeypatch):
    project = make_repo(tmp_path / 'implementation')
    base = project / 'baseline'
    base.mkdir()
    for name in ('__main__.py', 'runner.py', 'codex.py', 'local_exec.py', 'requirements.txt', 'task.md'):
        (base / name).write_text('initial execution input\n')
    runner.git(project, 'add', 'baseline')
    runner.git(project, '-c', 'user.name=T', '-c', 'user.email=t@example.invalid', 'commit', '-qm', 'Implementation')
    monkeypatch.setattr(runner, '__file__', str(base / 'runner.py'))
    module = sys.modules['consensus_assurance.adapters.storage.snapshot']
    installed = tmp_path / 'installed.py'
    installed.write_text('installed module bytes\n')
    monkeypatch.setattr(module, '__file__', str(installed))
    root = tmp_path / 'record'
    first = runner.implementation_identity(root)
    assert not first['execution_inputs_dirty']
    assert first['inputs'] == runner.implementation_identity(root)['inputs']
    entry = first['inputs'][module.__name__]
    assert entry['path'] == str(installed) and entry['framework_relative_path'] is None
    assert entry['version_basis'].startswith('external installed bytes')
    (base / 'runner.py').write_text('changed execution input\n')
    installed.write_text('changed installed bytes\n')
    (project / 'unrelated.env').write_text('PRIVATE_NOT_AN_EXECUTION_INPUT')
    later = runner.implementation_identity(root / 'later')
    assert later['execution_inputs_dirty'] and later['framework_commit'] == first['framework_commit']
    assert later['inputs']['baseline/runner.py']['sha256'] != first['inputs']['baseline/runner.py']['sha256']
    result = runner.finish_identity(root, first)
    assert not result['inputs_unchanged'] and set(result['changed_inputs']) == {'baseline/runner.py', module.__name__}
    assert first['inputs']['baseline/runner.py']['sha256'] != later['inputs']['baseline/runner.py']['sha256']
    assert all(b'PRIVATE_NOT_AN_EXECUTION_INPUT' not in p.read_bytes() for p in root.rglob('*') if p.is_file())


def test_optional_main_profile_uses_explicit_settings_without_changing_method(tmp_path):
    from consensus_assurance.adapters.agents.backend import CodexAgent, common_settings
    c = configuration(tmp_path)
    legacy = CodexAgent(c.agent_reasoning_effort, c.agent_model, c.codex_provider)
    common = CodexAgent(c.agent_reasoning_effort, c.agent_model, c.codex_provider, 'single_agent')
    assert legacy.profile_settings == {}
    assert common.profile_settings == common_settings(c.codex_provider)
    command = common.connection_options(tmp_path)
    assert 'features.multi_agent=false' in command
    assert 'model_providers.deepseek.stream_idle_timeout_ms=300000' in command
    assert '--output-schema' not in command
    assert not any('network.enabled=true' in value for value in command)
