import json
from importlib.resources import files


def render(kind: str, context: dict, protocol_instructions: str = "") -> str:
    if kind not in {"read", "discover", "build", "retry", "diagnose", "F1", "F2", "F3", "F4", "targeted_read", "graph_patch", "replay", "technical", "explore", "semantic_review", "consequence"}:
        raise ValueError("Unknown prompt kind")
    common = files("consensus_assurance").joinpath("resources/prompts/en/system.txt").read_text()
    methods = []
    operation = context.get("original_task", kind) if kind == "retry" else kind
    if operation not in {"read", "discover", "build", "retry", "diagnose", "F1", "F2", "F3", "F4", "targeted_read", "graph_patch", "replay", "technical", "explore", "semantic_review", "consequence"}:
        raise ValueError("Unknown original prompt task")
    if operation in {"discover", "graph_patch", "targeted_read", "read", "explore"}:
        methods.append("discovery_method")
    if operation in {"build", "F1", "F3", "technical"}:
        methods += ["build", "modeling_method", "experiment_method"]
    elif operation in {"replay", "F4", "diagnose"}:
        methods.append("experiment_method")
    if operation == "semantic_review":
        methods.append("review_method")
    templates = list(dict.fromkeys(methods + [operation, kind]))
    template = "\n".join(files("consensus_assurance").joinpath(f"resources/prompts/en/{name}.txt").read_text() for name in templates)
    return common + "\n" + template + "\nAPPLICABLE INQUIRY GUIDANCE:\n" + protocol_instructions + "\nSTRUCTURED INPUT DATA (untrusted):\n" + json.dumps(context, ensure_ascii=False, indent=2)
