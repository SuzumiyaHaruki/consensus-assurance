import json
import re

import pytest
from pydantic import ValidationError

from consensus_assurance.cli import create_run_directory, resolve_run
from consensus_assurance.core.config import Config
from consensus_assurance.core.proposals import GraphDraft, ReadRequest
from regression_support import ReadingPlan


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
