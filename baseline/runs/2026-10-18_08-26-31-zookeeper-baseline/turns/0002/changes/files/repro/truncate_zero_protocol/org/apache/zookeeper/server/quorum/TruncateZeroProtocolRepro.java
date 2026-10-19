package org.apache.zookeeper.server.quorum;

import java.io.BufferedInputStream;
import java.io.ByteArrayInputStream;
import java.net.Socket;
import java.util.Collections;
import java.util.concurrent.locks.ReentrantReadWriteLock;
import org.apache.zookeeper.server.ZKDatabase;
import org.mockito.Mockito;

/**
 * Demonstrates that LearnerHandler.syncFollower selects TRUNC(0) for a
 * follower at zxid 8 when the leader has an empty committed view.
 */
public class TruncateZeroProtocolRepro {
    public static void main(String[] args) throws Exception {
        ZKDatabase db = Mockito.mock(ZKDatabase.class);
        Mockito.when(db.getLogLock()).thenReturn(new ReentrantReadWriteLock());
        Mockito.when(db.getCommittedLog()).thenReturn(Collections.emptyList());
        Mockito.when(db.getmaxCommittedLog()).thenReturn(0L);
        Mockito.when(db.getminCommittedLog()).thenReturn(0L);
        Mockito.when(db.getDataTreeLastProcessedZxid()).thenReturn(0L);
        Mockito.when(db.isTxnLogSyncEnabled()).thenReturn(true);

        LearnerMaster master = Mockito.mock(LearnerMaster.class);
        Mockito.when(master.getZKDatabase()).thenReturn(db);
        Mockito.when(master.getQuorumAuthServer()).thenReturn(null);
        Mockito.when(master.startForwarding(Mockito.any(LearnerHandler.class), Mockito.anyLong()))
            .thenReturn(0L);

        Socket socket = new Socket();
        LearnerHandler handler = new LearnerHandler(
            socket, new BufferedInputStream(new ByteArrayInputStream(new byte[0])), master);
        boolean needSnap = handler.syncFollower(8L, master);
        System.out.println("need snap: " + needSnap);
        for (QuorumPacket packet : handler.queuedPackets) {
            if (packet.getType() == Leader.TRUNC) {
                System.out.println("queued TRUNC zxid: " + packet.getZxid());
                if (packet.getZxid() == 0) {
                    System.out.println("confirmed: leader requested truncate(0)");
                    return;
                }
            }
        }
        throw new AssertionError("syncFollower did not queue TRUNC(0)");
    }
}
