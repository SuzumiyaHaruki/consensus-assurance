// Bounded static-topology exploration. This is coverage evidence, not a liveness proof.
use omnipaxos_audit_repro::{cluster, Node, Value};
fn connected(mask: u16, a: u64, b: u64) -> bool {
    if a == b { return true; }
    let mut bit = 0;
    for i in 1..=5 { for j in i+1..=5 {
        if (i == a && j == b) || (i == b && j == a) { return mask & (1 << bit) != 0; }
        bit += 1;
    }}
    unreachable!()
}
fn deliver(nodes: &mut [Node], mask: u16) {
    for _ in 0..100 {
        let mut msgs = vec![];
        for n in nodes.iter_mut() { n.take_outgoing_messages(&mut msgs); }
        if msgs.is_empty() { return; }
        for m in msgs {
            if connected(mask, m.get_sender(), m.get_receiver()) {
                nodes[m.get_receiver() as usize - 1].handle_incoming(m);
            }
        }
    }
    panic!("message handling did not quiesce for topology {mask:010b}");
}
fn main() {
    let mut checked = 0;
    let mut failed = vec![];
    for mask in 0..1024 {
        // Documented sufficient condition: at least one node connected to a quorum (3).
        if !(1..=5).any(|a| (1..=5).filter(|&b| connected(mask, a, b)).count() >= 3) { continue; }
        checked += 1;
        let mut nodes = cluster(&[1,2,3,4,5]);
        deliver(&mut nodes, mask);
        let mut progressed = false;
        for step in 0..200 {
            for n in nodes.iter_mut() { n.tick(); }
            deliver(&mut nodes, mask);
            // Retry fresh proposals rather than assuming delivery of any individual forwarded one.
            if step % 10 == 0 {
                for n in nodes.iter_mut() { n.append(Value((step * 5) as u64 + n.get_pid())).unwrap(); }
                deliver(&mut nodes, mask);
            }
            if nodes.iter().any(|n| n.get_decided_idx() > 0) { progressed = true; break; }
        }
        if !progressed { failed.push(mask); println!("NO PROGRESS mask={mask:010b}, leaders={:?}", nodes.iter().map(|n| n.get_current_leader()).collect::<Vec<_>>()); }
    }
    println!("Checked {checked} undirected five-node static topologies with a quorum-connected node; {} failed to decide within 200 ticks", failed.len());
    assert!(failed.is_empty(), "bounded progress failures: {failed:?}");
}
