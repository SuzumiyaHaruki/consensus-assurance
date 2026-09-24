import argparse
import re
from datetime import datetime
import fcntl
import json
import os
import sys
from pathlib import Path
import yaml
from consensus_assurance.core.config import Config, locate_repo
from consensus_assurance.registry import assemble
from consensus_assurance.workflow.engine import Engine, FRAMEWORK_REVISION
from consensus_assurance.adapters.storage.files import Store, write_json
from consensus_assurance.adapters.runners.process import ProcessRunner
from consensus_assurance.reporting.chinese import render_report


def load_config(path=None, overrides=None):
    data = yaml.safe_load(Path(path).read_text()) or {} if path else {}
    if not isinstance(data, dict):
        raise ValueError("Configuration must be an object")
    for name in ("repo_path", "runs_dir", "tlc_jar", "fixture"):
        if data.get(name):
            p = Path(data[name]).expanduser()
            if not p.is_absolute():
                p = (Path(path).resolve().parent if path else Path.cwd()) / p
            data[name] = str(p.resolve())
    data.update({k: v for k, v in (overrides or {}).items() if v is not None})
    if not data.get("tlc_jar") and os.environ.get("TLC_JAR"):
        data["tlc_jar"] = os.environ["TLC_JAR"]
    return Config.model_validate(data)


def resolve_run(value, runs_dir):
    candidate = Path(value).expanduser()
    if candidate.is_dir():
        return candidate.resolve()
    candidate = Path(runs_dir) / value
    if not candidate.is_dir():
        raise FileNotFoundError("Run directory not found: " + str(candidate))
    return candidate.resolve()


def create_run_directory(config, command):
    parent = Path(config.runs_dir).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    label = re.sub(r"[^A-Za-z0-9_-]+", "-", config.target.variant or config.execution_backend).strip("-")[:64] or "implementation"
    mode = "mock" if config.agent_backend == "mock" else "real"
    name = f"{datetime.now().astimezone():%Y-%m-%d_%H-%M-%S}-{label}-{mode}-{command}"
    for number in range(10000):
        root = parent / (name if number == 0 else f"{name}-{number + 1}")
        try:
            root.mkdir(exist_ok=False)
            return root
        except FileExistsError:
            continue
    raise FileExistsError("Too many run directories with the same timestamp")


def main(argv=None):
    parser = argparse.ArgumentParser(description="共识义务驱动的局部实现审计；默认自主发现目标")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "run", "inspect", "plan", "estimate"):
        p = sub.add_parser(name)
        p.add_argument("--config"); p.add_argument("--repo")
        p.add_argument("--agent-backend", choices=["codex", "mock"])
        p.add_argument("--tlc-jar"); p.add_argument("--runs-dir")
        p.add_argument("--question", help="可选定向问题；默认不指定目标")
    for name in ("resume", "report"):
        p = sub.add_parser(name); p.add_argument("--run", required=True)
        p.add_argument("--runs-dir", default="runs")
        if name == "resume":
            p.add_argument("--repair-attempts",type=int,help="显式调整任务总修复上限；不重置已用次数或单问题失败记录")
            p.add_argument("--action-timeout", type=float, help="调整后续单动作超时（秒）；保留总预算和已用次数")
            p.add_argument("--native-turn-timeout", type=float, help="调整后续单次原生 Codex 调查最长时长（秒）；不改变正式执行超时或总预算")
    args = parser.parse_args(argv)
    try:
        if args.command in {"resume", "report"}:
            root = resolve_run(args.run, args.runs_dir)
            raw=json.loads((root/"state.json").read_text())
            if raw.get("framework_revision")!=FRAMEWORK_REVISION:
                if args.command=="report" and (root/"report.md").is_file():
                    print((root/"report.md").read_text());return 0
                print("历史运行只读；使用原始报告或离线导入，不能恢复到新语义。");return 2
            state=Store(root).load()
            if args.command == "report":
                print(render_report(state, root)); return 0
            config = Config.model_validate(state.config)
        else:
            config = load_config(args.config, {"agent_backend": args.agent_backend, "tlc_jar": args.tlc_jar,
                "runs_dir": args.runs_dir, "directed_question": args.question})
            if args.command == "estimate":
                repo = locate_repo(args.repo, config.repo_path)
                b = config.budget
                minimum = 1 if config.agent_backend=="codex" else 2 + b.audit_units + min(b.semantic_reviews, b.audit_units)
                print(json.dumps({"仓库":str(repo),"材料发送":False,"执行目标代码":False,
                    "agent调用上限":b.agent_calls,"粗略计划下限":minimum,
                    "预算说明":"原生路径按 CLI turn、总时长和正式执行计数；源码浏览发生在原生会话内，旧材料字符和 packet 额度仅用于离线旧阶段。不是账单。" if config.agent_backend=="codex" else "旧阶段离线估算；不是账单。",
                    "计划可能受限":minimum>b.agent_calls,"预算":b.model_dump(mode="json")},ensure_ascii=False,indent=2))
                return 0
            root = create_run_directory(config, args.command)
        implementation, agent, verifier, knowledge = assemble(config)
        if args.command == "doctor":
            runner = ProcessRunner(root)
            results = {"agent": agent.probe(runner), "verifier": verifier.probe(runner)}
            for result in results.values():
                result["checks"] = [c.model_dump(mode="json") for c in result["checks"]]
            results["implementation"] = runner.run(implementation.version_command(), root, "implementation_probe", "environment", 10).model_dump(mode="json") if implementation else {"available":False,"reason":"No execution backend configured"}
            write_json(root / "doctor.json", results)
            print(f"环境诊断已保存：{root / 'doctor.json'}")
            return 0 if all(results[k]["available"] for k in ("agent", "verifier")) else 2
        if args.command == "inspect":
            from consensus_assurance.adapters.storage.snapshot import capture
            repo = locate_repo(args.repo, config.repo_path)
            snapshot = capture(repo, analysis_roots=config.target.analysis_roots, expected_module=config.target.expected_module)
            write_json(root / "snapshot.json", snapshot)
            print(f"目标快照已保存：{root / 'snapshot.json'}"); return 0
        engine = Engine(config, root, implementation, agent, verifier, knowledge)
        with (root / ".run.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.command == "resume":
                state = engine.resume(action_timeout=args.action_timeout,repair_attempts=args.repair_attempts,
                    native_turn_timeout=args.native_turn_timeout)
                if state.framework_revision!=FRAMEWORK_REVISION:
                    print(state.stop_reason);return 2
            else:
                repo = locate_repo(args.repo, config.repo_path)
                state = engine.start(repo, plan_only=args.command == "plan")
            report = render_report(state, root)
        print(f"运行模式：{state.mode}；报告：{report}")
        print(f"停止原因：{state.stop_reason}")
        return 0 if state.stop_reason.startswith(("No pending", "Plan generated",
            "No further investigation selected", "Snapshot prepared")) else 2
    except (ValueError, FileNotFoundError, BlockingIOError, OSError) as exc:
        print(f"无法继续：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
