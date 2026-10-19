package org.apache.zookeeper.server.quorum;

import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.server.persistence.Util;
import org.apache.zookeeper.server.util.SerializeUtils;
import org.apache.zookeeper.txn.CreateTxn;
import org.apache.zookeeper.txn.TxnHeader;
import org.mockito.Mockito;

/**
 * A follower that receives the same PROPOSE twice should release the
 * redundant proposal instead of queuing two pending transactions.
 */
public class DuplicateProposalRepro {
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
        CreateTxn txn = new CreateTxn("/duplicate", new byte[0],
            ZooDefs.Ids.OPEN_ACL_UNSAFE, false, 0);
        byte[] data = Util.marshallTxnEntry(hdr, txn, null);
        QuorumPacket packet = new QuorumPacket(Leader.PROPOSAL, 5L, data, null);

        follower.receive(packet);
        follower.receive(packet);
        Mockito.verify(zk, Mockito.times(2)).logRequest(Mockito.any());
        throw new AssertionError(
            "the same PROPOSE was delivered to logRequest twice instead of being released");
    }
}
