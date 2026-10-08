"""Real CLI sandbox and real compilers; never invoke a model endpoint."""
import json
import os
import signal
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import pytest

from baseline import codex, runner
from baseline.__main__ import load_target
from baseline.tests.test_baseline import SESSION, configuration, events


@pytest.fixture(scope="module", params=["go_module", "cargo"])
def environment(request, tmp_path_factory):
    retained = os.environ.get("BASELINE_ACCEPTANCE_DIR")
    # The main Agent deliberately hides host /tmp; real run directories live outside it.
    temporary = None if retained else tempfile.TemporaryDirectory(prefix=".capability-", dir=runner.TASK.parent / "runs")
    tmp_path = Path(retained).resolve() / request.param if retained else Path(temporary.name)
    tmp_path.mkdir(parents=True, exist_ok=True)
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
        config.cargo_dependency_cache_dir = str(cache)
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
    runner.write_json(root / "inputs/implementation.json", runner.implementation_identity(root))
    # Adversarial repository instructions must not be automatically injected.
    (root / "work/AGENTS.md").write_text("METHOD_AND_ANSWER_CANARY_7301")
    client = codex.Codex(config, root, load_target(config), time.monotonic() + 900)
    try:
        client.prepare()
        yield client
    finally:
        client.close()
        if temporary:
            temporary.cleanup()


def sandbox(client, command, name):
    result, text = client.local(["sandbox", "--include-managed-config", "-P", "codex_plain",
                               *codex.options(client.settings), "-C", str(client.work), *command], name, maximum=90)
    stderr = (client.root / "inputs" / name / "stderr.log").read_text()
    return result, text + stderr


@pytest.fixture(params=["baseline", "full_agent", "full_fixed"])
def execution(request, environment, monkeypatch):
    """Call the actual neutral execution entry points without constructing an audit."""
    from consensus_assurance.adapters.agents.backend import CodexAgent
    from consensus_assurance.adapters.runners.go_module import GoModuleBackend
    from consensus_assurance.adapters.runners.cargo import CargoBackend
    from consensus_assurance.adapters.runners.process import ProcessRunner, output
    from consensus_assurance.adapters.runners.experiment import run_experiment
    from consensus_assurance.adapters.storage.files import write_json
    client = environment
    if request.param == "baseline":
        def execute(command, name, timeout=90):
            result, text = client.local(["sandbox", "--include-managed-config", "-P", "codex_plain",
                *codex.options(client.settings), "-C", str(client.work), *command], name, maximum=timeout)
            return result, text + (client.root / "inputs" / name / "stderr.log").read_text()
        return request.param, client.work, execute
    root = client.root.parent / request.param
    root.mkdir(exist_ok=True)
    source = root / "source"
    shutil.copytree(client.root / "source", source, dirs_exist_ok=True)
    shutil.copytree(source, root / "agent-source", dirs_exist_ok=True)
    work = root / "draft"
    shutil.copytree(source, work, dirs_exist_ok=True)
    (work / "tmp").mkdir(exist_ok=True)
    backend = GoModuleBackend() if client.target["execution_backend"] == "go_module" else CargoBackend()
    process_runner = ProcessRunner(root)
    if request.param == "full_agent":
        home = client.home / "full-common-home"
        home.mkdir(exist_ok=True)
        monkeypatch.setenv("CODEX_HOME", str(home))
        monkeypatch.setenv(client.config.credential_name, "profile-probe-canary")
        agent = CodexAgent(client.config.agent_reasoning_effort, client.config.agent_model, client.config.codex_provider, 'single_agent')
        assert agent.probe(process_runner)['available']
        agent.read_only_roots = backend.read_only_roots()
        agent.tool_environment = backend.environment(work)
        if not (root / 'agent-inputs/models.json').exists():
            agent.bind_inputs(root, Path(client.config.repo_path))
        assert (root / 'agent-inputs/models.json').read_bytes() == (client.root / 'inputs/models.json').read_bytes()
        verified, checks = agent.prepare(process_runner, work, 'synthetic')
        assert verified, [(check.action, check.exit_code, check.reason, Path(check.stderr).read_text()[-1000:]) for check in checks]
        # Use the same explicit arguments as the real --ignore-user-config model entry.
        settings = agent.permission_options(root, work) + agent.connection_options(root, sandbox=True)
        environment = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "CODEX_HOME": str(home), "LANG": "C.UTF-8"}
        def execute(command, name, timeout=90):
            if command[0] == "cargo":
                command = [str(backend.cargo), *command[1:]]
            check = process_runner.run([*agent.sandbox_command(root), "sandbox", "-P", "ca_audit", *settings,
                "-C", str(work), *command], work, name, "synthetic", timeout, env=environment)
            return {"status": check.status.value, "exit_code": check.exit_code, **check.parameters}, output(check)
        # These local commands inspect the main entry's effective settings without a model call.
        for name, args in (("features", ["features", "list"]), ("prompt", ["debug", "prompt-input", "Local inspection only."])):
            check = process_runner.run([*agent.sandbox_command(root), *args, *settings], work,
                                       "effective-" + name, "synthetic", 30, env=environment)
            assert check.exit_code == 0, output(check)
    else:
        def execute(command, name, timeout=90):
            if command[0] == "cargo":
                command = [str(backend.cargo), *command[1:]]
            check = run_experiment(process_runner, command, work, "synthetic", timeout, "bwrap",
                                   action=name, adapter=backend, prepared=True)
            return {"status": check.status.value, "exit_code": check.exit_code, **check.parameters}, output(check)
    execute.runner = process_runner
    return request.param, work, execute


