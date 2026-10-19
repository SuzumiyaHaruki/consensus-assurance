package org.apache.zookeeper.server.quorum;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import org.apache.jute.BinaryInputArchive;
import org.apache.jute.BinaryOutputArchive;
import org.apache.zookeeper.server.ZKDatabase;
import org.mockito.Mockito;

/**
 * After TRUNC, writeToTxnLog is false.  A COMMIT with no proposal must not
 * dereference pif.hdr.
 */
public class SyncCommitEmptyRepro {
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
        Mockito.when(db.truncateLog(0L)).thenReturn(true);
        Mockito.when(zk.shouldForceWriteInitialSnapshotAfterLeaderElection()).thenReturn(false);

        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        BinaryOutputArchive out = BinaryOutputArchive.getArchive(bytes);
        out.writeRecord(new QuorumPacket(Leader.TRUNC, 0, null, null), "packet");
        out.writeRecord(new QuorumPacket(Leader.COMMIT, 1, null, null), "packet");

        Probe follower = new Probe(self, zk);
        follower.setInput(bytes.toByteArray());
        try {
            follower.sync(1L);
            throw new AssertionError("unexpectedly accepted COMMIT without a proposal");
        } catch (NullPointerException e) {
            e.printStackTrace(System.out);
            throw new AssertionError(
                "syncWithLeader dereferenced a missing proposal for COMMIT", e);
        }
    }
}
