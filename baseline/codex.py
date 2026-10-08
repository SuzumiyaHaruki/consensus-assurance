"""Native text turns, isolated configuration, and verified local permissions."""
import json
import asyncio
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import UUID

from consensus_assurance.adapters.agents.backend import (
    classify_failure, codex_diagnostic, common_settings, DISABLED_FEATURES, toml, codex_options as options,
)
from consensus_assurance.adapters.runners.go_module import GoModuleBackend
from consensus_assurance.adapters.storage.files import write_json, digest
from . import local_exec


def process(command, cwd, folder, timeout, *, env, stdin="", secrets=()):
    """Keep partial bytes and terminate all descendants on every exit path."""
    folder.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    result = {"status": "completed", "exit_code": None, "timeout_seconds": timeout, "command": command,
              "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    child = None
    with (folder / "stdout.jsonl").open("wb") as out, (folder / "stderr.log").open("wb") as err:
        try:
            if timeout <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            child = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                     stdout=out, stderr=err, start_new_session=True)
            child.communicate(stdin.encode(), timeout=timeout)
            result["exit_code"] = child.returncode
        except subprocess.TimeoutExpired:
            result["status"] = "timeout"
        except KeyboardInterrupt:
            result["status"] = "cancelled"
        except OSError as exc:
            result.update(status="error", reason=str(exc))
        finally:
            if child:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
                result["exit_code"] = child.returncode
    result["elapsed_seconds"] = time.monotonic() - started
    # Raw CLI bytes are retained except exact credential values, which never belong in archives.
    for name in ("stdout.jsonl", "stderr.log", "final.txt"):
        path = folder / name
        if path.exists():
            data = path.read_bytes()
            for secret in secrets:
                if secret:
                    data = data.replace(secret.encode(), b"[REDACTED_CREDENTIAL]")
            path.write_bytes(data)
    return result


def decode(folder, result, session_id=None):
    events, invalid = [], 0
    for line in (folder / "stdout.jsonl").read_text(errors="replace").splitlines():
        try:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("Nonobject event")
            events.append(value)
        except ValueError:
            invalid += 1
    identities = [e.get("thread_id") for e in events if e.get("type") == "thread.started"]
    identity = identities[-1] if identities else session_id
    completed = [e for e in events if e.get("type") == "turn.completed"]
    diagnostic = codex_diagnostic(events)
    final_path = folder / "final.txt"
    final = final_path.read_text(errors="replace") if final_path.is_file() else ""
    tools = [e["item"] for e in events if e.get("type") == "item.completed"
             and isinstance(e.get("item"), dict) and e["item"].get("type") in
             {"command_execution", "file_change", "mcp_tool_call", "web_search"}]
    result.update(session_id=identity, native_completed=bool(completed), diagnostic=diagnostic,
                  usage=[e.get("usage") for e in completed], usage_semantics="unverified_do_not_sum",
                  tool_events=len(tools), invalid_jsonl_lines=invalid, final_present=bool(final))
    if result["status"] != "completed":
        return result
    # Match src: native retries can emit error notifications before successful completion.
    if (result["exit_code"] != 0 or any(e.get("type") == "turn.failed" for e in events)
            or (not completed and any(e.get("type") == "error" for e in events))):
        failure = diagnostic["message"] or (folder / "stderr.log").read_text(errors="replace")
        result.update(status="external_error", failure_kind=classify_failure(failure).value,
                      reason=failure or "Native turn failed; inspect retained output")
        return result
    try:
        UUID(identity)
    except (ValueError, TypeError, AttributeError):
        result.update(status="external_blocker_needs_review", reason="Missing valid native session identity")
        return result
    if any(x != identity for x in identities) or session_id and identity != session_id:
        result.update(status="session_mismatch", reason="Exact session changed; no replacement session allowed")
    elif not completed or invalid or not final:
        result.update(status="external_blocker_needs_review", reason="Incomplete or unrecognized native completion")
    elif final.lstrip().startswith("RUN_BLOCKED:"):
        result.update(status="run_blocked", reason=final)
    elif any(e.get("type") == "refusal" or e.get("item", {}).get("type") == "refusal"
             for e in events if isinstance(e.get("item", {}), dict)) or re.search(
                 r"(?is)\bi(?: am|'m)? (?:cannot|can't|will not|won't|must refuse|unable to) "
                 r"(?:help|assist|comply|fulfil|fulfill|do that|provide (?:that|those|the requested)|"
                 r"(?:perform|continue|proceed with) (?:this|the) (?:request|audit))\b|"
                 r"(?:我(?:不能|无法|必须拒绝)|(?:抱歉|对不起)[^。\n]{0,60})(?:协助|帮助|执行此审计|提供此类)",
                 final[:1000].replace("’", "'")):
        result.update(status="external_blocker_needs_review", reason="Possible final refusal; inspect original final text")
    return result


