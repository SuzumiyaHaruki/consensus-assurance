"""Fixed input capture, bounded same-session turns, and append-only handoffs."""
import json
import hashlib
import importlib.metadata
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from consensus_assurance.adapters.storage.files import digest, write_json
from consensus_assurance.adapters.storage.snapshot import (
    EXCLUDED_DIRS, KEY_NAME, SOURCE_SUFFIXES, SENSITIVE_CONTENT, SENSITIVE_NAME,
)

from .codex import Codex, decode, options


TASK = Path(__file__).with_name("task.md")
EXCLUDED = EXCLUDED_DIRS | {".execution", ".pytest_cache", ".mypy_cache"}
WORK_EXCLUDED = EXCLUDED | {".runtime"}


def implementation_identity(root):
    """Record only loaded execution inputs, not the repository or dependency trees."""
    project = Path(__file__).resolve().parents[1]
    paths = {"baseline/" + name: project / "baseline" / name for name in ("__main__.py", "codex.py", "runner.py", "local_exec.py", "requirements.txt", "task.md")}
    neutral = ("consensus_assurance.core.config", "consensus_assurance.core.types",
               "consensus_assurance.adapters.agents.backend", "consensus_assurance.adapters.runners.go_module",
               "consensus_assurance.adapters.runners.experiment", "consensus_assurance.adapters.runners.process",
               "consensus_assurance.adapters.storage.files", "consensus_assurance.adapters.storage.snapshot")
    paths.update({name: Path(sys.modules[name].__file__).resolve() for name in neutral})
    relative = [str(path.relative_to(project)) for path in paths.values() if path.is_relative_to(project)]
    dirty = git(project, "status", "--porcelain", "--untracked-files=all", "--", *relative).decode()
    commit = git(project, "rev-parse", "HEAD").decode().strip()
    entries = {}
    for label, path in paths.items():
        data = path.read_bytes()
        entries[label] = {"path": str(path), "sha256": digest(data),
                          "framework_relative_path": str(path.relative_to(project)) if path.is_relative_to(project) else None,
                          "version_basis": "framework Git and recorded bytes" if path.is_relative_to(project) else "external installed bytes; framework HEAD does not identify this module"}
        if dirty or not path.is_relative_to(project):
            # Save only execution inputs, and never archive credential-like source bytes.
            if SENSITIVE_CONTENT.search(data):
                entries[label]["saved_bytes"] = "excluded: credential-like content"
            else:
                destination = root / "inputs/implementation-source" / (label.replace("/", "__") + ".txt")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                entries[label]["saved_bytes"] = str(destination.relative_to(root))
    try:
        package_version = importlib.metadata.version("consensus-assurance")
    except importlib.metadata.PackageNotFoundError:
        package_version = "unknown"
    return {"generated_at": now(), "framework_commit": commit, "execution_inputs_dirty": bool(dirty),
            "execution_input_changes": dirty.splitlines(), "inputs": entries, "package_version": package_version,
            "python": sys.executable, "catalog_record": "inputs/models.json", "server_model_revision": "unknown",
            "config_record": "inputs/config.json", "task_record": "inputs/task.md",
            "execution_service_record": "inputs/local-exec.json",
            "protocol_dependencies": {name: importlib.metadata.version(name) for name in ('mcp','anyio','pydantic','jsonschema')}}


def executable_identity(client):
    path = getattr(client, "executable", None)
    if not path:
        return {"status": "not measured: test double"}
    path = Path(path)
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    info = path.stat()
    return {"path": str(path), "version": client.version, "sha256": hasher.hexdigest(),
            "stat": [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]}


def finish_identity(root, identity):
    changed = []
    for label, entry in identity["inputs"].items():
        path = Path(entry["path"])
        if not path.is_file() or digest(path.read_bytes()) != entry["sha256"]:
            changed.append(label)
    executable = identity.get("codex", {})
    if "path" in executable:
        try:
            info = Path(executable["path"]).stat()
            if [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns] != executable["stat"]:
                changed.append("codex_binary_metadata")
        except OSError:
            changed.append("codex_binary_metadata")
    result = {"checked_at": now(), "inputs_unchanged": not changed, "changed_inputs": changed,
              "basis": "entry bytes rechecked; binary stat rechecked; startup identity preserved"}
    write_json(root / "inputs/implementation-end.json", result)
    return result


