"""Run the finite, manually selected codec comparison through the existing isolated runner."""
import argparse
import shutil
import tempfile
from pathlib import Path
from consensus_assurance.core.config import TargetConfig
from consensus_assurance.adapters.storage.snapshot import capture
from consensus_assurance.adapters.storage.files import write_json
from consensus_assurance.adapters.runners.go_module import GoModuleBackend
from consensus_assurance.adapters.runners.process import ProcessRunner, output
from consensus_assurance.adapters.runners.experiment import run_experiment, extract_events


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--repo",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    root=args.output.resolve();repo=args.repo.resolve()
    if root.is_relative_to(repo) or repo.is_relative_to(root):raise ValueError("Output and target must be disjoint")
    root.mkdir(parents=True,exist_ok=False)
    harness=Path(__file__).with_name("paxos_codec_test.go")
    shutil.copy2(harness,root/harness.name)
    target=TargetConfig(expected_module="github.com/imdea-software/swiftpaxos",execution_package="./paxos",harness_path="paxos/assurance_generated_test.go")
    backend=GoModuleBackend(target);runner=ProcessRunner(root)
    version=runner.run(backend.version_command(),root,"implementation_probe","environment",10)
    with tempfile.TemporaryDirectory(prefix="paxos-codec-",dir=root) as temporary:
        workspace=Path(temporary)/"target"
        snapshot=capture(repo,workspace,expected_module=target.expected_module)
        write_json(root/"snapshot.json",snapshot)
        destination=workspace/backend.harness_filename
        if destination.exists():raise FileExistsError(destination)
        shutil.copy2(harness,destination)
        check=run_experiment(runner,backend.experiment_command(),workspace,snapshot.id,120,"bwrap","direct_check",adapter=backend)
        check.tool_version=output(version).strip()
        events=extract_events(check)
        write_json(root/"check.json",check)
        comparisons=[]
        for sent,decoded in zip(events[::2],events[1::2]):
            correlated=sent.get("event")=="sent" and decoded.get("event")=="decoded" and all(sent.get(k)==decoded.get(k) for k in ("operation","participant","context"))
            comparisons.append({"variant":sent.get("metadata",{}).get("variant"),"correlated":correlated,
                "fields":{key:{"sent":sent.get("state",{}).get(key),"decoded":decoded.get("state",{}).get(key)} for key in ("ballot","next_code")}})
        write_json(root/"directed-followup.json",{"analysis_mode":"directed","origin":"executed","source_commit":snapshot.commit,
            "manual_inputs":["Selected codec question, Go input values, in-memory peer stream and field comparison"],
            "check_id":check.id,"events":events,"comparisons":comparisons,
            "limitations":["Local send/decode paths only; network delivery and consensus history were not executed", "Temporary source copy is not retained; snapshot, Go input and raw output are retained"]})
    print(root/"directed-followup.json")
    return 0 if check.outcome=="tests_passed" else 1


if __name__=="__main__":raise SystemExit(main())
