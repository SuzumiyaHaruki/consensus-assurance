package org.apache.zookeeper.server.quorum;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import org.apache.jute.BinaryInputArchive;
import org.apache.jute.BinaryOutputArchive;
import org.apache.zookeeper.server.ZKDatabase;
import org.mockito.Mockito;

/**
 * syncWithLeader receives DIFF followed by COMMITANDACTIVATE without a
 * proposal.  It must not dereference a missing PacketInFlight.
 */
public class SyncCommitActivateRepro {
    static class Probe extends Follower {
        Probe(QuorumPeer self, FollowerZooKeeperServer zk) {
            super(self, zk);
        }

        void sync(long zxid) throws Exception {
            syncWithLeader(zxid);
        }

        void setInput(byte[] bytes) {
            this.leaderIs = BinaryInputArchive.getArchive(new ByteArrayInputStream(bytes));
        }
    }

    public static void main(String[] args) throws Exception {
        QuorumPeer self = Mockito.mock(QuorumPeer.class);
        FollowerZooKeeperServer zk = Mockito.mock(FollowerZooKeeperServer.class);
        ZKDatabase db = Mockito.mock(ZKDatabase.class);
        Mockito.when(self.isRunning()).thenReturn(true);
        Mockito.when(self.getQuorumVerifier()).thenReturn(null);
        Mockito.when(zk.getZKDatabase()).thenReturn(db);
        Mockito.when(zk.shouldForceWriteInitialSnapshotAfterLeaderElection()).thenReturn(false);

        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        BinaryOutputArchive out = BinaryOutputArchive.getArchive(bytes);
        out.writeRecord(new QuorumPacket(Leader.DIFF, 0, null, null), "packet");
        out.writeRecord(new QuorumPacket(Leader.COMMITANDACTIVATE, 1, new byte[8], null), "packet");

        Probe follower = new Probe(self, zk);
        follower.setInput(bytes.toByteArray());
        try {
            follower.sync(1L);
            throw new AssertionError("unexpectedly accepted COMMITANDACTIVATE without a proposal");
        } catch (NullPointerException e) {
            e.printStackTrace(System.out);
            throw new AssertionError(
                "syncWithLeader dereferenced a missing proposal for COMMITANDACTIVATE", e);
        }
    }
}
