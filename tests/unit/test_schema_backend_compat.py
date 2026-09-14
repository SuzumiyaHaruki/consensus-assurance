import copy
import json
import sys
from pathlib import Path

import pytest

from consensus_assurance.adapters.agents.backend import CodexAgent, MockAgent, strict_schema
from consensus_assurance.core.proposals import BuildReply, Discovery, Feedback, GraphPatch, ReplayPlan
from consensus_assurance.core.types import ExecutionStatus, Origin
from consensus_assurance.workflow.materials import ReadingPlan


@pytest.mark.parametrize('response_type', [ReadingPlan, Discovery, BuildReply, Feedback, GraphPatch, ReplayPlan])
def test_runtime_schemas_strip_default_annotations_without_mutating_models(response_type):
    original = response_type.model_json_schema()
    saved = copy.deepcopy(original)
    converted = strict_schema(original)

    def inspect(node):
        if isinstance(node, list):
            for item in node:
                inspect(item)
        elif isinstance(node, dict):
            assert 'default' not in node
            if node.get('type') == 'object':
                assert node['additionalProperties'] is False
                assert set(node['required']) == set(node['properties'])
            for key, value in node.items():
                if key in {'properties', '$defs', 'definitions'}:
                    for child in value.values():
                        inspect(child)
                elif key not in {'enum', 'const'}:
                    inspect(value)

    inspect(converted)
    assert original == saved
    if response_type is Discovery:
        assert 'default' in original['$defs']['ClaimDraft']['properties']['grounding']
        assert converted['$defs']['ClaimDraft']['properties']['grounding'] == {'$ref': '#/$defs/Grounding'}


def test_properties_named_default_and_validation_constraints_are_preserved():
    schema = {
        'type': 'object',
        'properties': {
            'default': {'type': 'integer', 'minimum': 1, 'default': 7},
            'choice': {'type': 'string', 'enum': ['default', 'other'], 'default': 'default'},
            'scope': {'$ref': '#/$defs/Scope', 'default': {'default': 7}},
        },
        '$defs': {'Scope': {'type': 'object', 'properties': {'default': {'type': 'integer', 'default': 7}}}},
    }
    converted = strict_schema(schema)
    assert converted['properties']['default'] == {'type': 'integer', 'minimum': 1}
    assert converted['properties']['choice']['enum'] == ['default', 'other']
    assert converted['properties']['scope'] == {'$ref': '#/$defs/Scope'}
    assert 'default' in converted['$defs']['Scope']['properties']
    assert 'default' in converted['required']


def test_backend_schema_rejection_keeps_the_actual_diagnostic(tmp_path):
    from consensus_assurance.adapters.runners.process import ProcessRunner

    message = "Invalid schema: context=('properties', 'grounding'), $ref cannot have keywords {'default'}."
    log = 'ERROR: ' + json.dumps({'type':'error','error':{'code':'invalid_json_schema','message':message},'status':400})
    class RejectedRunner(ProcessRunner):
        def run(self, command, cwd, action, snapshot_id, timeout, stdin):
            return super().run([sys.executable, '-c', 'import sys; print('+repr(log)+',file=sys.stderr);sys.exit(1)'], cwd, action, snapshot_id, timeout)
    agent = CodexAgent()
    agent.available = True
    agent.version = 'test-fixture'
    check, response = agent.analyze(RejectedRunner(tmp_path), 'Schema-only test', tmp_path, 'fixture', 5, Discovery)
    assert response is None and check.status == ExecutionStatus.ERROR
    assert 'invalid_json_schema' in check.reason and "{'default'}" in check.reason
    assert message in Path(check.stderr).read_text()


@pytest.mark.parametrize("failure_status", [ExecutionStatus.ERROR, ExecutionStatus.TIMEOUT])
def test_resume_retries_failed_discovery_and_reuses_completed_reading(tmp_path, prepared, failure_status):
    from consensus_assurance.consensus.inquiry import INQUIRY
    from consensus_assurance.core.config import Config
    from consensus_assurance.registry import assemble
    from consensus_assurance.workflow.engine import Engine

    repo, _, _, responses = prepared
    fixture = tmp_path / 'responses.json'
    fixture.write_text(json.dumps([responses[0], {}, responses[1]]))
    config = Config(protocol='toy', implementation='toy', agent_backend='mock', fixture=str(fixture), allow_experiments=False)
    class RejectFirstDiscovery(MockAgent):
        def analyze(self, runner, prompt, directory, snapshot_id, timeout, response_type):
            if self.cursor == 1:
                self.cursor += 1
                directory.mkdir(parents=True)
                check = runner.run([sys.executable, '-c', 'print("invalid_json_schema"); raise SystemExit(1)'], directory, 'agent', snapshot_id, timeout)
                check.origin = Origin.MOCK
                check.status = failure_status
                check.reason = 'Agent output schema rejected (invalid_json_schema)'
                return check, None
            return super().analyze(runner, prompt, directory, snapshot_id, timeout, response_type)
    impl, _, verifier, knowledge = assemble(config)
    root = tmp_path / 'resume-schema'
    stopped = Engine(config, root, impl, RejectFirstDiscovery(fixture), verifier, knowledge, INQUIRY).start(repo)
    assert stopped.completed_steps == ['capabilities', 'materials']
    assert stopped.usage['agent_calls'] == 2
    action = stopped.pending_action
    assert action.kind == 'agent:discover' and action.status == 'completed'
    failure_path = root / 'actions' / action.id / 'result.json'
    failure_bytes = failure_path.read_bytes()
    material_ids = [m.id for m in stopped.materials]
    class PlanOnly(Engine):
        def execute(self, probed=False, plan_only=False):
            return super().execute(probed=probed, plan_only=True)
    resumed = PlanOnly(config, root, impl, RejectFirstDiscovery(fixture), verifier, knowledge, INQUIRY).resume(action_timeout=600)
    assert resumed.stop_reason.startswith('Plan generated'), resumed.stop_reason
    assert resumed.usage['agent_calls'] == 3
    assert [m.id for m in resumed.materials] == material_ids
    assert len(resumed.reading_history) == 1
    assert resumed.claims
    assert failure_path.read_bytes() == failure_bytes
    assert any(a.id == action.id for a in resumed.action_history)
    assert len([c for c in resumed.checks if c.action == 'agent' and c.status == failure_status]) == 1

    assert resumed.config['budget']['action_timeout'] == 600
    assert resumed.config['budget']['total_seconds'] == config.budget.total_seconds
    assert resumed.elapsed_seconds >= stopped.elapsed_seconds
    assert json.loads((root / 'config.json').read_text())['budget']['action_timeout'] == config.budget.action_timeout
    history = [json.loads(p.read_text()) for p in (root / 'history').glob('*.json')]
    assert any(h['config']['budget']['action_timeout'] == config.budget.action_timeout for h in history)
    assert 'resume_action_timeout_changed' in (root / 'events.jsonl').read_text()


@pytest.mark.parametrize('timeout', [0, -1, float('inf'), float('nan')])
def test_resume_rejects_invalid_timeout_without_loading_or_running(tmp_path, timeout):
    from consensus_assurance.core.config import Config
    from consensus_assurance.workflow.engine import Engine

    engine = Engine(Config(), tmp_path, None, None, None, '', '')
    with pytest.raises(ValueError, match='finite positive'):
        engine.resume(action_timeout=timeout)
    assert not (tmp_path / 'state.json').exists()
