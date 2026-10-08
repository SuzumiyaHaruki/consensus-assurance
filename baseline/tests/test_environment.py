"""Real CLI sandbox and real compilers; never invoke a model endpoint."""
import json
import asyncio
import os
import signal
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

from baseline import codex, local_exec, runner
from baseline.__main__ import load_target
from baseline.tests.test_baseline import SESSION, configuration, events


toolchains = pytest.mark.parametrize('environment', ['go_module', 'cargo'], indirect=True, scope='module')


@pytest.fixture(scope="module")
def environments():
    with ExitStack() as cleanup:
        yield {}, cleanup


@pytest.fixture(scope="module")
def environment(request, environments):
    clients, cleanup = environments
    backend = getattr(request, 'param', 'go_module')
    if backend in clients:
        return clients[backend]
    retained = os.environ.get("BASELINE_ACCEPTANCE_DIR")
    # The main Agent deliberately hides host /tmp; real run directories live outside it.
    tmp_path = Path(retained).resolve() / backend if retained else Path(cleanup.enter_context(
        tempfile.TemporaryDirectory(prefix=".capability-", dir=runner.TASK.parent / "runs")))
    tmp_path.mkdir(parents=True, exist_ok=True)
    required = ["codex", "bwrap", "go" if backend == "go_module" else "cargo"]
    missing = [name for name in required if not shutil.which(name)]
    if missing:
        pytest.skip("Missing real local tools: " + ", ".join(missing))
    config = configuration(tmp_path, backend)
    cache = tmp_path / "dependency-cache"
    if backend == "go_module":
        config.go_mod_cache_dir = str(cache)
        folders = [cache]
    else:
        config.cargo_dependency_cache_dir = str(cache)
        folders = [cache / name for name in ("registry", "git")]
    for folder in folders:
        folder.mkdir(parents=True)
        (folder / "writable-host-canary").write_text("dependency canary")
    (tmp_path / "private-canary").write_text("private")
    if backend == "cargo":
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
    cleanup.callback(client.close)
    client.prepare()
    clients[backend] = client
    return client


def sandbox(client, command, name):
    result, text = client.local(["sandbox", "--include-managed-config", "-P", "codex_plain",
                               *codex.options(client.settings), "-C", str(client.work), *command], name, maximum=90)
    stderr = (client.root / "inputs" / name / "stderr.log").read_text()
    return result, text + stderr


@asynccontextmanager
async def mcp_session(client, server=None):
    settings = client.mcp_settings
    server = server or StdioServerParameters(command=settings['command'], args=settings['args'], cwd=settings['cwd'],
        env={'PYTHONPATH': str(client.work), 'BASELINE_TEST_KEY': 'must-not-be-inherited'})
    async with stdio_client(server) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            yield session, streams


@pytest.fixture(params=["baseline", "full_agent", "full_fixed", "baseline_mcp"])
def execution(request, environment, monkeypatch):
    """Call the actual neutral execution entry points without constructing an audit."""
    from consensus_assurance.adapters.agents.backend import CodexAgent
    from consensus_assurance.adapters.runners.go_module import GoModuleBackend
    from consensus_assurance.adapters.runners.cargo import CargoBackend
    from consensus_assurance.adapters.runners.process import ProcessRunner, output
    from consensus_assurance.adapters.runners.experiment import run_experiment
    from consensus_assurance.adapters.storage.files import write_json
    client = environment
    if request.param == 'baseline_mcp':
        async def call(command, timeout):
            async with mcp_session(client) as (session, _):
                response = await session.call_tool('isolated_exec', {'argv': command, 'timeout_seconds': float(timeout)})
                assert not response.isError, response
                result = response.structuredContent
                text = Path(result['stdout']['path']).read_text() + Path(result['stderr']['path']).read_text()
                return result, text
        def execute(command, name, timeout=90):
            client.execution_control.update(turn=name, turn_deadline=time.monotonic()+timeout, run_deadline=client.deadline, allow_experiments=True)
            write_json(client.control_path, client.execution_control)
            return asyncio.run(call(command, timeout))
        return request.param, client.work, execute
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


@toolchains
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


@toolchains
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
    client.settings['mcp_servers']['unexpected'] = {'command':'bad'}
    try:
        with pytest.raises(ValueError, match='policy changed'):
            client.turn(client.root/'turns/0003', 'Must not execute', 10, first['session_id'])
        assert len(captured)==2
    finally:client.settings['mcp_servers'].pop('unexpected')


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


