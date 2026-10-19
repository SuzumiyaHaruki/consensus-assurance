import java.io.File;
import java.lang.reflect.Method;
import java.net.InetSocketAddress;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.Map;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.server.DataTree;
import org.apache.zookeeper.server.persistence.FileSnap;
import org.apache.zookeeper.server.quorum.QuorumPeer;

/**
 * Upgrade/partial-epoch-file case: currentEpoch exists and is ahead of the
 * snapshot zxid, while acceptedEpoch is missing.  loadDataBase must not
 * create an acceptedEpoch below currentEpoch and then reject it.
 */
public class EpochMissingRepro {
    public static void main(String[] args) throws Exception {
        File dataDir = Files.createTempDirectory("epoch-missing-data").toFile();
        File logDir = Files.createTempDirectory("epoch-missing-log").toFile();
        Map<Long, QuorumPeer.QuorumServer> peers = new HashMap<>();
        InetSocketAddress a = new InetSocketAddress("127.0.0.1", 0);
        peers.put(1L, new QuorumPeer.QuorumServer(1L, a, a));
        QuorumPeer peer = new QuorumPeer(
            peers, dataDir, logDir, 3, 1L, 2000, 10, 5, 5, null);
        File snapDir = peer.getTxnFactory().getSnapDir();

        DataTree tree = new DataTree();
        tree.lastProcessedZxid = 5;
        tree.createNode("/epoch-test", new byte[0], ZooDefs.Ids.OPEN_ACL_UNSAFE,
            0L, 0, 5L, System.currentTimeMillis());
        new FileSnap(snapDir).serialize(
            tree, new HashMap<>(), new File(snapDir, "snapshot.00000005"), true);

        Files.writeString(new File(snapDir, "currentEpoch").toPath(), "6");
        Files.deleteIfExists(new File(snapDir, "acceptedEpoch").toPath());
        System.out.println("currentEpoch=6, acceptedEpoch missing, snapshot zxid=5");

        Method load = QuorumPeer.class.getDeclaredMethod("loadDataBase");
        load.setAccessible(true);
        try {
            load.invoke(peer);
            System.out.println("loadDataBase completed");
        } catch (java.lang.reflect.InvocationTargetException e) {
            e.getCause().printStackTrace(System.out);
            throw new AssertionError("loadDataBase rejected the missing acceptedEpoch", e.getCause());
        }
    }
}
