"""Fixed input capture, bounded same-session turns, and append-only handoffs."""
import json
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

from .codex import Codex, options


TASK = Path(__file__).with_name("task.md")
EXCLUDED = EXCLUDED_DIRS | {".execution", ".pytest_cache", ".mypy_cache"}
WORK_EXCLUDED = EXCLUDED | {".runtime"}


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


def synthetic_source(destination, backend):
    files = {"go.mod": "module baseline.local/smoke\n\ngo 1.20\n", "sample/value.go":
             "package sample\nfunc Add(a, b int) int { return a + b }\n"} if backend == "go_module" else {
             "Cargo.toml": '[package]\nname = "baseline-smoke"\nversion = "0.1.0"\nedition = "2021"\n',
             "src/lib.rs": "pub fn add(a: i32, b: i32) -> i32 { a + b }\n"}
    files["fixture.txt"] = "context-token-" + uuid4().hex + "\n"
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
        "permissions": "Source/logs read only; work writable; local tools only; no external or loopback network.",
        "tool_environment": "Offline Go/Cargo; writable temporary and cache paths in work/.runtime.",
        "remaining_total_seconds": remaining, "turn_timeout_seconds": timeout, "remaining_agent_calls": calls_left,
        "generated_at": now(), "estimated_turn_deadline_utc": (datetime.now(timezone.utc) + timedelta(seconds=timeout)).isoformat(),
        "deadline_basis": "Host monotonic clock; preparation, tool work and model waiting all consume total time."}, indent=2)


def smoke_prompt(second=False):
    if second:
        return ("Continue this same compatibility session. State the token you remembered from the previous "
                "conversation before reading note.txt, then read note.txt and fixture.txt to verify it. "
                "Modify your test, run it, inspect the output, and give a normal text handoff. "
                "Include that same token in the final handoff. "
                "Do not audit a consensus implementation. If externally blocked, begin RUN_BLOCKED:.")
    return ("This is an authorized synthetic coding-tool compatibility check, not a consensus audit. "
            "Read fixture.txt and the source. Remember the fixture token in this conversation and in note.txt. "
            "Write an ordinary test in the existing Go subpackage or Rust crate. Run an intentionally failing assertion, "
            "read its failure output, fix the test, and run it again. Preserve files and command outputs. "
            "Return a normal text handoff. If externally blocked, begin RUN_BLOCKED:.")


def smoke_observations(root, record):
    turns = record["turns"]
    commands = []
    for turn in turns:
        path = root / turn["path"] / "stdout.jsonl"
        if not path.is_file():
            continue
        for line in path.read_text(errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            item = event.get("item", {})
            if event.get("type") == "item.completed" and item.get("type") == "command_execution":
                commands.append((turn["number"], item.get("exit_code")))
    token = (root / "source/fixture.txt").read_text().strip()
    note, final = root / "work/note.txt", root / "turns/0002/final.txt"
    observed = {
        "two_completed_turns": len(turns) == 2 and all(t["status"] == "completed" for t in turns),
        "same_session": len(turns) == 2 and bool(turns[0]["session_id"]) and turns[0]["session_id"] == turns[1]["session_id"],
        "failure_then_another_command": any(code not in (0, None) and i < len(commands) - 1
                                           for i, (_, code) in enumerate(commands)),
        "successful_second_turn_command": any(turn == 2 and code == 0 for turn, code in commands),
        "file_read_and_written": note.is_file() and not note.is_symlink() and token in note.read_text(errors="replace"),
        "context_token_in_second_final": final.is_file() and token in final.read_text(errors="replace"),
    }
    write_json(root / "inputs/smoke-observations.json", {"observed": observed, "complete": all(observed.values()),
               "review": "Inspect actual tool arguments, test edits, failure reading and final text. These observations do not assess consensus defects."})
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
        prompt = smoke_prompt(number > 1) if smoke else (task if number == 1 else continuation)
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
        write_json(root / "run.json", {k: v for k, v in record.items() if k != "monotonic_start"})
        print(message, file=sys.stderr, flush=True)
    client = None
    old_handler = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        phase("source_capture", "正在捕获源码；尚未调用模型。")
        (root / "inputs/task.md").write_bytes(TASK.read_bytes())
        write_json(root / "inputs/config.json", config.model_dump())
        write_json(root / "inputs/target.json", target)
        source = synthetic_source(root / "source", target["execution_backend"]) if smoke else capture_source(
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
            "model_compatibility": "not evaluated" if environment_only else "requires review of raw tool and session evidence"}


def check_environment(config, target):
    return run(config, target, environment_only=True)
