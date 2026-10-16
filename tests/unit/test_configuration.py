"""Public profiles share target definitions without inheriting research settings."""
from pathlib import Path

import pytest

from baseline.__main__ import load_config as baseline_config, load_target
from consensus_assurance.cli import load_config
from consensus_assurance.adapters.storage.configuration import read_target

ROOT = Path(__file__).resolve().parents[2]


def test_public_profiles_and_all_targets_load_without_local_inputs():
    targets = sorted((ROOT / 'configs/targets').glob('*.yaml'))
    assert len(targets) == 7
    for path in (ROOT / 'configs/ca').glob('*.yaml'):
        for target in targets:
            config = load_config(path, {'target_config': str(target)})
            assert config.execution_backend == read_target(target)['execution_backend']
            assert not config.allow_agent_materials and not config.allow_experiments
            assert config.repo_path is None
    for path in (ROOT / 'configs/baseline').glob('*.yaml'):
        config = baseline_config(path)
        assert not config.allow_agent_materials and not config.allow_experiments
        for target in targets:
            config.target_config = str(target)
            assert load_target(config)['variant'] == read_target(target)['target']['variant']


def test_target_reference_paths_overrides_and_effective_config(tmp_path):
    targets = tmp_path / 'targets'; targets.mkdir()
    target = targets / 'sample.yaml'
    target.write_text('execution_backend: cargo\ntarget:\n  variant: sample\n  execution_package: crate\nagent_model: DO_NOT_INHERIT\nallow_experiments: true\n')
    profiles = tmp_path / 'profiles'; profiles.mkdir()
    path = profiles / 'run.yaml'
    path.write_text('target_config: ../targets/sample.yaml\ntarget:\n  harness_path: crate/tests/check.rs\nagent_model: chosen\nallow_experiments: false\nruns_dir: ../output\n')
    config = load_config(path, {'runs_dir': str(tmp_path / 'override')})
    assert config.target.execution_package == 'crate'
    assert config.target.harness_path == 'crate/tests/check.rs'
    assert config.agent_model == 'chosen' and not config.allow_experiments
    assert config.runs_dir == str(tmp_path / 'override')
    saved = config.model_dump()
    assert 'target_config' not in saved
    target.unlink()
    assert type(config).model_validate(saved) == config


@pytest.mark.parametrize('loader', [load_config, baseline_config])
def test_both_entry_points_reject_duplicate_yaml_keys(tmp_path, loader):
    path = tmp_path / 'duplicate.yaml'
    path.write_text('agent_model: first\nagent_model: second\n')
    with pytest.raises(ValueError, match='Duplicate configuration key'):
        loader(path)
