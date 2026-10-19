package org.apache.zookeeper.server.quorum;

import java.io.File;
import java.lang.reflect.Method;
import java.net.InetSocketAddress;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.Map;
import org.apache.zookeeper.server.quorum.flexible.QuorumOracleMaj;
import org.mockito.Mockito;

/**
 * QuorumOracleMaj is documented to behave like QuorumMaj when there are more
 * than two voters. FastLeaderElection.receivedLeadingNotification, however,
 * checks only getNeedOracle() and can accept a LEADING notification without a
 * majority. This repro uses three voters and one vote.
 */
public class OracleFleRepro {
    public static void main(String[] args) throws Exception {
        File oracleFile = File.createTempFile("zk-oracle-", ".txt");
        Files.write(oracleFile.toPath(), "0".getBytes());

        Map<Long, QuorumPeer.QuorumServer> members = new HashMap<>();
        for (long sid = 1; sid <= 3; sid++) {
            InetSocketAddress a = new InetSocketAddress("127.0.0.1", 21000 + (int) sid);
            members.put(sid, new QuorumPeer.QuorumServer(sid, a, a));
        }
        QuorumOracleMaj qv = new QuorumOracleMaj(members, oracleFile.getAbsolutePath());

        QuorumPeer self = Mockito.mock(QuorumPeer.class);
        Mockito.when(self.getMyId()).thenReturn(1L);
        Mockito.when(self.getQuorumVerifier()).thenReturn(qv);
        Mockito.when(self.getLastSeenQuorumVerifier()).thenReturn(null);
        Mockito.when(self.getLearnerType()).thenReturn(QuorumPeer.LearnerType.PARTICIPANT);

        QuorumCnxManager manager = Mockito.mock(QuorumCnxManager.class);
        FastLeaderElection fle = new FastLeaderElection(self, manager);

        FastLeaderElection.Notification n = new FastLeaderElection.Notification();
        n.version = FastLeaderElection.Notification.CURRENTVERSION;
        n.leader = 2L;
        n.zxid = 5L;
        n.electionEpoch = 1L;
        n.peerEpoch = 1L;
        n.state = QuorumPeer.ServerState.LEADING;
        n.sid = 3L;

        Method method = FastLeaderElection.class.getDeclaredMethod(
            "receivedLeadingNotification", Map.class, Map.class,
            SyncedLearnerTracker.class, FastLeaderElection.Notification.class);
        method.setAccessible(true);
        Object result = method.invoke(fle, new HashMap<Long, Vote>(),
            new HashMap<Long, Vote>(), null, n);

        System.out.println("result with one of three votes: " + result);
        if (result != null) {
            throw new AssertionError(
                "a LEADING notification was accepted without a majority in a three-voter config");
        }
    }
}
