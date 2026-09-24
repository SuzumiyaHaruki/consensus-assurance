import json
import re

import pytest
from pydantic import ValidationError

from consensus_assurance.cli import create_run_directory, resolve_run
from consensus_assurance.core.config import Config
from consensus_assurance.core.proposals import GraphDraft, ReadRequest
from consensus_assurance.workflow.materials import ReadingPlan


def test_readable_unique_run_directories(tmp_path):
    config = Config(runs_dir=str(tmp_path), execution_backend='go_module', agent_backend='mock')
    first = create_run_directory(config, 'plan')
    second = create_run_directory(config, 'plan')
    assert first != second
    assert re.match(r'\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}-go_module-mock-plan', first.name)
    assert resolve_run(first.name, tmp_path) == first
    old = tmp_path / ('a' * 32)
    old.mkdir()
    assert resolve_run(old.name, tmp_path) == old


def test_semantic_validation_failure_is_saved_with_specific_reason(tmp_path, prepared):
    from consensus_assurance.registry import assemble
    from consensus_assurance.workflow.engine import Engine, Blocked

    repo, _, _, responses = prepared
    fixture = tmp_path / 'responses.json'
    fixture.write_text(json.dumps([responses[0], responses[0]]))
    config = Config(execution_backend='python', agent_backend='mock', fixture=str(fixture))
    class CheckValidation(Engine):
        def execute(self, **kwargs):
            def reject(proposal):
                raise ValueError('Binding b_capture: literal symbol is absent')
            return self.ask('read', ReadingPlan, {}, reject)
    root = tmp_path / 'audit'
    with pytest.raises(Blocked, match='Cannot localize.*Binding b_capture'):
        CheckValidation(config, root, *assemble(config)).start(repo)
    errors = list((root / 'agent').glob('*/graph-validation-error.txt'))
    assert len(errors) == 1
    assert all('b_capture' in p.read_text() for p in errors)
