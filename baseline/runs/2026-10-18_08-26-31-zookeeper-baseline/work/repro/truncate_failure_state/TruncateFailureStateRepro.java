import java.io.File;
import java.nio.file.Files;
import java.util.HashMap;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.server.DataTree;
import org.apache.zookeeper.server.ZKDatabase;
import org.apache.zookeeper.server.persistence.FileSnap;
import org.apache.zookeeper.server.persistence.FileTxnSnapLog;

/**
 * If truncation has no log files to operate on, it returns false.  The
 * existing in-memory database must not be silently cleared by the failed
 * attempt.
 */
public class TruncateFailureStateRepro {
    public static void main(String[] args) throws Exception {
        File data = Files.createTempDirectory("truncate-failure-data").toFile();
        File snap = Files.createTempDirectory("truncate-failure-snap").toFile();
        FileTxnSnapLog files = new FileTxnSnapLog(data, snap);

        DataTree tree = new DataTree();
        tree.lastProcessedZxid = 7;
        tree.createNode("/keep-on-failure", new byte[0], ZooDefs.Ids.OPEN_ACL_UNSAFE,
            0L, 0, 7L, System.currentTimeMillis());
        new FileSnap(files.getSnapDir()).serialize(
            tree, new HashMap<>(), new File(files.getSnapDir(), "snapshot.00000007"), true);

        ZKDatabase db = new ZKDatabase(files);
        db.loadDataBase();
        System.out.println("node before failed truncate: "
            + (db.getDataTree().getNode("/keep-on-failure") != null));
        boolean truncated = db.truncateLog(5);
        System.out.println("truncate result: " + truncated);
        System.out.println("node after failed truncate: "
            + (db.getDataTree().getNode("/keep-on-failure") != null));
        if (!truncated && db.getDataTree().getNode("/keep-on-failure") == null) {
            throw new AssertionError(
                "failed truncate cleared the in-memory database");
        }
    }
}