class Codex:
    def __init__(self, config, root, target, deadline):
        self.config, self.root, self.target, self.deadline = config, Path(root), target, deadline
        self.work = self.root / "work"
        private_parent = Path(__file__).resolve().parent / "runs"
        private_parent.mkdir(exist_ok=True)
        self.private = tempfile.TemporaryDirectory(prefix=".client-", dir=private_parent)
        self.home = Path(self.private.name)
        self.client_home = self.home / "codex"
        self.client_home.mkdir()
        self.executable = shutil.which("codex")
        if not self.executable:
            raise ValueError("Codex CLI is unavailable")
        self.executable = str(Path(self.executable).resolve())
        self.helpers = self.home / "helpers"
        self.helpers.mkdir()
        for name in ("codex-linux-sandbox", "apply_patch"):
            (self.helpers / name).symlink_to(self.executable)
        self.environment = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(self.home),
                            "CODEX_HOME": str(self.client_home), "LANG": "C.UTF-8"}
        self.secrets = []
        self.read_roots = [str(Path(self.executable).parent), str(self.client_home / "tmp" / "arg0"), str(self.helpers)]
        self.tool_environment = {**GoModuleBackend().environment(self.work),
                                 "PATH": "/usr/bin:/bin", "HOME": str(self.work / ".runtime/home"),
                                 "TMPDIR": str(self.work / ".runtime/tmp"), "LANG": "C.UTF-8",
                                 "GOCACHE": str(self.work / ".runtime/go-build"),
                                 "GOMODCACHE": str(self.work / ".runtime/go-mod"),
                                 "CARGO_HOME": str(self.work / ".runtime/cargo"), "CARGO_NET_OFFLINE": "true",
                                 "CARGO_TARGET_DIR": str(self.work / ".runtime/cargo-target")}
        for name in ("home", "tmp", "go-build", "go-mod", "cargo", "cargo-target"):
            (self.work / ".runtime" / name).mkdir(parents=True, exist_ok=True)
        self.settings = {}

    def close(self):
        if hasattr(self, 'execution_control'):
            local_exec.reconcile(self.root/'executions', self.execution_control['turn'], 'Client lifecycle ended without a completion record')
        self.private.cleanup()

    def limit(self, maximum=30):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Total deadline reached during preparation")
        return min(maximum, remaining)

    def prefix(self, *, offline=False):
        # The outer mount namespace also normalizes non-path nsfs mounts for this CLI build.
        bwrap = shutil.which("bwrap")
        if not bwrap:
            raise ValueError("Bubblewrap is required for this Linux execution profile")
        return [bwrap, "--die-with-parent", "--ro-bind", "/", "/", "--bind", "/tmp", "/tmp", "--bind", str(self.root), str(self.root),
                "--bind", str(self.home), str(self.home), "--proc", "/proc", "--dev", "/dev",
                *(["--unshare-net"] if offline else []), "--", self.executable]

    def local(self, args, name, *, stdin="", offline=True, maximum=30, env=None):
        folder = self.root / "inputs" / name
        result = process([*self.prefix(offline=offline), *args], self.work, folder, self.limit(maximum),
                         env=env or self.environment, stdin=stdin)
        write_json(folder / "result.json", result)
        if result["status"] == "cancelled":
            raise KeyboardInterrupt
        if result["status"] == "timeout" and time.monotonic() >= self.deadline:
            raise TimeoutError("Total deadline reached during local preparation")
        return result, (folder / "stdout.jsonl").read_text(errors="replace")

    def authenticate(self):
        key = self.config.credential_name
        if self.config.auth_mode == "api_key":
            value = os.environ.get(key)
            if not value:
                raise ValueError(f"Missing credential environment variable: {key}; no model request sent")
            self.environment[key if self.config.codex_provider else "CODEX_API_KEY"] = value
            self.secrets = [value]
        else:
            original = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "auth.json"
            if not original.is_file() or original.is_symlink():
                raise ValueError("codex_login requires existing file-backed authentication; no automatic login")
            data = original.read_bytes()
            auth = json.loads(data)
            if auth.get("auth_mode") != "chatgpt":
                raise ValueError("codex_login requires ChatGPT auth; select api_key explicitly for API auth")
            (self.client_home / "auth.json").write_bytes(data)
            (self.client_home / "auth.json").chmod(0o600)
            self.secrets = [value for key, value in auth.get("tokens", {}).items()
                            if key in {"access_token", "refresh_token", "id_token"} and isinstance(value, str)]

    def prepare(self):
        result, text = self.local(['--version'], 'cli-version')
        if result['status'] != 'completed' or result['exit_code'] or 'codex' not in text:
            raise ValueError('Codex CLI version unavailable')
        self.version = text.strip()
        tool = "go" if self.target["execution_backend"] == "go_module" else "rustc"
        command = [tool, "env", "GOROOT"] if tool == "go" else [tool, "--print", "sysroot"]
        discovered = subprocess.run(command, capture_output=True, text=True, timeout=self.limit(), check=True)
        tool_root = Path(discovered.stdout.strip()).resolve()
        self.read_roots.append(str(tool_root))
        if tool == "go":
            if self.config.go_mod_cache_dir:
                cache = Path(self.config.go_mod_cache_dir)
                if not cache.is_dir() or cache.is_symlink() or self.root.is_relative_to(cache) or cache.is_relative_to(self.root):
                    raise ValueError("go_mod_cache_dir must be a separate existing module cache directory")
                self.tool_environment["GOMODCACHE"] = str(cache)
                self.read_roots.append(str(cache))
        elif self.config.cargo_dependency_cache_dir:
            cache = Path(self.config.cargo_dependency_cache_dir)
            if not cache.is_dir() or cache.is_symlink() or self.root.is_relative_to(cache) or cache.is_relative_to(self.root):
                raise ValueError("cargo_dependency_cache_dir must be a separate existing Cargo home")
            if not any((cache / name).is_dir() for name in ("registry", "git")):
                raise ValueError("cargo_dependency_cache_dir needs registry/ or git/; a compiled seed directory is not a dependency cache")
            # Match CargoBackend: expose only dependency trees through the private Cargo home.
            for name in ("registry", "git"):
                dependency = cache / name
                if dependency.is_dir():
                    if dependency.is_symlink():
                        raise ValueError("Cargo dependency roots must not be symlinks")
                    (self.work / ".runtime/cargo" / name).symlink_to(dependency, target_is_directory=True)
                    self.read_roots.append(str(dependency))
        self.tool_environment["PATH"] = str(tool_root / "bin") + ":" + str(self.helpers) + ":/usr/bin:/bin"
        self.execution_control = {'work': str(self.work), 'records': str(self.root/'executions'),
            'tool_roots': [str(tool_root)], 'read_only_roots': [str(self.root/'source'),
                *[p for p in self.read_roots if p not in {str(tool_root), str(Path(self.executable).parent), str(self.client_home/'tmp/arg0'), str(self.helpers)}]],
            'environment': {**self.tool_environment, 'PATH': str(tool_root/'bin')+':/usr/bin:/bin'},
            'action_timeout': self.config.budget.action_timeout, 'run_deadline': self.deadline,
            'turn_deadline': min(self.deadline, time.monotonic()+30), 'turn': 'environment-check',
            'allow_experiments': True}
        # check-env authorizes only the fixed local probe. Real calls require both original switches.
        self.control_path = self.home/'local-exec.json'
        write_json(self.control_path, self.execution_control)
        (self.root/'executions').mkdir(exist_ok=True)
        self.mcp_settings = local_exec.server_settings(self.control_path, max(self.config.budget.action_timeout, self.config.budget.agent_turn_timeout))
        filesystem = {":root": "deny", ":minimal": "read",
                      str(self.root / "source"): "read", str(self.work): "write",
                      str(self.root / "turns"): "read", str(self.root / "inputs/task.md"): "read",
                      str(self.root / "executions"): "read",
                      **{path: "read" for path in self.read_roots}}
        self.settings = {"default_permissions": "codex_plain", "permissions.codex_plain.filesystem": filesystem,
                         "permissions.codex_plain.network.enabled": False, "approval_policy": "never",
                         "shell_environment_policy.inherit": "none",
                         "shell_environment_policy.set": self.tool_environment,
                         "shell_environment_policy.ignore_default_excludes": False,
                         "shell_environment_policy.experimental_use_profile": False,
                         **common_settings(self.config.codex_provider),
                         "projects": {str(self.work): {"trust_level": "untrusted"}},
                         "model": self.config.agent_model}
        self.settings['mcp_servers'] = {'baseline_local': self.mcp_settings}
        if self.config.agent_reasoning_effort is not None:
            self.settings["model_reasoning_effort"] = self.config.agent_reasoning_effort
        provider = self.config.codex_provider
        if provider:
            self.settings["model_provider"] = provider.id
            for key, value in {"name": provider.id, "base_url": provider.base_url, "env_key": provider.env_key,
                               "wire_api": "responses", "requires_openai_auth": False, "supports_websockets": False}.items():
                self.settings[f"model_providers.{provider.id}.{key}"] = value
        else:
            self.settings["forced_login_method"] = "api" if self.config.auth_mode == "api_key" else "chatgpt"
        if provider and provider.model_catalog_path:
            raw = Path(provider.model_catalog_path).read_bytes()
            catalog = json.loads(raw)
            models = catalog.get("models", [])
            if len(models) != 1 or models[0].get("slug") != self.config.agent_model:
                raise ValueError("Catalog must contain exactly the selected model")
            supported = {x["effort"] for x in models[0].get("supported_reasoning_levels", [])}
            if self.config.agent_reasoning_effort is not None and self.config.agent_reasoning_effort not in supported:
                raise ValueError("Catalog does not support the requested reasoning effort")
            if self.config.agent_reasoning_effort is None and (supported or models[0].get("default_reasoning_level")):
                raise ValueError("null cannot omit reasoning with this catalog's defaults; select an explicit effort")
            (self.root / "inputs/models.json").write_bytes(raw)
            self.settings["model_catalog_json"] = str(self.root / "inputs/models.json")
        elif provider or self.config.agent_reasoning_effort is None:
            raise ValueError("Custom models and omitted reasoning require an explicitly verified model catalog")
        else:
            result, _ = self.local(["debug", "models", "--bundled"], "bundled-catalog")
            if result["exit_code"]:
                raise ValueError("Cannot capture the native bundled model catalog without network")
            raw = (self.root / "inputs/bundled-catalog/stdout.jsonl").read_bytes()
            selected = [m for m in json.loads(raw)["models"] if m.get("slug") == self.config.agent_model]
            if len(selected) != 1 or self.config.agent_reasoning_effort not in {
                    x["effort"] for x in selected[0].get("supported_reasoning_levels", [])}:
                raise ValueError("Native model or effort is not advertised by this installed CLI catalog")
            (self.root / "inputs/models.json").write_bytes(raw)
            self.settings["model_catalog_json"] = str(self.root / "inputs/models.json")
        self.permission_probe()
        asyncio.run(self.mcp_probe())
        write_json(self.root/'inputs/local-exec.json', local_exec.identity(self.mcp_settings, self.execution_control))
        self.execution_control['allow_experiments'] = self.config.allow_agent_materials and self.config.allow_experiments
        write_json(self.control_path, self.execution_control)
        self.prompt_probe()
        versions = {}
        commands = {"platform": ["uname", "-sm"], "go": ["go", "version"],
                    "go_environment": ["go", "env", "GOOS", "GOARCH", "GOVERSION", "GOROOT", "GOMODCACHE", "GOCACHE", "GOFLAGS", "GOWORK"]} if tool == "go" else {
                    "platform": ["uname", "-sm"], "cargo": ["cargo", "--version", "--verbose"], "rustc": ["rustc", "--version", "--verbose"]}
        for name, command in commands.items():
            result, text = self.local(["sandbox", "--include-managed-config", "-P", "codex_plain", *options(self.settings),
                                      "-C", str(self.work), *command], "tool-" + name)
            if result["status"] != "completed" or result["exit_code"]:
                raise ValueError("Cannot record the actual sandbox tool version: " + name)
            versions[name] = text.strip()
        write_json(self.root / "inputs/cli-settings.json", self.settings)
        return {"cli": self.version, "tool_root": str(tool_root), "tool_environment": self.tool_environment, "versions": versions,
                "network": "ordinary shell: disabled; isolated_exec: private loopback; model client: selected provider",
                "subagents": False, "cache_policy": "private cold builds; optional read-only shared dependencies",
                "native_retries": {"request_max_retries": 4, "stream_max_retries": 5} if provider else
                    {"policy": "bundled provider defaults, tied to recorded CLI version; reserved provider cannot be overridden"},
                "unbounded_connection_retries": False, "outer_retries": 0,
                "tool_evidence": {"local_registration_and_tcp": "verified",
                                  "model_request_tool_surface": "not_inspected_by_check_env",
                                  "real_model_tool_use": "not_evaluated"},
                "reasoning": self.config.agent_reasoning_effort, "permission_probe": "verified"}

    async def mcp_probe(self):
        async with local_exec.app_server([*self.prefix(offline=True), 'app-server', '--strict-config',
                *options(self.settings)], self.work, self.environment, self.root/'inputs/mcp-probe', self.limit()) as request:
            thread = (await request('thread/start', {'cwd': str(self.work)}))['thread']['id']
            inventory = await request('mcpServerStatus/list', {'threadId': thread})
            if ([server['name'] for server in inventory['data']] != ['baseline_local'] or
                    inventory['data'][0]['tools'] != {'isolated_exec': local_exec.tool().model_dump(mode='json', exclude_none=True)}):
                raise ValueError('Codex MCP inventory differs from the authorized tool')
            result = await request('mcpServer/tool/call', {'threadId': thread, 'server': 'baseline_local',
                'tool': 'isolated_exec', 'arguments': {'argv': ['python3', '-c',
                    "import socket; s=socket.socket();s.bind(('127.0.0.1',0));s.listen();c=socket.create_connection(s.getsockname());a,_=s.accept();c.sendall(b'ping');assert a.recv(4)==b'ping';a.sendall(b'pong');assert c.recv(4)==b'pong';print('ISOLATED_TCP_VERIFIED')"], 'timeout_seconds': 10.0}})
            write_json(self.root/'inputs/local-exec-probe.json', {'inventory': inventory, 'call': result})
            observed = result.get('structuredContent', {})
            if observed.get('status') != 'completed' or observed.get('exit_code') != 0 or 'ISOLATED_TCP_VERIFIED' not in observed.get('stdout', {}).get('preview', ''):
                raise ValueError('Isolated execution MCP probe failed; no model request sent')

    def permission_probe(self):
        canary = self.home / "credential-canary"
        canary.write_text("private canary")
        protected = self.root / "turns/permission-canary"
        protected.write_text("retained canary")
        old_result = self.root / "old-results-canary"
        old_result.write_text("old result canary")
        source = next(p for p in (self.root / "source").rglob("*") if p.is_file())
        framework = Path(__file__).resolve().parent.parent
        denied = [canary, old_result, framework / "AGENTS.md", framework / "src", framework / "runs",
                  framework / "baseline/README.md", self.client_home / "auth.json"]
        script = """import errno, os, pathlib, socket, subprocess, threading
def blocked(fn):
    try: fn()
    except OSError as exc:
        assert exc.errno in (errno.EPERM, errno.EACCES, errno.EROFS, errno.ENOENT), exc
    else: raise AssertionError('Forbidden operation succeeded')
"""
        script += f"for name in {list(map(str, denied))!r}:\n    blocked(lambda: pathlib.Path(name).read_bytes())\n"
        script += f"for name in {[str(source), str(protected)]!r}:\n    assert pathlib.Path(name).read_bytes()\n    blocked(lambda: pathlib.Path(name).open('a'))\n    blocked(lambda: os.chmod(name, 0o600))\n"
        names = ["OPENAI_API_KEY", "CODEX_API_KEY", self.config.credential_name or "BASELINE_SECRET"]
        script += f"assert not set({names!r}) & set(os.environ)\n"
        script += "for entry in pathlib.Path('/proc').glob('[0-9]*/environ'):\n    try: data = entry.read_bytes()\n    except OSError: continue\n    assert b'baseline-credential-canary' not in data, 'Credential visible through procfs'\n"
        script += """pathlib.Path('permission-write.txt').write_text('allowed')
assert subprocess.check_output(['/bin/sh', '-c', 'printf pipe | cat']) == b'pipe'
t = threading.Thread(target=lambda: None); t.start(); t.join()
blocked(lambda: socket.socket().bind(('127.0.0.1', 0)))
blocked(lambda: socket.socket().connect(('192.0.2.1', 9)))
print('PERMISSIONS_VERIFIED')
"""
        probe_environment = {**self.environment, **{name: "baseline-credential-canary" for name in names}}
        result, text = self.local(["sandbox", "--include-managed-config", "-P", "codex_plain",
                                  *options(self.settings), "-C", str(self.work), "/usr/bin/python3", "-c", script],
                                 "permission-probe", env=probe_environment)
        (self.work / "permission-write.txt").unlink(missing_ok=True)
        if result["status"] != "completed" or result["exit_code"] != 0 or "PERMISSIONS_VERIFIED" not in text:
            raise ValueError("Permission probe failed; no source may be sent to a model; inspect inputs/permission-probe")

    def prompt_probe(self):
        # This native debug command renders locally. The outer namespace has no network.
        args = ["debug", "prompt-input", *options(self.settings), "Local configuration inspection only."]
        result, _ = self.local(args, "prompt-bootstrap")
        if result["status"] != "completed" or result["exit_code"]:
            raise ValueError("Cannot inspect native prompt inputs without a model call")
        self.settings["skills.config"] = [{"path": str(path), "enabled": False}
                                          for path in sorted(self.client_home.glob("skills/**/SKILL.md"))]
        result, text = self.local(["debug", "prompt-input", *options(self.settings),
                                   "Local configuration inspection only."], "prompt-input")
        if result["status"] != "completed" or result["exit_code"]:
            raise ValueError("Native prompt isolation probe failed")
        items = json.loads(text)
        kinds = [kind for item in items for kind in item.get("internal_chat_message_metadata_passthrough", {}).get("content_item_kinds", [])]
        if any(kind in {"host_skills.instructions", "agents_md.instructions"} or "memory" in kind or "plugin" in kind for kind in kinds):
            raise ValueError("Unexpected automatic instructions in native prompt; inspect inputs/prompt-input")
        result, text = self.local(["features", "list", *options(self.settings)], "features")
        features = {line.split()[0]: line.split()[-1] for line in text.splitlines() if len(line.split()) >= 3}
        if result["exit_code"] or any(features.get(name) != "false" for name in DISABLED_FEATURES):
            raise ValueError("Required disabled capability could not be verified")

    def dependency_probe(self):
        command = ["go", "list", "-m", "all"] if self.target["execution_backend"] == "go_module" else [
            "cargo", "metadata", "--offline", "--format-version", "1"]
        result, _ = self.local(["sandbox", "--include-managed-config", "-P", "codex_plain", *options(self.settings),
                                "-C", str(self.work), *command], "dependency-probe", maximum=60)
        if result["status"] != "completed" or result["exit_code"]:
            raise ValueError("Offline dependency resolution failed; inspect inputs/dependency-probe")

    def turn(self, folder, prompt, timeout, session_id):
        # An agent-written project configuration must never become a new client configuration.
        if any((self.work / name).exists() for name in (".codex", ".agents")):
            raise ValueError("Unauthorized project configuration appeared in the working copy")
        if not (self.config.allow_agent_materials and self.config.allow_experiments):
            raise ValueError('Model transmission and local execution must both be authorized')
        saved = json.loads((self.root/'inputs/local-exec.json').read_text())
        if (saved != local_exec.identity(self.mcp_settings, self.execution_control)
                or self.settings.get('mcp_servers') != {'baseline_local': self.mcp_settings}
                or self.execution_control['run_deadline'] != self.deadline):
            raise ValueError('Isolated execution policy changed; start a new run')
        implementation = json.loads((self.root/'inputs/implementation.json').read_text())
        for label in ('baseline/local_exec.py', 'consensus_assurance.adapters.runners.experiment'):
            entry = implementation['inputs'][label]
            if digest(Path(entry['path']).read_bytes()) != entry['sha256']:
                raise ValueError('Isolated execution implementation changed; start a new run')
        self.execution_control.update(turn=folder.name, turn_deadline=min(self.deadline, time.monotonic()+timeout),
                                      allow_experiments=True)
        write_json(self.control_path, self.execution_control)
        command = [*self.prefix(), "exec", *(["resume"] if session_id else []), "--strict-config",
                   "--skip-git-repo-check", "--ignore-user-config", "--json",
                   "--output-last-message", str(folder / "final.txt"), *options(self.settings)]
        command += [session_id, "-"] if session_id else ["-"]
        result = process(command, self.work, folder, timeout, env=self.environment, stdin=prompt, secrets=self.secrets)
        local_exec.reconcile(self.root/'executions', folder.name, 'Codex turn ended: '+result['status'])
        return decode(folder, result, session_id)
