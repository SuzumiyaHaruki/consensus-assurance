"""Shared YAML input and neutral target selection for repository entry points."""
from pathlib import Path

import yaml

from consensus_assurance.core.config import TargetConfig


def read_yaml(path):
    class UniqueLoader(yaml.SafeLoader):
        pass

    def mapping(loader, node):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node)
            if key in result:
                raise ValueError(f"Duplicate configuration key: {key}")
            result[key] = loader.construct_object(value_node)
        return result

    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    value = yaml.load(Path(path).read_text(), Loader=UniqueLoader)
    if not isinstance(value, dict):
        raise ValueError("Configuration must be a mapping")
    return value


def relative_path(value, directory, *, resolve=True):
    path = Path(directory) / Path(value).expanduser()
    return str(path.resolve() if resolve else path.absolute())


def read_target(path):
    raw = read_yaml(path)
    backend = raw.get('execution_backend')
    if backend not in {'go_module', 'cargo', 'maven', 'python', 'none'}:
        raise ValueError('Unknown target execution_backend')
    target = TargetConfig.model_validate(raw.get('target', {}))
    return {'execution_backend': backend, 'target': target.model_dump()}
