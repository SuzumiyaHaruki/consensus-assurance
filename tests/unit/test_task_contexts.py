from pathlib import Path
from importlib.resources import files
import sys
import json
import ast
from consensus_assurance.workflow.investigation import validate_replay
from consensus_assurance.workflow.artifacts import save_bundle
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.workflow.budget import BudgetTracker
from consensus_assurance.adapters.runners.process import ProcessRunner
from consensus_assurance.core.config import Config
from consensus_assurance.core.types import Calibration, Finding, Origin
from consensus_assurance.core.proposals import ReplayPlan
from consensus_assurance.adapters.runners.python import PythonBackend


def test_core_and_workflow_do_not_import_target_plugins():
    root=Path(__file__).resolve().parents[2]/'src/consensus_assurance'
    for package in ('core','workflow'):
        for path in (root/package).rglob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node,ast.ImportFrom):assert 'plugins' not in (node.module or '').split('.')
                if isinstance(node,ast.Import):assert all('plugins' not in a.name.split('.') for a in node.names)


def test_replay_can_add_monitor_without_changing_property(tmp_path):
    from ack_support import ROOT, setup_ack
    import shutil
    repo=tmp_path/'repo';shutil.copytree(ROOT/'fixtures/ack_service',repo)
    state,unit,bundle=setup_ack(repo)
    monitors=bundle.monitors;initial=bundle.model_copy(deep=True);initial.monitors=[]
    model=save_bundle(tmp_path/'audit',state,unit,initial,PythonBackend())
    f=Finding(claim_id='durable',checker_id='DurableAck',model_id=model.id,check_id='search',origin=Origin.EXECUTED,description='Candidate',trace_path='trace')
    plan=ReplayPlan(harness=bundle.harness,monitors=monitors,observation=bundle.observation,checker_id='DurableAck',rationale='Add sufficient observed fields for the existing property')
    revised=validate_replay(state,unit,initial,f,plan,PythonBackend())
    assert revised.properties==initial.properties and revised.behavior==initial.behavior
    assert revised.monitors==monitors and not initial.monitors