def now():
    return datetime.now(timezone.utc).isoformat()


def git(repo, *args, deadline=None, stdin=None):
    timeout = min(30, deadline - time.monotonic()) if deadline else 30
    if timeout <= 0:
        raise TimeoutError("Total deadline reached during source capture")
    result = subprocess.run(["git", "--no-optional-locks", "-c", "core.fsmonitor=false",
                             "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args], input=stdin,
                            capture_output=True, timeout=timeout)
    if result.returncode:
        raise ValueError("Git input capture failed: " + result.stderr.decode(errors="replace"))
    return result.stdout


def capture_source(repo, destination, deadline):
    repo = Path(repo)
    if git(repo, "status", "--porcelain", "--untracked-files=all", deadline=deadline).strip():
        raise ValueError("Target must be a clean Git commit; dirty files are never cleaned automatically")
    commit = git(repo, "rev-parse", "HEAD", deadline=deadline).decode().strip()
    tree = git(repo, "ls-tree", "-rz", "--full-tree", commit, deadline=deadline)
    entries, excluded = [], {}
    for record in tree.split(b"\0"):
        if not record:
            continue
        meta, raw_name = record.split(b"\t", 1)
        mode, kind, oid = meta.decode().split()
        name = raw_name.decode("utf-8")
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Unsafe Git tree path")
        if (set(path.parts) & EXCLUDED or path.name in {"AGENTS.md", "SKILL.md"}
                or SENSITIVE_NAME.search(path.name) or (KEY_NAME.search(path.name) and path.suffix.lower() not in SOURCE_SUFFIXES)
                or mode not in {"100644", "100755"} or kind != "blob"):
            excluded[name] = "instruction, private, excluded directory, link, or submodule"
        else:
            entries.append((name, mode, oid))
    payload = git(repo, "cat-file", "--batch", deadline=deadline,
                  stdin="".join(oid + "\n" for _, _, oid in entries).encode()) if entries else b""
    offset, files = 0, {}
    destination.mkdir(parents=True, exist_ok=True)
    for name, mode, oid in entries:
        if time.monotonic() >= deadline:
            raise TimeoutError("Total deadline reached during source capture")
        end = payload.index(b"\n", offset)
        header = payload[offset:end].decode().split()
        if header[:2] != [oid, "blob"]:
            raise ValueError("Unexpected Git object response")
        size = int(header[2])
        data = payload[end + 1:end + 1 + size]
        offset = end + size + 2
        if SENSITIVE_CONTENT.search(data):
            excluded[name] = "credential-like content"
            continue
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(int(mode, 8) & 0o777)
        files[name] = {"git_blob": oid, "mode": mode, "size": size}
    if not files:
        raise ValueError("No authorized regular source files remain")
    return {"commit": commit, "files": files, "excluded": excluded, "capture": "committed Git blobs, no history"}


def file_inventory(root, *, exclude=WORK_EXCLUDED):
    """Hash mutable output bytes only, never follow links or archive special files."""
    files, excluded = {}, {}
    for folder, dirs, names in os.walk(root, followlinks=False):
        for name in list(dirs):
            path = Path(folder) / name
            if name in exclude or path.is_symlink():
                dirs.remove(name)
                excluded[str(path.relative_to(root))] = "excluded directory or symlink"
        for name in names:
            path = Path(folder) / name
            rel = str(path.relative_to(root))
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                excluded[rel] = "symlink, hardlink, or nonregular file"
                continue
            if (SENSITIVE_NAME.search(name) or (KEY_NAME.search(name) and path.suffix.lower() not in SOURCE_SUFFIXES)
                    or name.endswith(".lock.tmp")):
                excluded[rel] = "private or transient file"
                continue
            data = path.read_bytes()
            if SENSITIVE_CONTENT.search(data):
                excluded[rel] = "credential-like content"
                continue
            files[rel] = {"digest": digest(data), "mode": stat.S_IMODE(info.st_mode), "size": len(data)}
    return files, excluded


def save_changes(work, folder, previous):
    actual, excluded = file_inventory(work)
    changed = {name: info for name, info in actual.items() if previous.get(name) != info}
    for name in changed:
        destination = folder / "files" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(work / name, destination)
        destination.chmod(actual[name]["mode"])
    write_json(folder / "manifest.json", {"changed": changed, "deleted": sorted(previous.keys() - actual.keys()),
                                          "excluded": excluded, "basis": "previous retained turn, initially source",
                                          "timing": "end of turn, not input at each command start"})
    return actual


def freeze(root):
    for folder, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(folder) / d).is_symlink()]
        for name in names:
            path = Path(folder) / name
            if not path.is_symlink() and stat.S_ISREG(path.lstat().st_mode):
                path.chmod(path.stat().st_mode & ~0o222)
        Path(folder).chmod(0o555)


