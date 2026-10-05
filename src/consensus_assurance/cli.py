import argparse
import re
from datetime import datetime
import fcntl
import json
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
    for name in ("repo_path", "runs_dir", "fixture"):
        if data.get(name):
            p = Path(data[name]).expanduser()
            if not p.is_absolute():
                p = (Path(path).resolve().parent if path else Path.cwd()) / p
            data[name] = str(p.resolve())
    provider=data.get('codex_provider')
    if isinstance(provider,dict) and provider.get('model_catalog_path'):
        p=Path(provider['model_catalog_path']).expanduser()
        provider['model_catalog_path']=str((p if p.is_absolute() else (Path(path).resolve().parent if path else Path.cwd())/p).resolve())
    data.update({k: v for k, v in (overrides or {}).items() if v is not None})
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
        p.add_argument("--runs-dir")
        p.add_argument("--question", help="可选定向问题；默认不指定目标")
    for name in ("resume", "report"):
        p = sub.add_parser(name); p.add_argument("--run", required=True)
        p.add_argument("--runs-dir", default="runs")
        if name == "report":p.add_argument("--export-views",action="store_true",help="按需导出地图、材料、图、进度和计划的根目录派生副本")
        if name == "resume":
            p.add_argument("--repair-attempts",type=int,help="显式调整任务总修复上限；不重置已用次数或单问题失败记录")
            p.add_argument("--action-timeout", type=float, help="调整后续单动作超时（秒）；保留总预算和已用次数")
            p.add_argument("--agent-turn-timeout", type=float, help="调整后续单次Codex 调查最长时长（秒）；不改变正式执行超时或总预算")
    p = sub.add_parser('validate', help='只读检查当前草稿；不受理、不执行、不获取运行锁')
    p.add_argument('--run', required=True)
    p.add_argument('--submission', required=True, help='相对当前 draft 的产品路径')
    args = parser.parse_args(argv)
    try:
        if args.command == 'validate':
            from consensus_assurance.core.types import Analysis
            from consensus_assurance.registry import EXECUTION_BACKENDS
            from consensus_assurance.workflow.audit import validate_submission, draft_bytes
            root = Path(args.run).expanduser().resolve()
            raw = json.loads(draft_bytes(root, 'state.json'))
            if raw.get('framework_revision') != FRAMEWORK_REVISION:
                raise ValueError('Historical runs are read-only; validate requires the current framework revision')
            state = Analysis.model_validate(raw)
            config = Config.model_validate(state.config)
            implementation = EXECUTION_BACKENDS[config.execution_backend](config.target, config.budget.action_timeout)
            result = validate_submission(state, root, args.submission, implementation)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result['valid'] else 2
        if args.command in {"resume", "report"}:
            root = resolve_run(args.run, args.runs_dir)
            raw=json.loads((root/"state.json").read_text())
            if raw.get("framework_revision")!=FRAMEWORK_REVISION:
                if args.command=="report" and (root/"report.md").is_file():
                    print((root/"report.md").read_text());return 0
                print("历史运行只读；使用原始报告或离线导入，不能恢复到新语义。");return 2
            state=Store(root).load()
            if args.command == "report":
                if args.export_views:
                    from consensus_assurance.reporting.chinese import Archive
                    from consensus_assurance.workflow.audit_spec import audit_progress
                    archive=Archive(state,root)
                    spec_path=archive.path(f'audit-spec/v{state.audit_spec_version}.json')
                    spec=archive.read(spec_path)
                    if spec and spec.get('version')!=state.audit_spec_version:raise ValueError('Saved map version differs from state')
                    write_json(root/'materials.json',[m.model_dump(mode='json') for m in state.materials])
                    write_json(root/'graph.json',{'version':state.graph_version,
                        **{name:[x.model_dump(mode='json') for x in getattr(state,name)] for name in ('claims','bindings','relations')}})
                    if spec:write_json(root/'audit-spec.json',spec)
                    write_json(root/'audit-progress.json',audit_progress(state.model_copy(update={'audit_spec_path':str(spec_path) if spec_path else None})))
                    write_json(root/'plan.json',{'units':[u.model_dump(mode='json') for u in state.units],'selections':state.selections})
                print(render_report(state, root)); return 0
            config = Config.model_validate(state.config)
        else:
            config = load_config(args.config, {"agent_backend": args.agent_backend,
                "runs_dir": args.runs_dir, "directed_question": args.question})
            if args.command == "estimate":
                repo = locate_repo(args.repo, config.repo_path)
                b = config.budget
                print(json.dumps({"仓库":str(repo),"材料发送":False,"执行目标代码":False,
                    "后端":{"Agent":config.agent_backend,"目标执行":config.execution_backend},
                    "授权":{"发送材料":config.allow_agent_materials,"执行目标":config.allow_experiments},
                    "预算":b.model_dump(mode="json"),
                    "零额度":[k for k in ('agent_calls','experiments','audit_units','semantic_reviews','revisions') if getattr(b,k)==0],
                    "计数口径":{"agent_calls":"CLI turn；会话内工具不另算调用，总时间不重复叠加内部工具耗时",
                        "experiments":"控制器探索、失败重试与正式检查共用；不含 Agent 回合内本地试跑，不等于独立问题数",
                        "audit_units":"新义务入场；new_obligation 不保证能走完整条执行／复核链",
                        "semantic_reviews":"对应性及语义复核；零额度时新执行不能以 PASS 代替复核",
                        "revisions":"修订额度独立计数；不按执行次数推算剩余"},
                    "限制说明":"上限不自动扩容或兑换；单项额度耗尽不自动终止有预算的源码调查。缺失 token 用量保持未知，不预测发现数。"},ensure_ascii=False,indent=2))
                return 0
            root = create_run_directory(config, args.command)
        implementation, agent, knowledge = assemble(config)
        if args.command == "doctor":
            runner = ProcessRunner(root)
            results = {"agent": agent.probe(runner)}
            for result in results.values():
                result["checks"] = [c.model_dump(mode="json") for c in result["checks"]]
            results["implementation"] = runner.run(implementation.version_command(), root, "implementation_probe", "environment", 10).model_dump(mode="json") if implementation else {"available":False,"reason":"No execution backend configured"}
            write_json(root / "doctor.json", results)
            print(f"环境诊断已保存：{root / 'doctor.json'}")
            return 0 if all(results[k]["available"] for k in results if k!='implementation') else 2
        if args.command == "inspect":
            from consensus_assurance.adapters.storage.snapshot import capture
            repo = locate_repo(args.repo, config.repo_path)
            snapshot = capture(repo, analysis_roots=config.target.analysis_roots, expected_module=config.target.expected_module)
            write_json(root / "snapshot.json", snapshot)
            print(f"目标快照已保存：{root / 'snapshot.json'}"); return 0
        engine = Engine(config, root, implementation, agent, knowledge)
        with (root / ".run.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                if args.command == "resume":
                    state = engine.resume(action_timeout=args.action_timeout,repair_attempts=args.repair_attempts,
                        agent_turn_timeout=args.agent_turn_timeout)
                    if state.framework_revision!=FRAMEWORK_REVISION:
                        print(state.stop_reason);return 2
                else:
                    repo = locate_repo(args.repo, config.repo_path)
                    state = engine.start(repo, plan_only=args.command == "plan")
            except KeyboardInterrupt:
                if engine.state is None:raise
                state = engine.state
            report = render_report(state, root)
        print(f"运行模式：{state.mode}；报告：{report}")
        print(f"停止原因：{state.stop_reason}")
        if state.run_stop and state.run_stop['reason']=='user_stop':return 130
        return 0 if state.stop_reason.startswith(("Scoped stop (", "Snapshot prepared")) else 2
    except (ValueError, FileNotFoundError, BlockingIOError, OSError) as exc:
        print(f"无法继续：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
