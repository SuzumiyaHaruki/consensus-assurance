package org.apache.zookeeper.server.quorum;

import java.io.BufferedInputStream;
import java.io.ByteArrayInputStream;
import java.net.Socket;
import java.util.Collections;
import java.util.concurrent.locks.ReentrantReadWriteLock;
import org.apache.zookeeper.server.ZKDatabase;
import org.mockito.Mockito;

/**
 * syncFollower must not send a TRUNC across an epoch boundary.  With leader
 * maxCommittedLog in epoch 0 and a follower zxid in epoch 1, the current
 * branch compares only the numeric zxid and emits TRUNC(maxCommittedLog).
 */
public class CrossEpochTruncRepro {
    public static void main(String[] args) throws Exception {
        ZKDatabase db = Mockito.mock(ZKDatabase.class);
        Mockito.when(db.getLogLock()).thenReturn(new ReentrantReadWriteLock());
        Mockito.when(db.getCommittedLog()).thenReturn(Collections.emptyList());
        Mockito.when(db.getmaxCommittedLog()).thenReturn(5L);
        Mockito.when(db.getminCommittedLog()).thenReturn(5L);
        Mockito.when(db.getDataTreeLastProcessedZxid()).thenReturn(5L);
        Mockito.when(db.isTxnLogSyncEnabled()).thenReturn(true);

        LearnerMaster master = Mockito.mock(LearnerMaster.class);
        Mockito.when(master.getZKDatabase()).thenReturn(db);
        Mockito.when(master.getQuorumAuthServer()).thenReturn(null);
        Mockito.when(master.startForwarding(Mockito.any(LearnerHandler.class), Mockito.anyLong()))
            .thenReturn(5L);

        LearnerHandler handler = new LearnerHandler(
            new Socket(), new BufferedInputStream(new ByteArrayInputStream(new byte[0])), master);
        long peer = 0x100000005L; // epoch 1, counter 5
        boolean needSnap = handler.syncFollower(peer, master);
        System.out.println("need snap: " + needSnap);
        for (QuorumPacket packet : handler.queuedPackets) {
            if (packet.getType() == Leader.TRUNC) {
                System.out.println("queued TRUNC zxid: 0x" + Long.toHexString(packet.getZxid()));
                if (packet.getZxid() == 5L) {
                    throw new AssertionError(
                        "syncFollower queued a cross-epoch TRUNC instead of a snapshot");
                }
            }
        }
        throw new AssertionError("syncFollower did not exercise the expected TRUNC path");
    }
}
