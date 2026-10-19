import java.util.ArrayList;
import java.util.HashMap;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import org.apache.zookeeper.server.quorum.Leader;
import org.apache.zookeeper.server.quorum.QuorumPacket;
import org.apache.zookeeper.server.quorum.flexible.QuorumOracleMaj;
import org.mockito.Mockito;

/**
 * QuorumOracleMaj.revalidateOutstandingProp is supposed to return false when
 * it cannot commit an outstanding proposal. With one outstanding proposal and
 * Leader.tryToCommit returning false (the normal "not enough acks yet" case),
 * the method must return rather than spin.
 */
public class OracleRevalidateRepro {
    public static void main(String[] args) throws Exception {
        Leader leader = Mockito.mock(Leader.class);
        Mockito.when(leader.tryToCommit(
                Mockito.any(Leader.Proposal.class),
                Mockito.anyLong(),
                Mockito.any()))
            .thenReturn(false);

        QuorumOracleMaj qv = new QuorumOracleMaj(new HashMap<>(), null);
        ArrayList<Leader.Proposal> outstanding = new ArrayList<>();
        outstanding.add(new Leader.Proposal(
            new QuorumPacket(Leader.PROPOSAL, 5L, null, null)));

        ExecutorService pool = Executors.newSingleThreadExecutor(r -> {
            Thread t = new Thread(r, "oracle-revalidate-repro");
            t.setDaemon(true);
            return t;
        });
        Future<Boolean> result = pool.submit(
            () -> qv.revalidateOutstandingProp(leader, outstanding, 0L));
        try {
            boolean committed = result.get(2, TimeUnit.SECONDS);
            System.out.println("revalidateOutstandingProp returned: " + committed);
            if (committed) {
                throw new AssertionError("must not report success when tryToCommit failed");
            }
        } catch (TimeoutException e) {
            result.cancel(true);
            throw new AssertionError(
                "revalidateOutstandingProp did not return within 2 seconds while tryToCommit was false");
        } finally {
            pool.shutdownNow();
        }
    }
}
