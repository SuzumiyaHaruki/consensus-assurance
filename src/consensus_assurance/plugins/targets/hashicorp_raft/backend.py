from pathlib import Path
from consensus_assurance.adapters.runners.go_module import GoModuleBackend


class HashicorpRaftBackend(GoModuleBackend):
    name = 'hashicorp_raft'
    version = '1'
    harness_instructions = GoModuleBackend.harness_instructions + (
        ' Read native-support/assurance_support_test.go. NewAssuranceCluster initializes actual in-memory Raft nodes '
        'through BootstrapCluster/NewRaft and caller-supplied configs/FSMs. Gate actual request_delivery or '
        'reply_delivery by returning a release channel; nil delivers immediately. Message records describe '
        'actual RPCs, not an oracle. Connect/Disconnect actual transports for link faults. No deterministic '
        'global schedule, crash-durable storage, restart helper or application consequence is provided. '
        'The in-memory transport has no fast heartbeat callback. Observe public Future/FSM endpoints separately.')

    def support_files(self):
        return {str(Path(self.package)/'assurance_support_test.go'):
            Path(__file__).with_name('assurance_support_test.go').read_text()}
