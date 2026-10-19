import java.io.File;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.Map;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.server.DataNode;
import org.apache.zookeeper.server.DataTree;
import org.apache.zookeeper.server.persistence.FileSnap;
import org.apache.zookeeper.server.persistence.SnapStream;

/**
 * A structurally valid snapshot can contain a node whose extended
 * ephemeralOwner is invalid.  If the newer snapshot raises a RuntimeException
 * during DataTree.deserialize, FileSnap must still fall back to the older
 * snapshot rather than aborting recovery.
 */
public class SnapshotRuntimeRepro {
    public static void main(String[] args) throws Exception {
        File dir = Files.createTempDirectory("snapshot-runtime-repro").toFile();
        FileSnap snap = new FileSnap(dir);

        DataTree older = new DataTree();
        older.lastProcessedZxid = 1;
        snap.serialize(older, new HashMap<>(), new File(dir, "snapshot.00000001"), true);

        DataTree newer = new DataTree();
        newer.lastProcessedZxid = 2;
        newer.createNode("/invalid-owner", new byte[0], ZooDefs.Ids.OPEN_ACL_UNSAFE,
                0L, 0, 2L, System.currentTimeMillis());
        DataNode badNode = newer.getNode("/invalid-owner");
        badNode.stat.setEphemeralOwner(0xff00010000000001L);
        File newerFile = new File(dir, "snapshot.00000002");
        snap.serialize(newer, new HashMap<>(), newerFile, true);
        System.out.println("newer snapshot accepted by pre-check: "
            + SnapStream.isValidSnapshot(newerFile));

        DataTree restored = new DataTree();
        Map<Long, Integer> sessions = new HashMap<>();
        try {
            long zxid = snap.deserialize(restored, sessions);
            System.out.println("fallback restored zxid: " + zxid);
            System.out.println("invalid node present: "
                + (restored.getNode("/invalid-owner") != null));
            if (zxid != 1 || restored.getNode("/invalid-owner") != null) {
                throw new AssertionError("the older snapshot was not restored");
            }
        } catch (RuntimeException e) {
            e.printStackTrace(System.out);
            throw new AssertionError(
                "runtime failure in the newer snapshot aborted the fallback", e);
        }
    }
}