def test_real_tools_failure_repair_and_prompt_isolation(environment, execution):
    client = environment
    route, work, execute = execution
    prompt = (client.root / "inputs/prompt-input/stdout.jsonl").read_text()
    assert "METHOD_AND_ANSWER_CANARY_7301" not in prompt and "Available skills" not in prompt
    assert "PERMISSIONS_VERIFIED" in (client.root / "inputs/permission-probe/stdout.jsonl").read_text()
    if client.target["execution_backend"] == "go_module":
        path = work / "sample/ordinary_test.go"
        wrong = 'package sample\nimport "testing"\nfunc TestOrdinary(t *testing.T) { if Add(2,3) != 6 { t.Fatal("observed sum differs") } }\n'
        command = ["go", "test", "./sample"]
        correct = wrong.replace("!= 6", "!= 5")
    else:
        path = work / "tests/ordinary.rs"
        path.parent.mkdir(exist_ok=True)
        wrong = '#[test]\nfn ordinary() { assert_eq!(baseline_smoke::add(2,3), 6); }\n'
        correct = wrong.replace(", 6", ", 5")
        command = ["cargo", "test", "--offline"]
    path.write_text(wrong)
    result, text = execute(command, "intentional-failure")
    assert result["status"] == "completed" and result["exit_code"] != 0, text
    assert "FAIL" in text or "assertion" in text, text
    path.write_text(correct)
    result, text = execute(command, "corrected-test")
    assert result["status"] == "completed" and result["exit_code"] == 0, text
    assert not (client.root / "source" / path.relative_to(work)).exists()


def test_shared_dependencies_are_read_only_and_not_copied(environment):
    client = environment
    if client.target["execution_backend"] == "go_module":
        cache = Path(client.config.go_mod_cache_dir)
        visible = [cache]
        assert client.tool_environment["GOMODCACHE"] == str(cache)
        assert not any((client.work / ".runtime/go-mod").iterdir())
        private = cache.parent / "private-canary"
    else:
        cache = Path(client.config.cargo_dependency_cache_dir)
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


