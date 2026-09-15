"""Replay an explicitly supplied recorded candidate and patches without a remote model."""
import argparse
import json
from pathlib import Path
from consensus_assurance.core.types import Analysis
from consensus_assurance.core.proposals import Discovery
from consensus_assurance.core.config import Config
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.workflow.budget import BudgetTracker
from consensus_assurance.workflow.graph import apply_discovery
from consensus_assurance.registry import assemble
from consensus_assurance.adapters.storage.files import write_json


def main():
    parser=argparse.ArgumentParser(description='离线播放已保存候选与显式修复；不调用远端模型、不运行目标')
    parser.add_argument('--run',required=True);parser.add_argument('--candidate',required=True)
    parser.add_argument('--patches',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();parent=Path(args.run).resolve();candidate=(parent/args.candidate).resolve();root=Path(args.output).resolve()
    if not candidate.is_relative_to(parent):raise ValueError('Candidate must be an existing artifact within the selected run')
    if root.exists() or root.is_relative_to(parent) or parent.is_relative_to(root):raise ValueError('Use a new disjoint output directory; historical inputs stay read-only')
    parent_state=Analysis.model_validate_json((parent/'state.json').read_text());original=json.loads(candidate.read_text());patches=json.loads(Path(args.patches).read_text())
    if not isinstance(patches,list):raise ValueError('Patches must be an explicit ordered list')
    root.mkdir(parents=True);fixture=root/'responses.json';write_json(fixture,[original]+patches)
    config=Config(implementation=parent_state.config['implementation'],agent_backend='mock',fixture=str(fixture),allow_agent_materials=False,allow_experiments=False)
    engine=Engine(config,root,*assemble(config),'')
    state=Analysis(mode='mock',analysis_mode='regression',framework_revision='round6',framework_stage='offline_migrated_child',
        config=config.model_dump(mode='json'),snapshot=parent_state.snapshot,materials=parent_state.materials,
        tools={'agent':'mock/recorded-response','verifier':'not_executed','implementation':'not_executed'})
    engine.state=state;engine.budget=BudgetTracker(config.budget,state)
    write_json(root/'parent.json',{'origin':'recorded_candidate_with_explicit_synthetic_patches','parent_run':str(parent),'parent_run_id':parent_state.id,'child_run_id':state.id,'parent_tools':parent_state.tools,'candidate':str(candidate),'patch_file':str(Path(args.patches).resolve()),'remote_model_calls':0,'target_executions':0})
    state.stop_reason='Offline replay started'
    try:
        proposal,check=engine.ask('discover',Discovery,{'materials':[m.model_dump(mode='json') for m in state.materials]},lambda p:apply_discovery(state.model_copy(deep=True),p))
        apply_discovery(state,proposal);state.stop_reason='Offline candidate accepted; no autonomous discovery quality or verification is claimed'
    except Exception as exc:
        state.stop_reason='Offline replay blocked: '+str(exc)
        raise
    finally:
        engine.checkpoint('offline_child_finished')
    print(state.stop_reason)


if __name__=='__main__':main()
