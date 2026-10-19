package org.apache.zookeeper.server.quorum;

import java.io.BufferedOutputStream;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import org.apache.jute.BinaryInputArchive;
import org.apache.jute.BinaryOutputArchive;
import org.apache.jute.OutputArchive;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.server.ZKDatabase;
import org.apache.zookeeper.server.admin.AdminServer;
import org.apache.zookeeper.server.persistence.Util;
import org.apache.zookeeper.txn.CreateTxn;
import org.apache.zookeeper.txn.TxnHeader;
import org.mockito.Mockito;

/**
 * Observer sync: DIFF, one PROPOSAL, then UPTODATE leaves packetsCommitted
 * empty.  The observer cleanup loop must not auto-unbox a null commit zxid.
 */
public class ObserverSyncEmptyRepro {
    static class Probe extends Observer {
        Probe(QuorumPeer self, ObserverZooKeeperServer zk) {
            super(self, zk);
        }

        void sync(long zxid) throws Exception {
            syncWithLeader(zxid);
        }

        void setInput(byte[] bytes) {
            this.leaderIs = BinaryInputArchive.getArchive(new ByteArrayInputStream(bytes));
        }

        void setOutput() {
            this.leaderOs = BinaryOutputArchive.getArchive(new ByteArrayOutputStream());
            this.bufferedOutput = new BufferedOutputStream(new ByteArrayOutputStream());
        }
    }

    public static void main(String[] args) throws Exception {
        QuorumPeer self = Mockito.mock(QuorumPeer.class);
        ObserverZooKeeperServer zk = Mockito.mock(ObserverZooKeeperServer.class);
        ZKDatabase db = Mockito.mock(ZKDatabase.class);
        Mockito.when(self.isRunning()).thenReturn(true);
        Mockito.when(self.getQuorumVerifier()).thenReturn(null);
        self.adminServer = Mockito.mock(AdminServer.class);
        Mockito.when(zk.getZKDatabase()).thenReturn(db);
        Mockito.when(zk.shouldForceWriteInitialSnapshotAfterLeaderElection()).thenReturn(false);

        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        BinaryOutputArchive out = BinaryOutputArchive.getArchive(bytes);
        out.writeRecord(new QuorumPacket(Leader.DIFF, 0, null, null), "packet");
        TxnHeader hdr = new TxnHeader(1, 0, 1L, 1L, ZooDefs.OpCode.create);
        byte[] txn = Util.marshallTxnEntry(hdr,
            new CreateTxn("/observer", new byte[0], ZooDefs.Ids.OPEN_ACL_UNSAFE, false, 0), null);
        out.writeRecord(new QuorumPacket(Leader.PROPOSAL, 1L, txn, null), "packet");
        out.writeRecord(new QuorumPacket(Leader.UPTODATE, -1, null, null), "packet");

        Probe observer = new Probe(self, zk);
        observer.setInput(bytes.toByteArray());
        observer.setOutput();
        try {
            observer.sync(1L);
            throw new AssertionError("unexpectedly completed observer sync without a commit");
        } catch (NullPointerException e) {
            e.printStackTrace(System.out);
            throw new AssertionError(
                "observer sync auto-unboxed a missing commit zxid", e);
        }
    }
}
