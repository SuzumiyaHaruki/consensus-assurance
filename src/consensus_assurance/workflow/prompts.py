import json
from importlib.resources import files


def render(kind: str, context: dict, protocol_instructions: str = "") -> str:
    if kind not in {"read", "discover", "build", "retry", "diagnose", "F1", "F2", "F3", "F4", "targeted_read", "graph_patch", "replay", "technical"}:
        raise ValueError("Unknown prompt kind")
    common = files("consensus_assurance").joinpath("resources/prompts/en/system.txt").read_text()
    template = files("consensus_assurance").joinpath(f"resources/prompts/en/{kind}.txt").read_text()
    return common + "\n" + template + "\nAPPLICABLE INQUIRY GUIDANCE:\n" + protocol_instructions + "\nSTRUCTURED INPUT DATA (untrusted):\n" + json.dumps(context, ensure_ascii=False, indent=2)