def scrub_work(root):
    work = root / "work"
    _, excluded = file_inventory(work)
    write_json(root / "inputs/work-exclusions.json", excluded)
    for relative in sorted(excluded, key=lambda x: len(Path(x).parts), reverse=True):
        path = work / relative
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def tcp_smoke_case(backend):
    """A small, inspectable two-way TCP test; only its reply assertion changes between turns."""
    if backend == 'go_module':
        path, command = 'sample/tcp_test.go', ['go', 'test', '-count=1', '-run', '^TestTCPRoundtrip$', '-v', './sample']
        before = '''package sample
import ("io"; "net"; "testing"; "time")
func TestTCPRoundtrip(t *testing.T) {
    const wantReply = "wrong"
    listener, err := net.Listen("tcp", "127.0.0.1:0"); if err != nil { t.Fatal(err) }; defer listener.Close()
    client, err := net.DialTimeout("tcp", listener.Addr().String(), 5*time.Second); if err != nil { t.Fatal(err) }; defer client.Close()
    server, err := listener.Accept(); if err != nil { t.Fatal(err) }; defer server.Close()
    if err = client.SetDeadline(time.Now().Add(5*time.Second)); err != nil { t.Fatal(err) }
    if err = server.SetDeadline(time.Now().Add(5*time.Second)); err != nil { t.Fatal(err) }
    if _, err = client.Write([]byte("ping")); err != nil { t.Fatal(err) }
    request := make([]byte, 4); if _, err = io.ReadFull(server, request); err != nil { t.Fatal(err) }
    if _, err = server.Write([]byte("pong")); err != nil { t.Fatal(err) }
    reply := make([]byte, 4); if _, err = io.ReadFull(client, reply); err != nil { t.Fatal(err) }
    t.Logf("TCP_OBSERVED request=%s reply=%s", request, reply)
    if string(request) != "ping" { t.Fatalf("request mismatch: %q", request) }
    if string(reply) != wantReply { t.Fatalf("TCP_REPLY_ASSERTION: want %q, got %q", wantReply, reply) }
}
'''
        passed = '--- PASS: TestTCPRoundtrip'
    else:
        path, command = 'tests/tcp_roundtrip.rs', ['cargo', 'test', '--offline', '--test', 'tcp_roundtrip', '--', '--exact', 'tcp_roundtrip', '--nocapture']
        before = '''use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::time::Duration;
#[test]
fn tcp_roundtrip() {
    let want_reply = "wrong";
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let mut client = TcpStream::connect_timeout(&listener.local_addr().unwrap(), Duration::from_secs(5)).unwrap();
    let (mut server, _) = listener.accept().unwrap();
    client.set_read_timeout(Some(Duration::from_secs(5))).unwrap();
    server.set_read_timeout(Some(Duration::from_secs(5))).unwrap();
    client.write_all(b"ping").unwrap();
    let mut request = [0; 4]; server.read_exact(&mut request).unwrap();
    server.write_all(b"pong").unwrap();
    let mut reply = [0; 4]; client.read_exact(&mut reply).unwrap();
    println!("TCP_OBSERVED request={} reply={}", std::str::from_utf8(&request).unwrap(), std::str::from_utf8(&reply).unwrap());
    assert_eq!(&request, b"ping");
    assert_eq!(std::str::from_utf8(&reply).unwrap(), want_reply, "TCP_REPLY_ASSERTION");
}
'''
        passed = 'test result: ok. 1 passed'
    return {'path': path, 'argv': command, 'before': before, 'after': before.replace('"wrong"', '"pong"'), 'passed': passed}


