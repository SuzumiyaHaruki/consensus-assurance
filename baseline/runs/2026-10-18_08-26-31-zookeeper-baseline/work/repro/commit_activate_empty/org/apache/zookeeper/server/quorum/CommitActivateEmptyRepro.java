package org.apache.zookeeper.server.quorum;

import java.lang.reflect.Field;
import java.util.concurrent.LinkedBlockingQueue;
import org.apache.zookeeper.server.Request;
import org.mockito.Mockito;

/**
 * A COMMITANDACTIVATE packet with no matching pending proposal must not
 * throw an unchecked NoSuchElementException from pendingTxns.element().
 */
public class CommitActivateEmptyRepro {
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
        Field pending = FollowerZooKeeperServer.class.getDeclaredField("pendingTxns");
        pending.setAccessible(true);
        pending.set(zk, new LinkedBlockingQueue<Request>());
        Probe follower = new Probe(self, zk);

        QuorumPacket packet = new QuorumPacket(Leader.COMMITANDACTIVATE, 1L,
            new byte[8], null);
        try {
            follower.receive(packet);
            throw new AssertionError("unexpectedly accepted an empty COMMITANDACTIVATE");
        } catch (java.util.NoSuchElementException e) {
            e.printStackTrace(System.out);
            throw new AssertionError(
                "empty COMMITANDACTIVATE escaped as an unchecked queue exception", e);
        }
    }
}