def test_network_capabilities_with_host_success_control(environment, execution):
    from consensus_assurance.adapters.storage.files import write_json
    route, work, execute = execution
    host = socket.socket()
    host.bind(("127.0.0.1", 0))
    host.listen()
    port = host.getsockname()[1]
    with socket.create_connection(("127.0.0.1", port), timeout=2) as control:
        accepted, _ = host.accept()
        with accepted:
            accepted.sendall(b"host-canary")
            assert control.recv(11) == b"host-canary"
    namespace = os.readlink("/proc/self/ns/net")
    script = '''import errno, json, os, pathlib, socket, subprocess, threading
r = {'netns': os.readlink('/proc/self/ns/net'), 'route': pathlib.Path('/proc/net/route').read_text(),
     'ipv6_route': pathlib.Path('/proc/net/ipv6_route').read_text(),
     'pipe': subprocess.check_output(['/bin/sh', '-c', 'printf probe | cat']).decode()}
items=[]
t=threading.Thread(target=lambda:items.append('thread'));t.start();t.join();r['thread']=items==['thread']
try:
    s=socket.socket();s.settimeout(2);s.bind(('127.0.0.1',0));s.listen()
    c=socket.create_connection(s.getsockname(),timeout=2);a,_=s.accept()
    c.sendall(b'probe');first=a.recv(5);a.sendall(b'reply');second=c.recv(5)
    r['local_tcp']=first==b'probe' and second==b'reply'
    c.close();a.close();s.close()
except OSError as e:r.update(local_tcp=False,local_errno=e.errno)
try:
    c=socket.create_connection(('127.0.0.1', PORT),timeout=2);c.close();r['host_reachable']=True
except OSError as e:r.update(host_reachable=False,host_errno=e.errno)
r['environment']={k:os.environ.get(k) for k in ('PATH','GOMODCACHE','GOCACHE','GOPROXY','GOFLAGS','GOWORK','CARGO_HOME','CARGO_TARGET_DIR','CARGO_NET_OFFLINE')}
for key,args in COMMANDS.items():
    if args[0]=='rustc':args[0]=os.environ.get('RUSTC',args[0])
    if args[0]=='cargo' and os.environ.get('RUSTC'):args[0]=str(pathlib.Path(os.environ['RUSTC']).with_name('cargo'))
    r[key]=subprocess.check_output(args,text=True).strip()
print(json.dumps(r))
'''.replace("PORT", str(port)).replace("COMMANDS", repr({"tool": ["go", "version"], "platform": ["uname", "-sm"]} if environment.target["execution_backend"] == "go_module" else {"tool": ["rustc", "--version", "--verbose"], "cargo": ["cargo", "--version"], "platform": ["uname", "-sm"]}))
    try:
        result, text = execute(["python3", "-c", script], "network-capabilities")
    finally:
        host.close()
    assert result["status"] == "completed" and result["exit_code"] == 0, text
    observed = json.loads(text.strip())
    observed.update(host_namespace=namespace, host_success_control=True, execution_path=route)
    write_json(environment.root.parent / (route + "-capabilities.json"), observed)
    assert observed["pipe"] == "probe" and observed["thread"]
    assert not observed["host_reachable"]
    if route == "full_fixed":
        assert observed["local_tcp"] and observed["netns"] != namespace
        assert len(observed["route"].splitlines()) == 1
        assert all(line.split()[-1] == "lo" for line in observed["ipv6_route"].splitlines())
    else:
        # This is a recorded capability gap, not a claim that blocked TCP is adequate.
        assert observed["local_tcp"] is False and observed["local_errno"] in (1, 13)
        assert observed["host_errno"] in (1, 13)


