import java.io.File;
import java.io.RandomAccessFile;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.Map;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.server.DataTree;
import org.apache.zookeeper.server.EphemeralType;
import org.apache.zookeeper.server.persistence.FileSnap;

/**
 * FileSnap skips a corrupt snapshot and retries an older one. The retry must
 * not retain state parsed from the failed snapshot.
 */
public class SnapshotRetryRepro {
    public static void main(String[] args) throws Exception {
        File dir = Files.createTempDirectory("snap-retry-repro").toFile();
        FileSnap snap = new FileSnap(dir);

        DataTree older = new DataTree();
        older.lastProcessedZxid = 1;
        snap.serialize(older, new HashMap<>(), new File(dir, "snapshot.00000001"), true);

        DataTree newer = new DataTree();
        newer.lastProcessedZxid = 2;
        Map<Long, Integer> newerSessions = new HashMap<>();
        newerSessions.put(123L, 4000);
        newer.createNode("/ephemeral-from-bad-snapshot", new byte[0],
                ZooDefs.Ids.OPEN_ACL_UNSAFE, 1L, 0, 2L, System.currentTimeMillis());
        newer.createNode("/container-from-bad-snapshot", new byte[0],
                ZooDefs.Ids.OPEN_ACL_UNSAFE, EphemeralType.CONTAINER_EPHEMERAL_OWNER,
                0, 2L, System.currentTimeMillis());
        newer.createNode("/ttl-from-bad-snapshot", new byte[0],
                ZooDefs.Ids.OPEN_ACL_UNSAFE,
                EphemeralType.TTL.toEphemeralOwner(60_000L),
                0, 2L, System.currentTimeMillis());
        File newerFile = new File(dir, "snapshot.00000002");
        snap.serialize(newer, newerSessions, newerFile, true);

        // Corrupt the trailing CRC seal, leaving the file structurally
        // recognizable as a snapshot (the last five bytes remain len=1, '/').
        try (RandomAccessFile raf = new RandomAccessFile(newerFile, "rw")) {
            long pos = raf.length() - 13; // long checksum followed by 4-byte len + '/'
            raf.seek(pos);
            int b = raf.read();
            raf.seek(pos);
            raf.write(b ^ 0x01);
        }

        DataTree restored = new DataTree();
        Map<Long, Integer> sessions = new HashMap<>();
        long zxid = snap.deserialize(restored, sessions);
        System.out.println("restored zxid: " + zxid);
        System.out.println("ephemerals after fallback: " + restored.getEphemerals());
        System.out.println("containers after fallback: " + restored.getContainers());
        System.out.println("ttls after fallback: " + restored.getTtls());
        System.out.println("sessions after fallback: " + sessions);
        System.out.println("node /ephemeral-from-bad-snapshot exists: "
                + (restored.getNode("/ephemeral-from-bad-snapshot") != null));

        if (restored.getNode("/ephemeral-from-bad-snapshot") != null
                || restored.getNode("/container-from-bad-snapshot") != null
                || restored.getNode("/ttl-from-bad-snapshot") != null) {
            throw new AssertionError("test setup error: node from corrupt snapshot was restored");
        }
        if (!restored.getEphemerals().isEmpty()) {
            throw new AssertionError(
                "ephemeral state from the rejected snapshot leaked into the restored tree");
        }
        if (!restored.getContainers().isEmpty() || !restored.getTtls().isEmpty()) {
            throw new AssertionError(
                "container/TTL state from the rejected snapshot leaked into the restored tree");
        }
        if (!sessions.isEmpty()) {
            throw new AssertionError(
                "session table from the rejected snapshot leaked into the restored state");
        }
    }
}
