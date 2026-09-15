import json
from pathlib import Path
from consensus_assurance.adapters.storage.files import digest


def fingerprint(inputs):
    return digest(json.dumps(inputs,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode())


def execution_fingerprint(model):
    if not model.search_inputs:return ''
    values=dict(model.search_inputs)
    values.update(behavior=(Path(model.path).parent/'Behavior.tla').read_text(),properties=Path(model.path).read_text(),configuration=Path(model.config_path).read_text())
    return fingerprint(values)