def test_common_effective_settings_and_material_boundaries(environment, execution):
    from consensus_assurance.adapters.storage.files import write_json
    route, work, execute = execution
    if route == 'full_agent':
        root = work.parent
        profile = json.loads((root / 'agent-inputs/runtime-settings.json').read_text())
        assert all(profile[key] == value for key, value in codex.common_settings(environment.config.codex_provider).items())
        logs = [json.loads(p.read_text()) for p in (root / 'logs').glob('*/check.json')]
        feature_record = next(c for c in logs if c['action'] == 'effective-features')
        def features(text):
            return {line.split()[0]:line.split()[-1] for line in text.splitlines() if len(line.split()) >= 3}
        main_features = features(Path(feature_record['stdout']).read_text())
        baseline_features = features((environment.root / 'inputs/features/stdout.jsonl').read_text())
        assert main_features == baseline_features
        for c in logs:
            if c['action'] == 'codex_profile_prompt':
                assert 'Available skills' not in Path(c['stdout']).read_text()
        write_json(root / 'effective-comparison.json', {'features_equal': True, 'features': main_features,
                   'catalog_equal': (root / 'agent-inputs/models.json').read_bytes() == (environment.root / 'inputs/models.json').read_bytes(),
                   'method_schema': 'intentionally different; no parity assertion'})
    private = environment.root.parent / 'private-canary'
    source = environment.root / 'source/fixture.txt' if route == 'baseline' else work.parent / 'agent-source/fixture.txt'
    retained = environment.root / 'turns/permission-canary' if route == 'baseline' else work.parent / 'logs/host-record'
    if route != 'baseline':
        retained.write_text('host evidence')
    script = '''import errno, pathlib
def denied(fn):
    try: fn()
    except OSError as e: assert e.errno in (errno.EACCES,errno.EPERM,errno.EROFS,errno.ENOENT), e
    else: raise AssertionError('Forbidden material access succeeded')
pathlib.Path('neutral-note.txt').write_text('ordinary model-editable notes')
for path in PRIVATE:
    print('READ_CONTROL', path, flush=True)
    denied(lambda: pathlib.Path(path).read_bytes())
for path in PROTECTED:
    print('WRITE_CONTROL', path, flush=True)
    denied(lambda: pathlib.Path(path).open('a'))
print('MATERIAL_BOUNDARIES_VERIFIED')
'''.replace('PRIVATE', repr([str(private), str(environment.root / 'inputs/implementation.json'), str(runner.TASK.parent / 'README.md'), str(runner.TASK.parent / 'runs/2026-10-08_13-11-14-hashicorp_raft-baseline/run.json')])).replace('PROTECTED', repr([str(source), str(retained)]))
    result, text = execute(['python3','-c',script], 'material-boundaries')
    assert result['status'] == 'completed' and result['exit_code'] == 0 and 'MATERIAL_BOUNDARIES_VERIFIED' in text, text


def test_cargo_compiled_seed_is_not_a_dependency_cache(environment):
    if environment.target['execution_backend'] != 'cargo':
        return
    seed = environment.root.parent / 'compiled-seed'
    seed.mkdir()
    (seed / 'manifest.json').write_text('{}')
    config = environment.config.model_copy(update={'cargo_dependency_cache_dir': str(seed)})
    client = codex.Codex(config, environment.root, environment.target, time.monotonic() + 30)
    try:
        with pytest.raises(ValueError, match='compiled seed directory is not a dependency cache'):
            client.prepare()
    finally:
        client.close()


@pytest.mark.parametrize("stop", ["turn_timeout", "total_deadline", "cancelled"])
def test_execution_stops_descendants(environment, execution, stop):
    route, work, execute = execution
    heartbeat = work / ("heartbeat-" + stop)
    child = "import pathlib,time\np=pathlib.Path(" + repr(str(heartbeat)) + ")\nwhile True:\n p.write_text(str(time.monotonic_ns()));time.sleep(.03)"
    script = "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c'," + repr(child) + "]);time.sleep(60)"
    original = environment.deadline
    timer = None
    try:
        if stop == "cancelled":
            # Wait for actual child activity before sending the real cancellation signal.
            def cancel():
                limit = time.monotonic() + 5
                while not heartbeat.exists() and time.monotonic() < limit:
                    time.sleep(.01)
                if heartbeat.exists():
                    os.kill(os.getpid(), signal.SIGINT)
            timer = threading.Thread(target=cancel)
            timer.start()
            timeout = 8
        else:
            timeout = .7
        if stop == "total_deadline" and route == "baseline":
            environment.deadline = time.monotonic() + timeout
            timeout = 8
        elif stop == "total_deadline":
            execute.runner.deadline = time.monotonic() + timeout
            timeout = 8
        try:
            result, _ = execute(["python3", "-c", script], "stop-" + stop, timeout)
        except (TimeoutError, KeyboardInterrupt):
            assert route == "baseline"
        else:
            assert result["status"] == ("cancelled" if stop == "cancelled" else "timeout")
            if stop == "total_deadline":
                assert result["timeout_limit"] == "total_seconds"
        assert heartbeat.exists(), "Child did not start; termination has not been exercised"
        time.sleep(.15)
        last = heartbeat.read_text()
        time.sleep(.2)
        assert heartbeat.read_text() == last, "Descendant continued running after controller stop"
    finally:
        environment.deadline = original
        if timer:
            timer.join(timeout=6)
