from consensus_assurance.adapters.agents.backend import CodexAgent, MockAgent
from consensus_assurance.adapters.runners.go_module import GoModuleBackend
from consensus_assurance.adapters.runners.python import PythonBackend
from consensus_assurance.adapters.runners.cargo import CargoBackend
from consensus_assurance.plugins.protocols.raft.pack import knowledge as raft_knowledge
from consensus_assurance.plugins.protocols.toy.pack import knowledge as toy_knowledge

EXECUTION_BACKENDS = {"go_module": GoModuleBackend, "cargo": CargoBackend, "python": PythonBackend, "none": lambda target, timeout: None}
KNOWLEDGE = {"raft": raft_knowledge, "toy": toy_knowledge, "none": lambda: ""}
AGENTS = {"codex": lambda cfg: CodexAgent(cfg.agent_reasoning_effort, cfg.agent_model, cfg.codex_provider, cfg.codex_profile), "mock": lambda cfg: MockAgent(cfg.fixture)}


def execution_backend(config):
    options = {'seed_cache_dir':config.cargo_seed_cache_dir} if config.execution_backend == 'cargo' else {}
    return EXECUTION_BACKENDS[config.execution_backend](config.target, config.budget.action_timeout, **options)


def assemble(config):
    try:
        return execution_backend(config), AGENTS[config.agent_backend](config), KNOWLEDGE[config.protocol]()
    except KeyError as exc:
        raise ValueError("Unknown configured backend: " + str(exc)) from exc
