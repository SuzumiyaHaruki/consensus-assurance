import json
import os
import re
import shutil
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
from pathlib import Path
from consensus_assurance.core.types import CheckRun, ExecutionStatus, Origin
from consensus_assurance.adapters.runners.process import output
from consensus_assurance.adapters.storage.files import write_json, redact, digest


DISABLED_FEATURES = (
    "apps", "plugins", "remote_plugin", "hooks", "memories", "multi_agent", "multi_agent_v2",
    "skill_search", "skill_mcp_dependency_install", "shell_snapshot", "browser_use",
    "browser_use_external", "computer_use", "image_generation", "external_agent_memory_import",
    "unbounded_connection_retries", "workspace_dependencies", "in_app_local_automation",
)


def toml(value):
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k) + "=" + toml(v) for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(toml(v) for v in value) + "]"
    return json.dumps(value)


def codex_options(settings):
    return [arg for key, value in settings.items() for arg in ("-c", key + "=" + toml(value))]


def common_settings(provider=None):
    """Optional neutral single-agent policy; no research instructions or permissions."""
    settings = {"project_doc_max_bytes": 0, "web_search": "disabled", "mcp_servers": {}, "approval_policy": "never",
                "allow_login_shell": False, "memories.use_memories": False, "memories.generate_memories": False,
                "features.skip_host_skill_discovery": True,
                **{"features." + name: False for name in DISABLED_FEATURES}}
    if provider:
        settings.update({f"model_providers.{provider.id}.{key}": value for key, value in {
            "request_max_retries": 4, "stream_max_retries": 5, "stream_idle_timeout_ms": 300000}.items()})
    return settings


def classify_failure(text: str) -> ExecutionStatus:
    low = text.lower()
    if any(s in low for s in ["insufficient_quota", "quota exceeded", "usage limit", "rate limit", "quota exhausted", "credits exhausted"]):
        return ExecutionStatus.QUOTA_EXHAUSTED
    if (any(s in low for s in ["login required", "not logged in", "please log in", "authentication required", "unauthorized", "run codex login"])
            or re.search(r"\b(?:http(?:/\d(?:\.\d)?)?|status(?: code)?)\s*[:=]?\s*401\b", low)):
        return ExecutionStatus.LOGIN_REQUIRED
    return ExecutionStatus.ERROR


def codex_events(check):
    events = []
    if check.stdout and Path(check.stdout).is_file():
        for line in Path(check.stdout).read_text(errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):events.append(event)
    return events


def codex_diagnostic(events):
    """Only top-level failures authorize transport recovery; mixed/unknown errors do not."""
    errors = [e.get('error') if e.get('type') == 'turn.failed' else e.get('message')
        for e in events if e.get('type') in {'turn.failed','error'}]
    messages = [' '.join(str(error[k]) for k in ('code','message') if error.get(k))
        if isinstance(error,dict) else str(error or '') for error in errors]
    def restricted(low):
        restrictive = ('cybersecurity','safety','policy','flagged','refus','permission','denied','cancel',
            'forbidden','authentication','quota','rate_limit','billing','credential','account')
        return (classify_failure(low) != ExecutionStatus.ERROR or any(s in low for s in restrictive)
            or re.search(r'\b(?:http(?:/\d(?:\.\d)?)?|status(?: code)?)\s*[:=]?\s*(?:403|429)\b',low))
    def missing(low):
        return any(s in low for s in ('session not found','thread not found','no session found'))
    def transport(low):
        return (not restricted(low) and not missing(low)
            and any(s in low for s in ('request timed out','stream disconnected','connection reset',
                'connection closed','tls handshake','unexpected eof','error sending request')))
    normalized = [m.lower() for m in messages]
    return {'message':redact('\n'.join(messages)),
        'transport_failure':bool(messages) and all(map(transport,normalized)),
        'session_unavailable':any(map(missing,normalized)) and
            all(not restricted(m) and (missing(m) or transport(m)) for m in normalized)}


