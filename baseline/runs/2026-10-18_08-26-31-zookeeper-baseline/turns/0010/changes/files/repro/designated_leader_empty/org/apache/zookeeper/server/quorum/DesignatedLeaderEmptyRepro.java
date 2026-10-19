package org.apache.zookeeper.server.quorum;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.net.InetSocketAddress;
import java.util.HashMap;
import java.util.Map;
import org.apache.zookeeper.server.quorum.flexible.QuorumMaj;
import org.mockito.Mockito;

/**
 * A reconfig whose new view has only the current leader as a voter, but with
 * a different leader address, leaves getDesignatedLeader with no candidate
 * after it removes self. It must not throw from iterator().next().
 */
public class DesignatedLeaderEmptyRepro {
    public static void main(String[] args) throws Exception {
        QuorumPeer self = Mockito.mock(QuorumPeer.class);
        Mockito.when(self.getMyId()).thenReturn(1L);
        Mockito.when(self.getQuorumListenOnAllIPs()).thenReturn(false);
        Mockito.when(self.shouldUsePortUnification()).thenReturn(false);
        Mockito.when(self.isSslQuorum()).thenReturn(false);
        Mockito.when(self.getQuorumAddress()).thenReturn(
            new MultipleAddresses(new InetSocketAddress("127.0.0.1", 0)));

        LeaderZooKeeperServer zk = Mockito.mock(LeaderZooKeeperServer.class);
        Leader leader = new Leader(self, zk);

        Map<Long, QuorumPeer.QuorumServer> members = new HashMap<>();
        members.put(1L, new QuorumPeer.QuorumServer(
            1L,
            new InetSocketAddress("127.0.0.1", 2181),
            new InetSocketAddress("127.0.0.1", 3888)));
        QuorumMaj qv = new QuorumMaj(members);

        Leader.Proposal proposal = new Leader.Proposal();
        proposal.addQuorumVerifier(qv);
        proposal.addAck(1L);

        Method method = Leader.class.getDeclaredMethod(
            "getDesignatedLeader", Leader.Proposal.class, long.class);
        method.setAccessible(true);
        try {
            Object result = method.invoke(leader, proposal, 0L);
            System.out.println("designated leader: " + result);
        } catch (InvocationTargetException e) {
            e.getCause().printStackTrace(System.out);
            throw new AssertionError(
                "getDesignatedLeader threw instead of returning a valid leader", e.getCause());
        }
    }
}
