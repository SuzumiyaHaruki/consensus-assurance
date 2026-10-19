#![cfg(not(feature = "unicache"))]

use omnipaxos::{ClusterConfig, OmniPaxosConfig, ServerConfig};

#[test]
fn duplicate_node_ids_are_rejected() {
    let cfg = OmniPaxosConfig {
        cluster_config: ClusterConfig {
            configuration_id: 1,
            nodes: vec![1, 1],
            flexible_quorum: None,
        },
        server_config: ServerConfig {
            pid: 1,
            ..Default::default()
        },
    };

    assert!(
        cfg.validate().is_err(),
        "a two-entry node list containing only node ID 1 cannot form a two-node cluster"
    );
}