@toolchains
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
    script = '''import errno, json, os, pathlib, socket, subprocess, threading, sys
r = {'netns': os.readlink('/proc/self/ns/net'), 'route': pathlib.Path('/proc/net/route').read_text(),
     'ipv6_route': pathlib.Path('/proc/net/ipv6_route').read_text(),
     'pipe': subprocess.check_output(['/bin/sh', '-c', 'printf probe | cat']).decode()}
items=[]
t=threading.Thread(target=lambda:items.append('thread'));t.start();t.join();r['thread']=items==['thread']
try:
    s=socket.socket();s.settimeout(2);s.bind(('127.0.0.1',0));s.listen()
    program="import socket,sys;c=socket.create_connection(('127.0.0.1',int(sys.argv[1])),timeout=2);c.sendall(b'probe');sys.stdout.buffer.write(c.recv(5))"
    c=subprocess.Popen([sys.executable,'-c',program,str(s.getsockname()[1])],stdout=subprocess.PIPE)
    a,_=s.accept();first=a.recv(5);a.sendall(b'reply');second=c.communicate(timeout=3)[0]
    r['local_tcp']=first==b'probe' and second==b'reply' and c.returncode==0
    a.close();s.close()
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
    if route in {"full_fixed", "baseline_mcp"}:
        assert observed["local_tcp"] and observed["netns"] != namespace
        assert len(observed["route"].splitlines()) == 1
        assert all(line.split()[-1] == "lo" for line in observed["ipv6_route"].splitlines())
    else:
        # Ordinary shells remain restricted; both groups have separate TCP execution paths.
        assert observed["local_tcp"] is False and observed["local_errno"] in (1, 13)
        assert observed["host_errno"] in (1, 13)


@toolchains
def test_common_effective_settings_and_material_boundaries(environment, execution):
    from consensus_assurance.adapters.storage.files import write_json
    route, work, execute = execution
    if route == 'full_agent':
        root = work.parent
        profile = json.loads((root / 'agent-inputs/runtime-settings.json').read_text())['settings']
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
    source = environment.root / 'source/fixture.txt' if route in {'baseline', 'baseline_mcp'} else work.parent / 'agent-source/fixture.txt'
    retained = environment.root / 'turns/permission-canary' if route in {'baseline', 'baseline_mcp'} else work.parent / 'logs/host-record'
    if route not in {'baseline', 'baseline_mcp'}:
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


@pytest.mark.parametrize('environment', ['cargo'], indirect=True, scope='module')
def test_cargo_compiled_seed_is_not_a_dependency_cache(environment):
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
@pytest.mark.parametrize('execution', ['baseline', 'full_agent', 'full_fixed'], indirect=True)
def test_execution_stops_descendants(environment, execution, stop):
    route, work, execute = execution
    heartbeat = work / ("heartbeat-" + stop)
    heartbeat.unlink(missing_ok=True)
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
        if stop == "total_deadline" and route == 'baseline':
            environment.deadline = time.monotonic() + timeout
            timeout = 8
        elif stop == "total_deadline":
            execute.runner.deadline = time.monotonic() + timeout
            timeout = 8
        try:
            result, _ = execute(["python3", "-c", script], "stop-" + stop, timeout)
        except (TimeoutError, KeyboardInterrupt):
            assert route == 'baseline'
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


@toolchains
def test_mcp_permissions_arguments_and_results(environment):
    client = environment
    socket_directory = tempfile.TemporaryDirectory(prefix='baseline-ipc-')
    host_socket = Path(socket_directory.name)/'host-control.sock'
    unix = socket.socket(socket.AF_UNIX)
    unix.bind(str(host_socket)); unix.listen()
    with socket.socket(socket.AF_UNIX) as positive:
        positive.connect(str(host_socket)); accepted, _ = unix.accept()
        with accepted:
            accepted.sendall(b'control'); assert positive.recv(7) == b'control'
    deps = client.execution_control['read_only_roots']
    canaries = [str(p/'writable-host-canary') for p in map(Path, deps) if (p/'writable-host-canary').exists()]
    secret = client.root.parent/'private-canary'
    log = client.root/'executions/host-canary';log.write_text('retained log')
    script = '''import errno,json,os,pathlib,socket,subprocess
