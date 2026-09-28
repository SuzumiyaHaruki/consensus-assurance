from pathlib import Path
from consensus_assurance.adapters.runners.go_module import GoModuleBackend


class HashicorpRaftBackend(GoModuleBackend):
    name = 'hashicorp_raft'
    version = '2'
    harness_instructions = GoModuleBackend.harness_instructions + (
        ' Read target-support/assurance_support_test.go. NewAssuranceCluster initializes actual in-memory Raft nodes '
        'through BootstrapCluster/NewRaft and caller-supplied configs/FSMs. NewAssuranceClusterWithSuffrage accepts '
        'an explicit role for each initial member, validated by the target bootstrap API; alternatively use real public membership changes. '
        'Inspect GetConfiguration and match actual member IDs and suffrage. Gate actual request_delivery or '
        'reply_delivery by returning a release channel; nil delivers immediately. Message records describe '
        'actual RPCs, not an oracle. Delivery events mean gate arrival; request_handoff means transfer to the real worker inbox, '
        'reply_handoff means transfer to the transport response channel, neither proves later consumption. '
        'Message IDs correlate request and reply, not a high-level operation; correlate public operation intervals separately. '
        'Connect/Disconnect actual transports for link faults. No deterministic '
        'global schedule, crash-durable storage, restart helper or application consequence is provided. '
        'The in-memory transport has no fast heartbeat callback. Observe public Future/FSM endpoints separately.')

    def support_files(self):
        return {str(Path(self.package)/'assurance_support_test.go'):
            Path(__file__).with_name('assurance_support_test.go').read_text()}