def synthetic_source(destination, backend, *, tcp=False):
    files = {"go.mod": "module baseline.local/smoke\n\ngo 1.20\n", "sample/value.go":
             "package sample\nfunc Add(a, b int) int { return a + b }\n"} if backend == "go_module" else {
             "Cargo.toml": '[package]\nname = "baseline-smoke"\nversion = "0.1.0"\nedition = "2021"\n',
             "src/lib.rs": "pub fn add(a: i32, b: i32) -> i32 { a + b }\n"}
    files["fixture.txt"] = "context-token-" + uuid4().hex + "\n"
    if tcp:
        case = tcp_smoke_case(backend)
        files[case['path']] = case['before']
    for name, text in files.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return {"commit": None, "kind": "synthetic compatibility fixture", "files": sorted(files)}


def brief(root, source, target, deadline, timeout, calls_left):
    remaining = max(0, deadline - time.monotonic())
    return "\n\nRun brief (host facts):\n" + json.dumps({
        "working_directory": str(root / "work"), "read_only_source": str(root / "source"),
        "source_identity": source.get("commit") or source.get("kind"), "scope": target,
        "report_path": str(root / "work/report.md"), "retained_logs": str(root / "turns"),
        "permissions": "Source/logs read only; work writable; ordinary shell has no network. isolated_exec supports private local TCP; no host or external network.",
        "tool_environment": "Offline Go/Cargo; writable temporary and cache paths in work/.runtime.",
        "remaining_total_seconds": remaining, "turn_timeout_seconds": timeout, "remaining_agent_calls": calls_left,
        "generated_at": now(), "estimated_turn_deadline_utc": (datetime.now(timezone.utc) + timedelta(seconds=timeout)).isoformat(),
        "deadline_basis": "Host monotonic clock; preparation, tool work and model waiting all consume total time."}, indent=2)


def smoke_prompt(second=False, backend='go_module'):
    case = tcp_smoke_case(backend)
    execution = json.dumps({'argv': case['argv'], 'cwd': '.', 'timeout_seconds': 90})
    if second:
        return ("Continue this same synthetic compatibility session. Read the previous isolated_exec result and note.txt. "
                f"In {case['path']}, change only the expected reply from wrong to pong; preserve the TCP test body. "
                f"Call baseline_local.isolated_exec again with {execution}, and inspect its actual result and output. "
                "Explain the previous TCP_REPLY_ASSERTION failure and the new result in your normal text handoff; "
                "include the fixture token. Do not audit consensus code. If externally blocked, begin RUN_BLOCKED:.")
    return ("This is an authorized synthetic coding-tool compatibility check, not a consensus audit. "
            "Read fixture.txt and the source. Remember the fixture token in this conversation and in note.txt. "
            f"Read {case['path']}; it manages both TCP endpoints in one test and deliberately expects the wrong reply. "
            f"Leave the test unchanged in this turn. Call baseline_local.isolated_exec with {execution}. "
            "Use tool_search if the tool is deferred. Read the actual failure output; a nonzero test exit is expected "
            "and is not an MCP service failure. Preserve the test for correction in the next turn. "
            "Return a normal text handoff explaining the observed result. If externally blocked, begin RUN_BLOCKED:.")


