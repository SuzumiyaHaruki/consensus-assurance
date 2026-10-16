"""Synthetic repositories and Codex events shared by baseline tests."""
import json
import subprocess
from pathlib import Path
import yaml
from baseline.__main__ import Config

SESSION = "00000000-0000-4000-8000-000000000001"
PROJECT = Path(__file__).resolve().parents[2]


def make_repo(path, backend="go_module"):
    path.mkdir()
    files = {"go.mod": "module baseline.local/fixture\n\ngo 1.20\n", "sample/value.go":
             "package sample\nfunc Add(a, b int) int { return a + b }\n"} if backend == "go_module" else {
             "Cargo.toml": '[package]\nname = "baseline-smoke"\nversion = "0.1.0"\nedition = "2021"\n',
             "src/lib.rs": "pub fn add(a: i32, b: i32) -> i32 { a + b }\n"}
    for name, text in {**files, 'fixture.txt': 'synthetic source control'}.items():
        file = path/name; file.parent.mkdir(parents=True, exist_ok=True); file.write_text(text)
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
