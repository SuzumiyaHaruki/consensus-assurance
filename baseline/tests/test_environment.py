"""Real CLI sandbox and real compilers; never invoke a model endpoint."""
import json
import shutil
import time
from pathlib import Path

import pytest

from baseline import codex, runner
from baseline.__main__ import load_target
from baseline.tests.test_baseline import SESSION, configuration, events


@pytest.fixture(params=["go_module", "cargo"])
def environment(request, tmp_path):
    required = ["codex", "bwrap", "go" if request.param == "go_module" else "cargo"]
    missing = [name for name in required if not shutil.which(name)]
    if missing:
        pytest.skip("Missing real local tools: " + ", ".join(missing))
    config = configuration(tmp_path, request.param)
    cache = tmp_path / "dependency-cache"
    if request.param == "go_module":
        config.go_mod_cache_dir = str(cache)
        folders = [cache]
    else:
        config.cargo_seed_cache_dir = str(cache)
        folders = [cache / name for name in ("registry", "git")]
    for folder in folders:
        folder.mkdir(parents=True)
        (folder / "writable-host-canary").write_text("dependency canary")
    (tmp_path / "private-canary").write_text("private")
    if request.param == "cargo":
        (cache / "credentials.toml").write_text("private")
    root = tmp_path / "run"
    for name in ("source", "inputs", "turns"):
        (root / name).mkdir(parents=True)
    runner.capture_source(config.repo_path, root / "source", time.monotonic() + 30)
    shutil.copytree(root / "source", root / "work")
    runner.git(root / "work", "-c", "init.templateDir=", "init")
    (root / "inputs/task.md").write_bytes(runner.TASK.read_bytes())
    # Adversarial repository instructions must not be automatically injected.
    (root / "work/AGENTS.md").write_text("METHOD_AND_ANSWER_CANARY_7301")
    client = codex.Codex(config, root, load_target(config), time.monotonic() + 180)
    try:
        client.prepare()
        yield client
    finally:
        client.close()


def sandbox(client, command, name):
    result, text = client.local(["sandbox", "--include-managed-config", "-P", "codex_plain",
                               *codex.options(client.settings), "-C", str(client.work), *command], name, maximum=90)
    stderr = (client.root / "inputs" / name / "stderr.log").read_text()
    return result, text + stderr


def test_real_tools_failure_repair_and_prompt_isolation(environment):
    client = environment
    prompt = (client.root / "inputs/prompt-input/stdout.jsonl").read_text()
    assert "METHOD_AND_ANSWER_CANARY_7301" not in prompt and "Available skills" not in prompt
    assert "PERMISSIONS_VERIFIED" in (client.root / "inputs/permission-probe/stdout.jsonl").read_text()
    if client.target["execution_backend"] == "go_module":
        path = client.work / "sample/ordinary_test.go"
        wrong = 'package sample\nimport "testing"\nfunc TestOrdinary(t *testing.T) { if Add(2,3) != 6 { t.Fatal("observed sum differs") } }\n'
        command = ["go", "test", "./sample"]
        correct = wrong.replace("!= 6", "!= 5")
    else:
        path = client.work / "tests/ordinary.rs"
        path.parent.mkdir()
        wrong = '#[test]\nfn ordinary() { assert_eq!(baseline_smoke::add(2,3), 6); }\n'
        correct = wrong.replace(", 6", ", 5")
        command = ["cargo", "test", "--offline"]
    path.write_text(wrong)
    result, text = sandbox(client, command, "intentional-failure")
    assert result["status"] == "completed" and result["exit_code"] != 0, text
    assert "FAIL" in text or "assertion" in text, text
    path.write_text(correct)
    result, text = sandbox(client, command, "corrected-test")
    assert result["status"] == "completed" and result["exit_code"] == 0, text
    assert not (client.root / "source" / path.relative_to(client.work)).exists()