def smoke_observations(root, record):
    turns = record["turns"]
    case = tcp_smoke_case(json.loads((root/'inputs/target.json').read_text())['execution_backend'])
    calls, completions = [], []
    for turn in turns:
        folder = root / turn['path']
        receipt = json.loads((folder/'result.json').read_text())
        decoded = decode(folder, {'status': receipt['status'], 'exit_code': receipt.get('exit_code')}, turn.get('session_id'))
        completions.append(turn['status'] == decoded['status'] == 'completed')
        for line in (folder/'stdout.jsonl').read_text(errors='replace').splitlines():
            try:
                event = json.loads(line)
                item = event.get('item', {})
                if (event.get('type') != 'item.completed' or item.get('type') != 'mcp_tool_call'
                        or item.get('status') != 'completed' or item.get('server') != 'baseline_local'
                        or item.get('tool') != 'isolated_exec' or item.get('error') or not item.get('id')):
                    continue
                returned = item['result']['structured_content']
                execution_id = returned['execution_id']
                if not re.fullmatch(r'[0-9a-f]{32}', execution_id):continue
                path = root/'executions'/execution_id/'result.json'
                if path.is_symlink() or path.resolve().parent.parent != (root/'executions').resolve():continue
                actual = json.loads(path.read_text())
                args = item['arguments']
                if (returned != actual or actual['turn'] != folder.name or actual['status'] != 'completed'
                        or actual['argv'] != args['argv'] or args['argv'] != case['argv']
                        or args.get('cwd', '.') != '.' or actual['cwd'] != str(root/'work')
                        or actual['requested_timeout_seconds'] != args.get('timeout_seconds')):
                    continue
                output = ''.join((path.parent/(name+'.txt')).read_text(errors='replace') for name in ('stdout', 'stderr'))
                calls.append({'turn': turn['number'], 'item_id': item['id'], 'execution_id': execution_id,
                              'mcp_request_id': actual['mcp_request_id'], 'exit_code': actual['exit_code'],
                              'tcp_observed': 'TCP_OBSERVED request=ping reply=pong' in output,
                              'assertion_failed': 'TCP_REPLY_ASSERTION' in output, 'test_passed': case['passed'] in output})
            except (ValueError, KeyError, TypeError, AttributeError, OSError):
                continue
    token = (root / "source/fixture.txt").read_text().strip()
    note, final = root / "work/note.txt", root / "turns/0002/final.txt"
    versions = []
    path = root/'source'/case['path']
    for number in (1, 2):
        changed = root/'turns'/f'{number:04d}'/'changes/files'/case['path']
        if changed.is_file():path = changed
        versions.append(path.read_text() if path.is_file() and not path.is_symlink() else '')
    observed = {
        "two_completed_turns": len(turns) == 2 and all(completions),
        "same_session": len(turns) == 2 and bool(turns[0]["session_id"]) and turns[0]["session_id"] == turns[1]["session_id"],
        "first_turn_tcp_assertion_failure": any(c['turn'] == 1 and c['exit_code'] not in (0, None)
                                                and c['tcp_observed'] and c['assertion_failed'] for c in calls),
        "second_turn_tcp_test_passed": any(c['turn'] == 2 and c['exit_code'] == 0
                                           and c['tcp_observed'] and c['test_passed'] for c in calls),
        "same_test_repaired": versions == [case['before'], case['after']],
        "file_read_and_written": note.is_file() and not note.is_symlink() and token in note.read_text(errors="replace"),
        "context_token_in_second_final": final.is_file() and token in final.read_text(errors="replace"),
        "second_final_discusses_failure": final.is_file() and 'TCP_REPLY_ASSERTION' in final.read_text(errors='replace'),
    }
    write_json(root / "inputs/smoke-observations.json", {"observed": observed, "calls": calls, "complete": all(observed.values()),
               "review": "Synthetic tool compatibility only, not autonomous discovery or a consensus verdict. Inspect both native MCP items, correlated raw execution outputs, test versions and the second explanation. Retained test versions describe turn boundaries, not the exact instant each command started; response text alone does not prove semantic understanding."})
    return all(observed.values())


