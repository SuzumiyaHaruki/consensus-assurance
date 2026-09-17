import json
import re

import pytest
from pydantic import ValidationError

from consensus_assurance.cli import create_run_directory, resolve_run
from consensus_assurance.core.config import Config
from consensus_assurance.core.proposals import Discovery, ReadRequest
from consensus_assurance.adapters.agents.backend import strict_schema, wire_value
from consensus_assurance.workflow.materials import ReadingPlan


def test_readable_unique_run_directories(tmp_path):
    config = Config(runs_dir=str(tmp_path), implementation='hashicorp_raft', agent_backend='mock')
    first = create_run_directory(config, 'plan')
    second = create_run_directory(config, 'plan')
    assert first != second
    assert re.match(r'\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}-hashicorp_raft-mock-plan', first.name)
    assert resolve_run(first.name, tmp_path) == first
    old = tmp_path / ('a' * 32)
    old.mkdir()
    assert resolve_run(old.name, tmp_path) == old


def test_read_request_schema_matches_reader():
    request = {'file':'代码.go','start_line':1,'end_line':12,'reason':'Inspect the upstream producer'}
    schema = Discovery.model_json_schema()
    strict = strict_schema(schema)
    assert strict['$defs']['ReadRequest']['properties']['file']['type'] == 'string'
    encoded = wire_value({'reading_requests':[request]}, schema)
    decoded = wire_value(encoded, schema, decode=True)
    model = ReadRequest.model_validate(decoded['reading_requests'][0])
    assert ReadingPlan(requests=[model], rationale='Read dependency').requests[0] == model
    with pytest.raises(ValidationError):
        ReadRequest.model_validate({'files':['a.go'], 'symbols_or_topics':['producer']})


def test_semantic_validation_failure_is_saved_with_specific_reason(tmp_path, prepared):
    from consensus_assurance.registry import assemble
    from consensus_assurance.workflow.engine import Engine, Blocked

    repo, _, _, responses = prepared
    fixture = tmp_path / 'responses.json'
    fixture.write_text(json.dumps([responses[0], responses[0]]))
    config = Config(implementation='toy', agent_backend='mock', fixture=str(fixture))
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
