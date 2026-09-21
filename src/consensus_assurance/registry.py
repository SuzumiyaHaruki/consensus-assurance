from consensus_assurance.adapters.agents.backend import CodexAgent, MockAgent
from consensus_assurance.adapters.verifiers.tlc import TLCVerifier
from consensus_assurance.adapters.runners.go_module import GoModuleBackend
from consensus_assurance.adapters.runners.python import PythonBackend
from consensus_assurance.plugins.protocols.raft.pack import knowledge as raft_knowledge
from consensus_assurance.plugins.protocols.toy.pack import knowledge as toy_knowledge

EXECUTION_BACKENDS = {"go_module": GoModuleBackend, "python": PythonBackend, "none": lambda target, timeout: None}
KNOWLEDGE = {"raft": raft_knowledge, "toy": toy_knowledge, "none": lambda: ""}
AGENTS = {"codex": lambda cfg: CodexAgent(cfg.agent_reasoning_effort), "mock": lambda cfg: MockAgent(cfg.fixture)}
VERIFIERS = {"tlc": lambda cfg: TLCVerifier(cfg.tlc_jar)}


def assemble(config):
    try:
        return EXECUTION_BACKENDS[config.execution_backend](config.target, config.budget.action_timeout), AGENTS[config.agent_backend](config), VERIFIERS[config.verifier_backend](config), KNOWLEDGE[config.protocol]()
    except KeyError as exc:
        raise ValueError("Unknown configured backend: " + str(exc)) from exc