def loop(config, root, source, target, client, deadline, record, *, smoke=False):
    task, continuation = (root / "inputs/task.md").read_text().split("<!-- continuation -->")
    previous, _ = file_inventory(root / "work")
    session, completed_report = None, None
    for number in range(1, config.budget.agent_calls + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            record["stop"] = "total_deadline"
            break
        timeout = min(config.budget.agent_turn_timeout, remaining)
        folder = root / "turns" / f"{number:04d}"
        folder.mkdir()
        prompt = smoke_prompt(number > 1, target['execution_backend']) if smoke else (task if number == 1 else continuation)
        prompt += brief(root, source, target, deadline, timeout, config.budget.agent_calls - number + 1)
        (folder / "request.txt").write_text(prompt)
        remaining = max(0, deadline - time.monotonic())
        try:
            result = client.turn(folder, prompt, min(timeout, remaining), session)
        except KeyboardInterrupt:
            result = {"status": "cancelled", "session_id": session}
        except (ValueError, OSError) as exc:
            result = {"status": "external_blocker_needs_review", "session_id": session, "reason": str(exc)}
        result["timeout_limit"] = "total_seconds" if remaining <= config.budget.agent_turn_timeout else "agent_turn_timeout"
        result["ended_at"] = now()
        result["run_elapsed_seconds"] = time.monotonic() - record["monotonic_start"]
        previous = save_changes(root / "work", folder / "changes", previous)
        report = root / "work/report.md"
        if "report.md" in previous:
            shutil.copyfile(report, folder / "report.md")
            if result["status"] == "completed":
                completed_report = str((folder / "report.md").relative_to(root))
        write_json(folder / "result.json", result)
        record["turns"].append({"number": number, "status": result["status"], "session_id": result.get("session_id"),
                                "tool_events": result.get("tool_events", 0), "path": str(folder.relative_to(root))})
        record["last_completed_report"] = completed_report
        session = result.get("session_id")
        write_json(root / "run.json", {k: v for k, v in record.items() if k != "monotonic_start"})
        if result["status"] != "completed":
            record["stop"] = ("total_deadline" if result["status"] == "timeout" and result["timeout_limit"] == "total_seconds"
                              else "turn_timeout" if result["status"] == "timeout" else result["status"])
            record["reason"] = result.get("reason")
            break
    else:
        record["stop"] = "smoke_call_limit" if smoke else "agent_call_limit"


def index(root, record):
    lines = ["# 运行索引", "", f"类型：{record['kind']}；停止原因：`{record['stop']}`。", "",
             "模型自述未经裁决；每轮变更仅表示回合结束状态。", "", "[完整运行记录](run.json)", ""]
    report = record.get("last_completed_report")
    lines += [f"[最近完成回合的报告]({report})" if report else "未交付完成回合报告；不能据此解释为没有缺陷。", ""]
    for turn in record["turns"]:
        path = turn["path"]
        lines.append(f"- 回合 {turn['number']}：{turn['status']}；[记录]({path}/result.json)、"
                     f"[原始输出]({path}/stdout.jsonl)、[最终回答]({path}/final.txt)、[变更]({path}/changes/manifest.json)")
    executions = sorted((root/'executions').glob('*/result.json'))
    if executions:
        lines += ['', '隔离执行记录（不代表缺陷确认）：', '']
        for path in executions:
            execution = json.loads(path.read_text())
            lines.append(f"- {execution['turn']} / {execution['execution_id']}：{execution['status']}；[原始记录]({path.relative_to(root)})")
    (root / "index.md").write_text("\n".join(lines) + "\n")


def run(config, target, *, smoke=False, client_factory=Codex, environment_only=False):
    if not environment_only and not (config.allow_agent_materials and config.allow_experiments):
        raise ValueError("Model transmission and local experiments must both be authorized")
    start = time.monotonic()
    target_name = re.sub(r"[^A-Za-z0-9_-]+", "-", target.get("variant") or target["execution_backend"]).strip("-_")[:80] or "target"
    if smoke:
        config = config.model_copy(deep=True)
        config.budget.total_seconds = min(config.budget.total_seconds, 300)
        config.budget.agent_calls = min(config.budget.agent_calls, 2)
        target = {"execution_backend": target["execution_backend"], "variant": "synthetic", "execution_package": ".",
                  "analysis_roots": []}
    deadline = start + config.budget.total_seconds
    kind = "check-env" if environment_only else "smoke" if smoke else "audit"
    suffix = "baseline" if kind == "audit" else kind
    name = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S") + f"-{target_name}-{suffix}"
    attempt = 1
    while True:
        root = Path(config.runs_dir) / (name if attempt == 1 else f"{name}-{attempt}")
        try:
            root.mkdir(parents=True, mode=0o700)
            break
        except FileExistsError:
            attempt += 1
    for name in ("inputs", "source", "work", "turns"):
        (root / name).mkdir()
    record = {"kind": kind, "started_at": now(), "monotonic_start": start, "config": config.model_dump(),
              "turns": [], "stop": "preparing", "usage_semantics": "raw per event; no automatic sum",
              "last_completed_report": None, "archive_exclusions": sorted(WORK_EXCLUDED)}
    write_json(root / "run.json", {k: v for k, v in record.items() if k != "monotonic_start"})
    print(f"运行目录：{root}", file=sys.stderr, flush=True)
    def phase(name, message):
        record["phase"] = name
        record.setdefault("phase_times", {})[name] = {"at": now(), "elapsed_seconds": time.monotonic() - start}
        write_json(root / "run.json", {k: v for k, v in record.items() if k != "monotonic_start"})
        print(message, file=sys.stderr, flush=True)
    client = identity = None
    old_handler = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        phase("source_capture", "正在捕获源码；尚未调用模型。")
        (root / "inputs/task.md").write_bytes(TASK.read_bytes())
        write_json(root / "inputs/config.json", config.model_dump())
        write_json(root / "inputs/target.json", target)
        identity = implementation_identity(root)
        record["implementation"] = "inputs/implementation.json"
        write_json(root / record["implementation"], identity)
        source = synthetic_source(root / "source", target["execution_backend"], tcp=True) if smoke else capture_source(
            config.repo_path, root / "source", deadline)
        if not smoke and target.get("expected_module"):
            if not (root / "source/go.mod").is_file() or not any(
                    line.split() == ["module", target["expected_module"]] for line in (root / "source/go.mod").read_text().splitlines()):
                raise ValueError("Captured Go module differs from target.expected_module")
        write_json(root / "inputs/source.json", source)
        shutil.copytree(root / "source", root / "work", dirs_exist_ok=True)
        # A fresh empty Git boundary prevents configuration discovery in framework ancestors.
        git(root / "work", "-c", "init.templateDir=", "init", deadline=deadline)
        freeze(root / "source")
        client = client_factory(config, root, target, deadline)
        phase("environment_check", "正在检查本地权限和工具环境；尚未调用模型。")
        record["environment"] = client.prepare()
        identity["codex"] = executable_identity(client)
        write_json(root / record["implementation"], identity)
        if environment_only:
            phase("dependency_check", "正在检查离线依赖；尚未调用模型。")
            client.dependency_probe()
            key = config.credential_name
            record["credential_available"] = bool(os.environ.get(key)) if key else "not inspected; codex_login checked only on authorized model run"
            record["stop"] = "environment_checked"
        else:
            client.authenticate()
            record["stop"] = "running"
            phase("model_audit", "本地准备完成，开始调用模型。")
            loop(config, root, source, target, client, deadline, record, smoke=smoke)
            if smoke:
                record["smoke_observations_complete"] = smoke_observations(root, record)
    except (TimeoutError, subprocess.TimeoutExpired):
        record["stop"] = "total_deadline"
    except KeyboardInterrupt:
        record["stop"] = "cancelled"
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        record.update(stop="preflight_or_runtime_error", reason=str(exc))
    finally:
        if identity:
            record["implementation_check"] = finish_identity(root, identity)
        if client:
            client.close()
        signal.signal(signal.SIGTERM, old_handler)
        record["elapsed_seconds"] = time.monotonic() - start
        record["ended_at"] = now()
        record.pop("monotonic_start", None)
        scrub_work(root)
        write_json(root / "run.json", record)
        index(root, record)
        freeze(root)
    return {"ok": (record["stop"] == "environment_checked" if environment_only else
                   record["stop"] in {"agent_call_limit", "total_deadline", "smoke_call_limit"})
                  and (not smoke or record.get("smoke_observations_complete", False)),
            "run_dir": str(root), "stop": record["stop"], "reason": record.get("reason"),
            "tool_evidence": record.get('environment', {}).get('tool_evidence', {}),
            "model_compatibility": "not evaluated" if environment_only else "requires review of raw tool and session evidence"}


def check_environment(config, target):
    return run(config, target, environment_only=True)
