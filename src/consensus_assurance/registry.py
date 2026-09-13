from consensus_assurance.adapters.agents.backend import CodexAgent, MockAgent
from consensus_assurance.adapters.verifiers.tlc import TLCVerifier
from consensus_assurance.plugins.implementations.hashicorp_raft.adapter import HashicorpRaft
from consensus_assurance.plugins.implementations.toy.adapter import ToyImplementation
from consensus_assurance.plugins.protocols.raft.pack import knowledge as raft_knowledge
from consensus_assurance.plugins.protocols.toy.pack import knowledge as toy_knowledge

IMPLEMENTATIONS = {"hashicorp_raft": HashicorpRaft, "toy": ToyImplementation}
KNOWLEDGE = {"raft": raft_knowledge, "toy": toy_knowledge, "none": lambda: ""}
AGENTS = {"codex": lambda cfg: CodexAgent(), "mock": lambda cfg: MockAgent(cfg.fixture)}
VERIFIERS = {"tlc": lambda cfg: TLCVerifier(cfg.tlc_jar)}


def assemble(config):
    try:
        return IMPLEMENTATIONS[config.implementation](), AGENTS[config.agent_backend](config), VERIFIERS[config.verifier_backend](config), KNOWLEDGE[config.protocol]()
    except KeyError as exc:
        raise ValueError("Unknown configured backend: " + str(exc)) from exc