def test_shared_dependencies_are_read_only_and_not_copied(environment):
    client = environment
    if client.target["execution_backend"] == "go_module":
        cache = Path(client.config.go_mod_cache_dir)
        visible = [cache]
        assert client.tool_environment["GOMODCACHE"] == str(cache)
        assert not any((client.work / ".runtime/go-mod").iterdir())
        private = cache.parent / "private-canary"
    else:
        cache = Path(client.config.cargo_seed_cache_dir)
        visible = [client.work / ".runtime/cargo" / name for name in ("registry", "git")]
        assert all(path.is_symlink() and path.resolve() == cache / path.name for path in visible)
        private = cache / "credentials.toml"
    script = """import errno, pathlib
def denied(fn):
    try: fn()
    except OSError as exc:
        assert exc.errno in (errno.EACCES, errno.EPERM, errno.EROFS, errno.ENOENT), exc
    else: raise AssertionError('Forbidden cache access succeeded')
"""
    script += f"for directory in {list(map(str, visible))!r}:\n"
    script += "    path = pathlib.Path(directory) / 'writable-host-canary'\n"
    script += "    assert path.read_text() == 'dependency canary'\n"
    script += "    denied(lambda: path.write_text('changed'))\n"
    script += "    denied(lambda: (path.parent / 'new-file').write_text('created'))\n"
    script += f"denied(lambda: pathlib.Path({str(private)!r}).read_text())\n"
    result, text = sandbox(client, ["python3", "-c", script], "dependency-permissions")
    assert result["status"] == "completed" and result["exit_code"] == 0, text
    assert all((path / "writable-host-canary").read_text() == "dependency canary" for path in visible)


def test_real_catalog_copy_and_native_text_command(environment, monkeypatch):
    client = environment
    original = Path(client.config.codex_provider.model_catalog_path).read_bytes()
    assert (client.root / "inputs/models.json").read_bytes() == original
    captured = []
    def playback(command, cwd, folder, timeout, **kwargs):
        captured.append(command)
        return events(folder)
    monkeypatch.setattr(codex, "process", playback)
    first = client.turn(client.root / "turns/0001", "First ordinary turn", 10, None)
    second = client.turn(client.root / "turns/0002", "Continue", 10, first["session_id"])
    assert second["status"] == "completed"
    assert "resume" in captured[1] and captured[1][-2:] == [SESSION, "-"]
    for command in captured:
        assert "--output-schema" not in command and "--output-last-message" in command
        assert not any("danger-full-access" in x for x in command)


def test_native_openai_connection_and_key_boundary(tmp_path, monkeypatch):
    if not all(shutil.which(name) for name in ("codex", "bwrap", "go")):
        pytest.skip("Codex, Bubblewrap and Go are required")
    config = configuration(tmp_path)
    config.codex_provider = None
    config.agent_model = "gpt-5.4"
    config.api_key_env = "BASELINE_NATIVE_TEST_KEY"
    root = tmp_path / "native"
    for name in ("inputs", "source", "turns"):
        (root / name).mkdir(parents=True)
    runner.synthetic_source(root / "source", "go_module")
    shutil.copytree(root / "source", root / "work")
    (root / "inputs/task.md").write_bytes(runner.TASK.read_bytes())
    client = codex.Codex(config, root, load_target(config), time.monotonic() + 60)
    try:
        client.prepare()
        assert "model_provider" not in client.settings
        assert client.settings["forced_login_method"] == "api"
        monkeypatch.delenv(config.api_key_env, raising=False)
        with pytest.raises(ValueError, match="Missing credential"):
            client.authenticate()
        monkeypatch.setenv(config.api_key_env, "native-test-canary")
        client.authenticate()
        assert client.environment["CODEX_API_KEY"] == "native-test-canary"
        assert config.api_key_env not in client.environment
        assert "native-test-canary" not in json.dumps(client.settings)
    finally:
        client.close()


def test_check_env_runs_no_model_and_retains_real_probes(tmp_path):
    if not all(shutil.which(name) for name in ("codex", "bwrap", "go")):
        pytest.skip("Codex, Bubblewrap and Go are required")
    config = configuration(tmp_path)
    config.allow_agent_materials = config.allow_experiments = False
    result = runner.check_environment(config, load_target(config))
    assert result["ok"], result
    root = Path(result["run_dir"])
    record = json.loads((root / "run.json").read_text())
    assert record["kind"] == "check-env" and record["turns"] == []
    assert (root / "inputs/dependency-probe/result.json").exists()
    assert not (root / "work/.runtime").exists()
