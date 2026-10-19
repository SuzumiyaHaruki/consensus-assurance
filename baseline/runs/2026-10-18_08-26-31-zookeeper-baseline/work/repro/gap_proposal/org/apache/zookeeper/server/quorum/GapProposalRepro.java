package org.apache.zookeeper.server.quorum;

import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.server.persistence.Util;
import org.apache.zookeeper.txn.CreateTxn;
import org.apache.zookeeper.txn.TxnHeader;
import org.mockito.Mockito;

/**
 * A fresh follower with lastQueued == 0 must not queue a proposal at zxid 5
 * without the intervening log entries.  The current live path only warns.
 */
public class GapProposalRepro {
    static class Probe extends Follower {
        Probe(QuorumPeer self, FollowerZooKeeperServer zk) {
            super(self, zk);
        }

        void receive(QuorumPacket packet) throws Exception {
            processPacket(packet);
        }
    }

    public static void main(String[] args) throws Exception {
        QuorumPeer self = Mockito.mock(QuorumPeer.class);
        FollowerZooKeeperServer zk = Mockito.mock(FollowerZooKeeperServer.class);
        Probe follower = new Probe(self, zk);

        TxnHeader hdr = new TxnHeader(1, 0, 5L, 5L, ZooDefs.OpCode.create);
        CreateTxn txn = new CreateTxn("/gap", new byte[0],
            ZooDefs.Ids.OPEN_ACL_UNSAFE, false, 0);
        QuorumPacket packet = new QuorumPacket(Leader.PROPOSAL, 5L,
            Util.marshallTxnEntry(hdr, txn, null), null);

        follower.receive(packet);
        Mockito.verify(zk, Mockito.times(1)).logRequest(Mockito.any());
        throw new AssertionError(
            "a proposal with a missing predecessor was queued for logging");
    }
}
