import json
import os
from pathlib import Path
import pytest
from consensus_assurance.cli import main
from regression_support import fixture_config as Config
from consensus_assurance.core.types import Assessment
from consensus_assurance.registry import assemble
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.adapters.storage.snapshot import capture






def test_missing_target_cli_has_no_download(tmp_path, capsys):
    assert main(["run", "--repo", str(tmp_path / "absent"), "--runs-dir", str(tmp_path / "runs")]) == 2
    assert "does not exist" in capsys.readouterr().err
