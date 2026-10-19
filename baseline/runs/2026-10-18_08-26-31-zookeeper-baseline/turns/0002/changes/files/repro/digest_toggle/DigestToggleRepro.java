import java.io.File;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.Map;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.server.DataTree;
import org.apache.zookeeper.server.ZooKeeperServer;
import org.apache.zookeeper.server.persistence.FileSnap;
import org.apache.zookeeper.server.persistence.SnapStream;

/**
 * Snapshot compatibility check: write a snapshot with the default digest
 * setting, then restore it after disabling only the digest feature.  The
 * documented feature flags are independent; the snapshot should still be
 * readable, or the failure must be explained by a format marker.
 */
public class DigestToggleRepro {
    public static void main(String[] args) throws Exception {
        File dir = Files.createTempDirectory("digest-toggle-repro").toFile();
        FileSnap snap = new FileSnap(dir);

        DataTree source = new DataTree();
        source.lastProcessedZxid = 7;
        source.createNode("/digest-toggle", new byte[] {1}, ZooDefs.Ids.OPEN_ACL_UNSAFE,
                0L, 0, 7L, System.currentTimeMillis());
        File snapshotFile = new File(dir, "snapshot.00000007");
        snap.serialize(source, new HashMap<>(), snapshotFile, true);
        System.out.println("snapshot valid before toggle: " + SnapStream.isValidSnapshot(snapshotFile));

        ZooKeeperServer.setDigestEnabled(false);
        System.out.println("snapshot valid after toggle: " + SnapStream.isValidSnapshot(snapshotFile));
        DataTree restored = new DataTree();
        Map<Long, Integer> sessions = new HashMap<>();
        try {
            long zxid = snap.deserialize(restored, sessions);
            System.out.println("restored zxid without digest: " + zxid);
            System.out.println("restored node: " + restored.getNode("/digest-toggle"));
            if (restored.getNode("/digest-toggle") == null) {
                throw new AssertionError("the snapshot node was not restored");
            }
        } catch (Exception e) {
            e.printStackTrace(System.out);
            throw new AssertionError(
                "snapshot written with digest could not be restored with digest disabled", e);
        }
    }
}
