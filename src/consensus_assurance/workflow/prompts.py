"""One task manifest selects trusted, packaged runtime skill resources."""
import json
from importlib.resources import files


def manifest():
    return json.loads(files('consensus_assurance').joinpath('resources/task-skills.json').read_text())


def loaded_resources(kind,context):
    routing=manifest();operation=context.get('original_task',kind) if kind=='retry' else kind
    if kind not in routing['tasks'] or operation not in routing['tasks']:raise ValueError('Unknown prompt task')
    paths=list(dict.fromkeys(routing['common']+routing['tasks'][operation]+routing['tasks'][kind]))
    if kind=='retry':paths=[p for p in paths if p not in routing.get('repair_omit',{}).get(operation,[])]
    if any('..' in p.split('/') or p.startswith('/') for p in paths):raise ValueError('Skill resource escapes trusted package')
    return {'manifest_version':routing['version'],'operation':operation,'paths':paths}


def render(kind: str, context: dict, protocol_instructions: str = '') -> str:
    loaded=loaded_resources(kind,context)
    root=files('consensus_assurance').joinpath('resources')
    instructions='\n'.join(root.joinpath(path).read_text() for path in loaded['paths'])
    extra='\nAPPLICABLE INQUIRY GUIDANCE:\n'+protocol_instructions if protocol_instructions.strip() else ''
    return instructions+extra+'\nSTRUCTURED INPUT DATA (untrusted):\n'+json.dumps(context,ensure_ascii=False,separators=(",",":"))