def failure_reason(text: str) -> str:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"(?m)^ERROR:\s*(?=\{)", text):
        try:
            payload, _ = decoder.raw_decode(text[match.end():])
        except ValueError:
            continue
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict) and error.get("code") == "invalid_json_schema":
            return "Agent output schema rejected (invalid_json_schema): " + redact(str(error.get("message", "")))[:1000]
    return "Agent execution failed: " + redact(text.strip())[:1000] if text.strip() else "Agent execution blocked; inspect raw logs"


class CodexAgent:
    name = "codex"
    mock = False

    def __init__(self, reasoning_effort: str | None = None, model: str | None = None, provider=None, profile=None):
        self.reasoning_effort = reasoning_effort
        self.model = model
        self.provider = provider
        self.profile = profile
        self.profile_settings = common_settings(provider) if profile == 'single_agent' else {}

    def bind_inputs(self, root, repo):
        """Capture an explicitly selected catalog, including any behavioral template."""
        if not self.provider or not self.provider.model_catalog_path:return
        path=Path(self.provider.model_catalog_path).expanduser().resolve()
        if path.is_relative_to(repo.resolve()) or path.is_relative_to(root):
            raise ValueError('Model catalog must be a trusted input outside the target and run')
        raw=path.read_bytes();catalog=json.loads(raw)
        models=catalog.get('models',[]) if isinstance(catalog,dict) else []
        if not isinstance(models,list) or len(models)!=1 or not isinstance(models[0],dict) or models[0].get('slug')!=self.model:
            raise ValueError('Model catalog must contain exactly the configured model')
        efforts={item['effort'] for item in models[0].get('supported_reasoning_levels',[])}
        if self.reasoning_effort is not None and self.reasoning_effort not in efforts:
            raise ValueError('Requested reasoning effort is not supported by the selected catalog')
        folder=root/'agent-inputs';folder.mkdir(exist_ok=True)
        (folder/'models.json').write_bytes(raw)
        (folder/'models.json').chmod(0o444)
        write_json(folder/'catalog.json',{'source':str(path),'digest':digest(raw),'record':'agent-inputs/models.json'})

    def validate_inputs(self, root, config):
        expected=(config.agent_model,config.agent_reasoning_effort,config.codex_provider,config.codex_profile)
        if (self.model,self.reasoning_effort,self.provider,self.profile)!=expected:
            raise ValueError('Codex connection changed; start a new run')
        self.validate_profile(root)
        def connection(argv):
            return sorted((arg,argv[i+1]) for i,arg in enumerate(argv[:-1]) if arg=='-m' or
                arg=='-c' and (argv[i+1].split('=',1)[0] in {'model_reasoning_effort','model_provider','model_catalog_json','web_search'}
                    or argv[i+1].startswith('model_providers.')))
        options=connection(self.connection_options(root))
        for path in (root/'logs').glob('*/check.json'):
            record=json.loads(path.read_text())
            if record['action']=='agent_turn' and connection(record['command'])!=options:
                raise ValueError('Codex connection options changed; start a new run')
        if not self.provider or not self.provider.model_catalog_path:return
        record=json.loads((root/'agent-inputs/catalog.json').read_text())
        source=Path(self.provider.model_catalog_path).expanduser().resolve()
        if (record['source']!=str(source) or digest((root/'agent-inputs/models.json').read_bytes())!=record['digest']
                or source.is_file() and digest(source.read_bytes())!=record['digest']):
            raise ValueError('Codex model catalog changed; start a new run')

    def validate_profile(self, root, *, bind=False):
        """Compare durable policy before probes or cached actions can replace it."""
        path = root/'agent-inputs/runtime-settings.json'
        if self.profile is None:
            if path.exists():
                raise ValueError('Codex profile changed; start a new run')
            return
        home = Path(os.environ.get('CODEX_HOME', Path.home()/'.codex')).resolve()
        def normalized(settings):
            result = dict(settings)
            result['skills.config'] = [{**item, 'path': '$CODEX_HOME/' + str(Path(item['path']).relative_to(home))
                if Path(item['path']).is_relative_to(home) else item['path']} for item in settings.get('skills.config', [])]
            return result
        saved = json.loads(path.read_text()) if path.exists() else None
        if saved is None and getattr(self, '_profile_prepared', None):
            raise ValueError('Codex profile record disappeared; start a new run')
        if saved is not None and (saved.get('profile') != self.profile or 'settings' not in saved):
            raise ValueError('Missing or changed Codex profile basis; start a new run')
        if saved and 'skills.config' not in self.profile_settings:
            self.profile_settings['skills.config'] = [{**item, 'path': item['path'].replace('$CODEX_HOME/', str(home)+'/')}
                for item in saved['settings'].get('skills.config', [])]
        record = {'profile': self.profile, 'settings': normalized(self.profile_settings)}
        if saved is not None and saved != record:
            raise ValueError('Codex profile settings changed; start a new run')
        historical = []
        for log in (root/'logs').glob('*/check.json'):
            check = json.loads(log.read_text())
            if check.get('action') != 'agent_turn':continue
            historical.append(check)
            argv = check['command']; settings = {}
            for i, arg in enumerate(argv[:-1]):
                if arg == '-c':
                    key, value = argv[i+1].split('=', 1)
                    if key in self.profile_settings:settings[key] = tomllib.loads('value='+value)['value']
            if normalized(settings) != record['settings']:
                raise ValueError('Codex profile argv changed or incomplete; start a new run')
        if saved is None and historical:
            raise ValueError('Historical run has no durable Codex profile basis; start a new run')
        if bind and saved is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json(path, record)

    def connection_options(self, root, *, sandbox=False):
        options=codex_options(self.profile_settings)
        if self.model:options += ['-c','model='+json.dumps(self.model)] if sandbox else ['-m',self.model]
        if self.reasoning_effort is not None:options += ['-c','model_reasoning_effort='+json.dumps(self.reasoning_effort)]
        if self.provider:
            provider=self.provider
            options += ['-c','model_provider='+json.dumps(provider.id)]
            for key,value in dict(name=provider.id,base_url=provider.base_url,env_key=provider.env_key,
                    wire_api='responses',requires_openai_auth=False,supports_websockets=False).items():
                options += ['-c',f'model_providers.{provider.id}.{key}='+json.dumps(value)]
            options += ['-c','web_search="disabled"']
            if provider.model_catalog_path:
                options += ['-c','model_catalog_json='+json.dumps(str(root/'agent-inputs/models.json'))]
        return options

    def client_environment(self):
        if not self.provider:return None
        key=self.provider.env_key
        if not os.environ.get(key):raise ValueError('Missing provider credential environment variable: '+key+'; no model payload sent')
        allowed=('PATH','HOME','CODEX_HOME','TMPDIR','LANG','LC_ALL','SSL_CERT_FILE','SSL_CERT_DIR',
            'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','http_proxy','https_proxy','all_proxy','no_proxy')
        return {k:os.environ[k] for k in (*allowed,key) if k in os.environ}

    def probe(self, runner):
        version = runner.run(["codex", "--version"], runner.root, "agent_probe", "environment", 10)
        help_run = runner.run(["codex", "exec", "--help"], runner.root, "agent_capabilities", "environment", 10)
        resume_run = runner.run(["codex", "exec", "resume", "--help"], runner.root, "agent_resume_capabilities", "environment", 10)
        text = output(help_run)
        required = ["--output-schema", "--output-last-message", "--skip-git-repo-check", "--json", "--ignore-user-config"]
        self.available = (version.status == ExecutionStatus.COMPLETED and version.exit_code == 0
            and all(s in text for s in required) and "SESSION_ID" in output(resume_run))
        self.version = output(version).strip()
        self.missing = version.status == ExecutionStatus.TOOL_MISSING
        return {"available": self.available, "version": self.version, "checks": [version, help_run, resume_run], "reason": "Codex CLI session and JSONL capabilities detected" if self.available else "Codex missing or required Codex session capabilities unavailable"}

    def permission_options(self, root, directory):
        """Scope model-controlled commands to the captured source, draft, and retained evidence."""
        executable = shutil.which("codex")
        if not executable:
            raise FileNotFoundError("Codex executable is unavailable")
        codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).resolve()
        # Deny the host temp path, not the draft TMPDIR set for sandboxed tools below.
        from consensus_assurance.adapters.validation import validation_tool
        tool_paths = validation_tool(root)['read_only_paths']
        if any(Path(p) == root or root.is_relative_to(Path(p)) or Path(p).is_relative_to(directory) for p in tool_paths):
            raise ValueError('Validator installation must be separate from writable drafts and retained runs')
        filesystem={":root":"deny",":minimal":"read",":slash_tmp":"deny",
            str(Path(os.environ.get("TMPDIR") or "/tmp").resolve()):"deny",
            str(root/"agent-source"):"read",str(directory):"write",
            str(root/"direct-checks"):"read",str(root/"submissions"):"read",
            str(root/"state.json"):"read",str(root/"research.json"):"read",
            str(root/"submission.schema.json"):"read",str(root/"product-schemas.json"):"read",
            str(root/"audit-method.md"):"read",
            str(root/"target-support"):"read",
            str(root/"build-inputs"):"read",
            str(root/"agent-inputs"):"read",
            **{str(root/name):"read" for name in ("logs","findings","audit-spec","actions")},
            **{str(path):"read" for path in getattr(self,"read_only_roots",[]) if path.is_dir()},
            **{path:"read" for path in tool_paths},
            str(codex_home/"tmp"/"arg0"):"read",str(Path(executable).resolve().parent):"read"}
        inline="{"+",".join(json.dumps(key)+"="+json.dumps(value) for key,value in filesystem.items())+"}"
        environment={"GOCACHE":str(directory/"go-cache"),"GOMODCACHE":str(directory/"go-mod-cache"),
            "TMPDIR":str(directory/"tmp"),"GOPROXY":"off","GOSUMDB":"off","GOTOOLCHAIN":"local","GOFLAGS":"-mod=readonly"}
        environment.update(getattr(self,"tool_environment",{}))
        if self.provider and self.provider.env_key.upper() in {k.upper() for k in environment}:
            raise ValueError('Provider credential cannot be a tool environment setting')
        return ["-c",'default_permissions="ca_audit"',
            "-c","permissions.ca_audit.filesystem="+inline,
            "-c","permissions.ca_audit.network.enabled=false",
            "-c",'shell_environment_policy.inherit="core"',
            *(['-c','shell_environment_policy.filters={'+json.dumps(self.provider.env_key)+'="exclude"}'] if self.provider else []),
            "-c","shell_environment_policy.set={"+",".join(json.dumps(k)+"="+json.dumps(v) for k,v in environment.items())+"}",
            "-c","project_doc_max_bytes=0", "-c","tools.web_search=false",
            "-c","memories.use_memories=false", "-c","memories.generate_memories=false"]

    def sandbox_command(self, root):
        """Hide non-path nsfs mount roots from affected Codex Linux sandbox builds."""
        try:
            affected=any(not line.split()[3].startswith("/") for line in
                Path("/proc/self/mountinfo").read_text().splitlines() if len(line.split())>4)
        except OSError:
            affected=False
        if not affected:
            return ["codex"]
        bubblewrap=shutil.which("bwrap")
        if not bubblewrap:
            raise RuntimeError("Codex sandbox requires Bubblewrap on this nsfs-mounted host")
        codex_home=Path(os.environ.get("CODEX_HOME",Path.home()/".codex")).resolve()
        return [bubblewrap,"--ro-bind","/","/","--bind","/tmp","/tmp",
            "--bind",str(root),str(root),"--bind",str(codex_home),str(codex_home),
            "--proc","/proc","--dev","/dev","--","codex"]

    def permission_probe(self, runner, directory, snapshot_id, options):
        """Positive controls and explicit denied operations; a crashed probe proves nothing."""
        source = next((p for p in (runner.root / "agent-source").rglob("*") if p.is_file()), None)
        if source is None:
            return False, []
        private = runner.root / "codex-private-canary"
        private.write_text("private permission canary")
        from consensus_assurance.adapters.validation import validation_tool
        tool = validation_tool(runner.root)
        protected = [source, Path(__file__)]
        for folder in ("logs", "direct-checks"):
            path = runner.root / folder / "permission-canary"
            path.parent.mkdir(exist_ok=True)
            path.write_text("retained permission canary")
            protected.append(path)
        build_input=next((runner.root/'build-inputs').glob('targets/**/basis.json'),None)
        if build_input:protected.append(build_input)
        protected.extend(p for p in (runner.root/'agent-inputs').glob('*.json'))
        script = directory / ".permission-probe.py"
        script.write_text(
            "import errno, os, pathlib, socket, tempfile, subprocess\n"
            "def denied(label, fn):\n"
            "    try: fn()\n"
            "    except OSError as exc:\n"
            "        if exc.errno not in (errno.EACCES, errno.EPERM, errno.EROFS, errno.ENOENT): raise\n"
            "        print('DENIED:' + label)\n"
            "    else: raise RuntimeError('UNSAFE:' + label)\n"
            + ("assert "+repr(self.provider.env_key)+" not in os.environ\nprint('CREDENTIAL_ABSENT')\n" if self.provider else '')
            + "protected = " + repr([str(p) for p in protected]) + "\n"
            "for i, name in enumerate(protected):\n"
            "    path = pathlib.Path(name); path.read_bytes(); print('READ:' + str(i))\n"
            "    denied('write:' + str(i), lambda: path.open('a'))\n"
            + "denied('private', lambda: pathlib.Path(" + repr(str(private)) + ").read_bytes())\n"
            "denied('network', lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(('127.0.0.1', 9)))\n"
            + "pathlib.Path(" + repr(str(directory / '.write-control')) + ").write_text('allowed')\n"
            "with tempfile.TemporaryFile(dir=os.environ['TMPDIR']) as stream:\n"
            "    stream.write(b'temp control'); stream.seek(0)\n"
            "    assert stream.read() == b'temp control'\n"
            + "command = " + repr(tool['command'][:-4] + ['validate', '--help']) + "\n"
            "result = subprocess.run(command, capture_output=True, text=True)\n"
            "assert result.returncode == 0 and '--submission' in result.stdout, result.stderr\n"
            "print('PERMISSIONS_VERIFIED')\n")
        try:
            environment=self.client_environment() if self.provider else None
            if environment is not None:environment[self.provider.env_key]='ca-provider-permission-canary'
            check = runner.run([*self.sandbox_command(runner.root), "sandbox", "-P", "ca_audit", *options,*self.connection_options(runner.root,sandbox=True),
                "-C", str(directory), "/usr/bin/python3", str(script)], directory,
                "codex_permission_probe", snapshot_id, 15,
                **({'env':environment,'sensitive_env':(self.provider.env_key,)} if self.provider else {}))
            verified = check.status == ExecutionStatus.COMPLETED and check.exit_code == 0 and "PERMISSIONS_VERIFIED" in output(check)
            check.parameters['permission_result'] = 'verified' if verified else 'inconclusive_or_unsafe'
            return verified, [check]
        finally:
            for path in [private, script, directory / '.write-control',
                    *(runner.root/folder/'permission-canary' for folder in ('logs','direct-checks'))]:
                path.unlink(missing_ok=True)

    def prepare(self, runner, directory, snapshot_id):
        self.validate_profile(runner.root)
        self.client_environment()
        (directory / "tmp").mkdir(parents=True, exist_ok=True)
        profile_checks = []
        profile_key = (str(runner.root), os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
        if self.profile == 'single_agent' and getattr(self, '_profile_prepared', None) != profile_key:
            # --ignore-user-config is used on real turns, so the policy must be explicit argv.
            for name in ('bootstrap', 'prompt', 'features'):
                args = ['features', 'list'] if name == 'features' else ['debug', 'prompt-input', 'Local configuration inspection only.']
                command = self.sandbox_command(runner.root)
                if command[0].endswith('bwrap'):
                    command = [command[0], '--unshare-net', *command[1:]]
                else:
                    home = Path(os.environ.get('CODEX_HOME', Path.home()/'.codex')).resolve()
                    home.mkdir(parents=True, exist_ok=True)
                    command = ['bwrap', '--unshare-net', '--ro-bind', '/', '/', '--bind', str(runner.root), str(runner.root),
                        '--bind', str(home), str(home), '--', *command]
                check = runner.run([*command, *args, *self.permission_options(runner.root, directory),
                    *self.connection_options(runner.root, sandbox=True)], directory, 'codex_profile_' + name, snapshot_id, 30,
                    env=self.client_environment(), sensitive_env=(self.provider.env_key,) if self.provider else ())
                profile_checks.append(check)
                if check.status != ExecutionStatus.COMPLETED or check.exit_code != 0:
                    return False, profile_checks
                if name == 'bootstrap':
                    home = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')).resolve()
                    self.profile_settings['skills.config'] = [{'path':str(path),'enabled':False} for path in sorted(home.glob('skills/**/SKILL.md'))]
                elif name == 'prompt':
                    items = json.loads(Path(check.stdout).read_text())
                    kinds = [kind for item in items for kind in item.get('internal_chat_message_metadata_passthrough',{}).get('content_item_kinds',[])]
                    if any(kind in {'host_skills.instructions','agents_md.instructions'} or 'memory' in kind or 'plugin' in kind for kind in kinds):
                        check.reason = 'Unexpected automatic instructions'; return False, profile_checks
                else:
                    features = {line.split()[0]:line.split()[-1] for line in Path(check.stdout).read_text().splitlines() if len(line.split()) >= 3}
                    if any(features.get(name) != 'false' for name in DISABLED_FEATURES):
                        check.reason = 'Single-agent settings were not effective'; return False, profile_checks
            self.validate_profile(runner.root, bind=True)
            self._profile_prepared = profile_key
        options = self.permission_options(runner.root, directory)
        key = (str(runner.root), tuple(options), tuple(self.connection_options(runner.root)), getattr(self, 'version', 'unknown'))
        if getattr(self, '_permission_key', None) == key:
            return True, profile_checks
        permitted, checks = self.permission_probe(runner, directory, snapshot_id, options)
        if permitted:
            self._permission_key = key
        return permitted, profile_checks + checks

    def investigate(self, runner, prompt, directory, snapshot_id, timeout, session_id=None):
        """Run one Codex turn and retain the exact session and tool events."""
        self.validate_profile(runner.root)
        directory.mkdir(parents=True, exist_ok=True)
        schema = runner.root / "agent-final.schema.json"
        write_json(schema, {"type":"object","properties":{
            "submission":{"type":"string"},"summary":{"type":"string"}},
            "required":["submission","summary"],"additionalProperties":False})
        if not getattr(self, "available", False):
            return CheckRun(action="agent_turn", cwd=str(directory), snapshot_id=snapshot_id,
                status=ExecutionStatus.TOOL_MISSING if getattr(self, "missing", False) else ExecutionStatus.ERROR,
                reason="Codex capability probe failed"), None, None
        options=self.permission_options(runner.root,directory)
        if getattr(self, '_permission_key', None) != (str(runner.root), tuple(options), tuple(self.connection_options(runner.root)), getattr(self, 'version', 'unknown')):
            raise RuntimeError("Codex permission profile must be prepared before reserving a model call")
        response = runner.root / "actions" / (runner.active_action_id or "standalone") / "agent-response.json"
        response.parent.mkdir(parents=True, exist_ok=True)
        command = [*self.sandbox_command(runner.root), "exec"]
        if session_id:
            command.append("resume")
        command += ["--skip-git-repo-check", "--ignore-user-config", "--json",
            "--output-schema", str(schema), "--output-last-message", str(response), *options,*self.connection_options(runner.root)]
        command += [session_id, "-"] if session_id else ["-"]
        check = runner.run(command, directory, "agent_turn", snapshot_id, timeout, stdin=prompt,
            **({'env':self.client_environment(),'sensitive_env':(self.provider.env_key,)} if self.provider else {}))
        return self.decode(check, response, session_id)

    def decode(self, check, response, session_id=None):
        """Decode a durable Agent receipt without invoking another model turn."""
        check.tool_version = getattr(self, "version", "unknown")
        events = codex_events(check)
        started = [e.get("thread_id") for e in events if e.get("type") == "thread.started"]
        actual_id = started[-1] if started else None
        completed = [e for e in events if e.get("type") == "turn.completed"]
        diagnostic = codex_diagnostic(events)
        if session_id and actual_id and actual_id != session_id:
            check.status = ExecutionStatus.ERROR
            check.reason = "Agent session identity changed unexpectedly"
            diagnostic['transport_failure'] = False
        if check.status == ExecutionStatus.COMPLETED and (check.exit_code != 0
                or any(e.get("type") == "turn.failed" for e in events)
                or (not completed and any(e.get("type") == "error" for e in events))):
            # Startup stderr remains useful diagnosis, but never transport retry authority.
            failure = diagnostic['message'] or (output(check) if not events else
                Path(check.stderr).read_text(errors='replace') if check.stderr and Path(check.stderr).is_file() else '')
            check.status = classify_failure(failure)
            check.reason = failure_reason(failure)
            if session_id and diagnostic['session_unavailable']:
                check.parameters["agent_session_unavailable"]=True
        if completed and not (actual_id or session_id):
            check.status = ExecutionStatus.ERROR
            check.reason = "Agent turn completed without a recoverable session identity"
        check.parameters.update({"agent_session_id":actual_id or session_id,
            "agent_diagnostic":{**diagnostic, 'message':diagnostic['message'][:2000]},
            "agent_response_path":str(response),
            "agent_turn_completed":bool(completed),
            "agent_tool_events":len({e['item']['id'] for e in events if e.get('type') == 'item.completed'
                and isinstance(e.get('item'),dict) and e['item'].get('id') and e['item'].get('type') in
                {'command_execution','file_change','mcp_tool_call','web_search'}}),
            "agent_usage":completed[-1].get("usage") if completed else None,
            "agent_sandbox":"ca_audit: root deny, captured source/evidence read, draft write, tool network off",
            "permission_probe":"verified before model call; cached for this process/profile",
            "agent_model":self.model or "CLI default; inspect raw Codex events",
            "codex_provider":self.provider.model_dump(mode='json') if self.provider else None,
            "agent_reasoning_effort":self.reasoning_effort or "CLI default"})
        if check.status != ExecutionStatus.COMPLETED or not completed:
            if check.status == ExecutionStatus.COMPLETED:
                check.status = ExecutionStatus.ERROR
                check.reason = "Agent turn lacked a completed event"
            return check, actual_id or session_id, None
        try:
            result = json.loads(response.read_text())
            if (not isinstance(result, dict) or set(result) != {"submission", "summary"}
                    or not all(isinstance(value, str) for value in result.values())):
                raise ValueError("Agent final response has the wrong shape")
            return check, actual_id or session_id, result
        except (OSError, ValueError) as exc:
            check.reason = "Agent final response invalid: " + str(exc)
            check.parameters["agent_response_error"] = check.reason
            return check, actual_id or session_id, {"submission":"", "summary":check.reason}

class MockAgent:
    """Explicit file-product playback through the same audit product boundary."""
    name = "mock"
    mock = True

    def __init__(self, fixture=None):
        self.fixture = Path(fixture).resolve() if fixture else None
        self.cursor = 0
        self.responses = json.loads(self.fixture.read_text()) if self.fixture else []
        self.available = bool(self.responses)

    def probe(self, runner):
        return {"available":self.available, "version":"audit-fixture/1", "checks":[],
            "reason":"Explicit product playback; no autonomous discovery evidence"}

    def investigate(self, runner, prompt, directory, snapshot_id, timeout, session_id=None):
        if self.cursor >= len(self.responses):
            return CheckRun(action="agent_turn", status=ExecutionStatus.ERROR,
                snapshot_id=snapshot_id, origin=Origin.MOCK, reason="Audit fixture exhausted"), session_id, None
        item = self.responses[self.cursor]
        self.cursor += 1
        from consensus_assurance.workflow.audit import draft_file
        for name, content in item.get("files", {}).items():
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Fixture path escapes draft")
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            draft_file(directory, name)
        write_json(directory / "submission.json", item["submission"])
        return CheckRun(action="agent_turn", cwd=str(directory), snapshot_id=snapshot_id,
            origin=Origin.MOCK, status=ExecutionStatus.COMPLETED, exit_code=0), session_id or "fixture-session", {
            "submission":"submission.json", "summary":"Explicit fixture product"}