blocked=[]
def denied(label, fn):
    try:fn()
    except OSError as e:
        assert e.errno in (errno.ENOENT,errno.EACCES,errno.EPERM,errno.EROFS,errno.ECONNREFUSED), e
        blocked.append(label)
    else:raise AssertionError(label)
for p in PRIVATE:denied(p,lambda:pathlib.Path(p).read_bytes())
for p in READONLY:
    assert pathlib.Path(p).read_bytes()
    denied('write:'+p,lambda:pathlib.Path(p).open('a'))
denied('host-unix',lambda:socket.socket(socket.AF_UNIX).connect(SOCKET))
assert not pathlib.Path('/run/docker.sock').exists() and not pathlib.Path('/var/run/dbus/system_bus_socket').exists()
assert not any('KEY' in k or 'TOKEN' in k or 'PROXY' in k and k != 'GOPROXY' for k in os.environ)
pids=list(pathlib.Path('/proc').glob('[0-9]*'))
for p in pids:
    try:data=(p/'cmdline').read_bytes()
    except OSError:continue
    assert b'local_'+b'exec.py' not in data and b'codex'+b' exec' not in data
pathlib.Path('isolated-note.txt').write_text('allowed')
try:os.lseek(1,0,0)
except OSError as e:assert e.errno==errno.ESPIPE
else:raise AssertionError('Raw log is seekable by test process')
print(json.dumps({'denied':blocked,'pids':[p.name for p in pids],'env':dict(os.environ),'fds':[os.readlink(p) for p in pathlib.Path('/proc/self/fd').glob('*') if p.exists()]}))
'''.replace('PRIVATE', repr(list(map(str,[secret, log, client.control_path, client.root/'inputs/task.md', runner.TASK.parent/'README.md'])))).replace('READONLY', repr([str(client.root/'source/fixture.txt'), *canaries])).replace('SOCKET', repr(str(host_socket)))
    link=client.work/'outside';link.symlink_to(client.root.parent,target_is_directory=True)
    host_program=client.root.parent/'host-only.py'
    host_program.write_text("#!/usr/bin/python3\nprint('HOST_PROGRAM_CONTROL')\n");host_program.chmod(0o755)
    assert subprocess.check_output([str(host_program)],text=True).strip()=='HOST_PROGRAM_CONTROL'
    client.execution_control.update(turn='mcp-boundaries', allow_experiments=True, turn_deadline=time.monotonic()+60)
    runner.write_json(client.control_path, client.execution_control)
    async def scenario():
        async with mcp_session(client) as (session, _):
            response = await session.call_tool('isolated_exec', {'argv': ['python3', '-c', script]})
            runner.write_json(client.root/'inputs/mcp-ipc-controls.json', response.model_dump(mode='json'))
            assert response.structuredContent['exit_code'] == 0, response
            assert all(Path(p).read_text() == 'dependency canary' for p in canaries)
            for args in ({'argv':[]},{'argv':['true'],'cwd':'..'},{'argv':['true'],'cwd':str(client.work)},
                         {'argv':['true'],'cwd':'outside'},{'argv':['true'],'env':{'PATH':'bad'}},
                         {'argv':['true'],'mounts':['/']},{'argv':['true'],'timeout_seconds':0}):
                response=await session.call_tool('isolated_exec',args)
                assert response.isError,response
            response=await session.call_tool('isolated_exec',{'argv':[str(host_program)]})
            assert response.structuredContent['status']=='launch_error' and response.structuredContent['exit_code']!=0
            assert 'HOST_PROGRAM_CONTROL' not in response.structuredContent['stdout']['preview']
            response=await session.call_tool('isolated_exec',{'argv':['python3','-c',"import sys;print('x'*20000);print('diagnostic',file=sys.stderr);sys.exit(7)"]})
            assert not response.isError
            result=response.structuredContent
            assert result['status']=='completed' and result['exit_code']==7 and result['stdout']['truncated']
            assert Path(result['stdout']['path']).stat().st_size==20001
            concurrent=await asyncio.gather(*(session.call_tool('isolated_exec',{'argv':['python3','-c','import time;time.sleep(.1)']}) for _ in range(2)))
            ordered=sorted((r.structuredContent for r in concurrent),key=lambda r:r['started_at'])
            assert ordered[1]['started_at']>=ordered[0]['ended_at'], 'Tool calls overlapped'
            return result
    try:
        runner.write_json(client.root/'inputs/mcp-contract.json', asyncio.run(scenario()))
    finally:
        link.unlink()
        unix.close()
        socket_directory.cleanup()


@pytest.mark.parametrize('stop', ['action_timeout','agent_turn_timeout','total_seconds','cancelled',
                               'stdio_disconnect','service_death','background_exit','parent_exit','parent_kill'])
def test_mcp_lifecycle_retains_partial_output_and_kills_detached_children(environment, stop):
    client=environment
    heartbeat=client.work/('mcp-heartbeat-'+stop)
    child="import pathlib,time\np=pathlib.Path("+repr(str(heartbeat))+")\nwhile True:\n p.write_text(str(time.monotonic_ns()));time.sleep(.02)"
    script="import subprocess,sys,time,pathlib;subprocess.Popen([sys.executable,'-c',"+repr(child)+"],start_new_session=True);\nwhile not pathlib.Path("+repr(str(heartbeat))+").exists():time.sleep(.01)\nprint('CHILD_STARTED',flush=True)\n"
    if stop!='background_exit':script+='time.sleep(60)\n'
    control={**client.execution_control,'turn':'lifecycle-'+stop,'allow_experiments':True,'action_timeout':10,
             'turn_deadline':time.monotonic()+20,'run_deadline':time.monotonic()+30}
    if stop=='action_timeout':control['action_timeout']=.5
    if stop in {'agent_turn_timeout','total_seconds'}:control['turn_deadline' if stop=='agent_turn_timeout' else 'run_deadline']=time.monotonic()+3
    runner.write_json(client.control_path,control)
    server = None
    if stop in {'parent_exit', 'parent_kill'}:
        # The client keeps STDIO open after this parent exits, so EOF cannot mask a broken pidfd watch.
        wrapper = ('import signal,subprocess,sys,time; signal.signal(signal.SIGTERM,lambda *_:sys.exit(0)); '
                   'subprocess.Popen(sys.argv[1:]); time.sleep(60)')
        server = StdioServerParameters(command=sys.executable, args=['-c', wrapper,
            client.mcp_settings['command'], *client.mcp_settings['args']], env={})
    async def scenario():
        async with mcp_session(client, server) as (session, streams):
            task=asyncio.create_task(session.call_tool('isolated_exec',{'argv':['python3','-c',script],'timeout_seconds':15.0}))
            end=time.monotonic()+8
            while not heartbeat.exists() and time.monotonic()<end:await asyncio.sleep(.02)
            assert heartbeat.exists(), 'The child did not start'
            records=[p for p in (client.root/'executions').glob('*/result.json') if json.loads(p.read_text())['turn']==control['turn']]
            assert len(records)==1
            record=json.loads(records[0].read_text())
            captured=records[0].parent/'stdout.txt'
            while (not captured.exists() or 'CHILD_STARTED' not in captured.read_text()) and time.monotonic()<end:
                await asyncio.sleep(.01)
            assert captured.exists() and 'CHILD_STARTED' in captured.read_text(), 'Partial output was not produced before termination'
            if stop=='cancelled':
                await session.send_notification(types.ClientNotification(types.CancelledNotification(params=types.CancelledNotificationParams(requestId=record['mcp_request_id'],reason='acceptance cancellation'))))
            elif stop=='stdio_disconnect':await streams[1].aclose()
            elif stop=='service_death':os.kill(record['service_pid'],signal.SIGKILL)
            elif stop in {'parent_exit', 'parent_kill'}:
                parent = int(Path(f"/proc/{record['service_pid']}/stat").read_text().split()[3])
                os.kill(parent, signal.SIGTERM if stop == 'parent_exit' else signal.SIGKILL)
            try:
                response=await asyncio.wait_for(task,8)
                if stop in {'action_timeout','agent_turn_timeout','total_seconds'}:
                    assert response.structuredContent['status']=='timeout'
                    assert response.structuredContent['timeout_limit']==stop
                elif stop=='background_exit':assert response.structuredContent['exit_code']==0
            except Exception as exc:
                if stop not in {'cancelled','stdio_disconnect','service_death','parent_exit','parent_kill'}:raise
                if stop in {'parent_exit', 'parent_kill'}:
                    assert not isinstance(exc, asyncio.TimeoutError), 'MCP hung on open stdin after parent exit'
            return records[0]
    path=asyncio.run(scenario())
    local_exec.reconcile(client.root/'executions',control['turn'],'Abrupt service termination')
    record=json.loads(path.read_text())
    assert record['status']!='running'
    if stop in {'parent_exit', 'parent_kill'}:
        assert record['status'] == 'cancelled' and record['reason'] == 'parent_exit', record
    assert 'CHILD_STARTED' in (path.parent/'stdout.txt').read_text()
    time.sleep(.1);before=heartbeat.read_text();time.sleep(.2)
    assert heartbeat.read_text()==before, 'Detached descendant survived the service lifecycle'


def test_real_codex_long_command_and_required_service(environment, monkeypatch):
    """Exercise real tool execution and both model entry points without inference."""
    client = environment
    monkeypatch.setenv(client.config.credential_name, 'baseline-credential-canary')
    client.authenticate()
    runner.write_json(client.control_path, {**client.execution_control, 'turn': 'native-long-command',
        'allow_experiments': True, 'action_timeout': 30, 'turn_deadline': time.monotonic()+60,
        'run_deadline': time.monotonic()+90})
    async def scenario():
        async with local_exec.app_server([*client.prefix(offline=True), 'app-server', '--strict-config',
                *codex.options(client.settings)], client.work, client.environment,
                client.root/'inputs/mcp-long-command', 30) as request:
            thread = (await request('thread/start', {'cwd': str(client.work)}))['thread']['id']
            result = await request('mcpServer/tool/call', {'threadId': thread, 'server': 'baseline_local',
                'tool': 'isolated_exec', 'arguments': {'argv': ['python3', '-c',
                    'import time; print("START",flush=True); time.sleep(12); print("DONE",flush=True)'],
                    'timeout_seconds': 25.0}})
            record = result['structuredContent']
            assert record['status'] == 'completed' and record['exit_code'] == 0, result
            assert record['elapsed_seconds'] >= 12 and record['stdout']['preview'] == 'START\nDONE\n'
            await request('thread/inject_items', {'threadId': thread, 'items': [
                {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text',
                 'text': 'Offline MCP fixture; no model turn has occurred.'}]}]})
            return thread
    session = asyncio.run(scenario())
    broken = {**client.settings, 'mcp_servers': {'baseline_local': {**client.mcp_settings,
        'args': ['-i', '/nonexistent-baseline-acceptance-service']}}}
    for name in ('exec', 'resume'):
        args = ['exec', *(['resume', session] if name == 'resume' else []), '--ignore-user-config', '--strict-config',
                '--skip-git-repo-check', '--json', *codex.options(broken), '-']
        result, text = client.local(args, 'required-mcp-'+name, stdin='Synthetic startup check; no inference is authorized.')
        error = (client.root/'inputs'/('required-mcp-'+name)/'stderr.log').read_text()
        assert result['exit_code'] != 0 and 'baseline_local' in text+error, text+error
        assert 'required mcp' in (text+error).lower(), text+error
        events = [json.loads(line) for line in text.splitlines() if line.startswith('{')]
        assert not any(e.get('type') == 'turn.completed' for e in events)


def test_native_full_profile_creates_and_preserves_its_own_record(environment, monkeypatch):
    from consensus_assurance.adapters.agents.backend import CodexAgent
    from consensus_assurance.adapters.runners.process import ProcessRunner
    client=environment
    root=client.root.parent/'native-profile'
    (root/'agent-source').mkdir(parents=True)
    (root/'agent-source/fixture.txt').write_text('source control')
    home=client.home/'native-profile-home';home.mkdir()
    monkeypatch.setenv('CODEX_HOME',str(home))
    process_runner=ProcessRunner(root)
    agent=CodexAgent('high','gpt-5.4',profile='single_agent')
    assert agent.probe(process_runner)['available']
    assert agent.prepare(process_runner,root/'draft','s')[0]
    record=root/'agent-inputs/runtime-settings.json';before=record.read_bytes()
    restored=CodexAgent('high','gpt-5.4',profile='single_agent')
    assert restored.prepare(process_runner,root/'draft','s')[0]
    assert record.read_bytes()==before
    restored.profile_settings['features.shell_snapshot']=True
    with pytest.raises(ValueError,match='profile settings changed'):
        restored.prepare(process_runner,root/'draft','s')
    assert record.read_bytes()==before
