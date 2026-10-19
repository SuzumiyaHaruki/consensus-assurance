package org.apache.zookeeper.server.quorum;

import java.lang.reflect.Method;
import java.net.InetSocketAddress;
import java.util.HashMap;
import java.util.Map;
import org.apache.zookeeper.server.quorum.flexible.QuorumOracleMaj;
import org.mockito.Mockito;

/**
 * A missing oracle must not be interpreted as a negative answer that permits
 * a LOOKING node to follow a leader without a quorum.
 */
public class OracleMissingRepro {
    public static void main(String[] args) throws Exception {
        Map<Long, QuorumPeer.QuorumServer> members = new HashMap<>();
        for (long sid = 1; sid <= 2; sid++) {
            InetSocketAddress a = new InetSocketAddress("127.0.0.1", 22000 + (int) sid);
            members.put(sid, new QuorumPeer.QuorumServer(sid, a, a));
        }
        QuorumOracleMaj qv = new QuorumOracleMaj(members, null); // oracle unavailable

        QuorumPeer self = Mockito.mock(QuorumPeer.class);
        Mockito.when(self.getMyId()).thenReturn(1L);
        Mockito.when(self.getQuorumVerifier()).thenReturn(qv);
        Mockito.when(self.getLastSeenQuorumVerifier()).thenReturn(null);
        Mockito.when(self.getLearnerType()).thenReturn(QuorumPeer.LearnerType.PARTICIPANT);
        FastLeaderElection fle = new FastLeaderElection(
            self, Mockito.mock(QuorumCnxManager.class));

        FastLeaderElection.Notification n = new FastLeaderElection.Notification();
        n.version = FastLeaderElection.Notification.CURRENTVERSION;
        n.leader = 2L;
        n.zxid = 5L;
        n.electionEpoch = 1L;
        n.peerEpoch = 1L;
        n.state = QuorumPeer.ServerState.LEADING;
        n.sid = 2L;

        Method method = FastLeaderElection.class.getDeclaredMethod(
            "receivedLeadingNotification", Map.class, Map.class,
            SyncedLearnerTracker.class, FastLeaderElection.Notification.class);
        method.setAccessible(true);
        Object result = method.invoke(fle, new HashMap<Long, Vote>(),
            new HashMap<Long, Vote>(), null, n);
        System.out.println("result with missing oracle: " + result);
        if (result != null) {
            throw new AssertionError(
                "missing oracle was treated as permission to follow a leader");
        }
    }
}
