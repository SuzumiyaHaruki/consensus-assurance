import java.io.File;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.Map;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.server.DataTree;
import org.apache.zookeeper.server.ZooKeeperServer;
import org.apache.zookeeper.server.persistence.FileSnap;

/**
 * Reverse direction of DigestToggleRepro: write with digest disabled, restore
 * with digest enabled while lastProcessedZxid serialization is enabled.
 */
public class DigestToggleReverseRepro {
    public static void main(String[] args) throws Exception {
        File dir = Files.createTempDirectory("digest-toggle-reverse-repro").toFile();
        FileSnap snap = new FileSnap(dir);

        DataTree source = new DataTree();
        source.lastProcessedZxid = 7;
        source.createNode("/digest-toggle-reverse", new byte[] {1},
                ZooDefs.Ids.OPEN_ACL_UNSAFE, 0L, 0, 7L, System.currentTimeMillis());
        ZooKeeperServer.setDigestEnabled(false);
        File snapshotFile = new File(dir, "snapshot.00000007");
        snap.serialize(source, new HashMap<>(), snapshotFile, true);

        ZooKeeperServer.setDigestEnabled(true);
        DataTree restored = new DataTree();
        Map<Long, Integer> sessions = new HashMap<>();
        try {
            long zxid = snap.deserialize(restored, sessions);
            System.out.println("restored zxid with digest enabled: " + zxid);
            if (restored.getNode("/digest-toggle-reverse") == null) {
                throw new AssertionError("the snapshot node was not restored");
            }
        } catch (Exception e) {
            e.printStackTrace(System.out);
            throw new AssertionError(
                "snapshot written without digest could not be restored with digest enabled", e);
        }
    }
}
