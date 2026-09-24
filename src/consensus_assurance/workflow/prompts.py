"""One task manifest selects trusted, packaged runtime skill resources."""
import json
from importlib.resources import files


def manifest():
    return json.loads(files('consensus_assurance').joinpath('resources/task-skills.json').read_text())


def loaded_resources(kind="native"):
    routing = manifest()
    if kind not in routing['tasks']:
        raise ValueError('Unknown method resource selection')
    paths = list(dict.fromkeys(routing['common'] + routing['tasks'][kind]))
    if any('..' in p.split('/') or p.startswith('/') for p in paths):
        raise ValueError('Method resource escapes trusted package')
    return {'manifest_version':routing['version'], 'operation':kind, 'paths':paths}
