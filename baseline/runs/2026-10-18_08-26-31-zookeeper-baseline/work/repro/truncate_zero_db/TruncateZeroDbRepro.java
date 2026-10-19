import java.io.File;
import java.nio.file.Files;
import java.util.HashMap;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.server.Request;
import org.apache.zookeeper.server.ZKDatabase;
import org.apache.zookeeper.server.persistence.FileSnap;
import org.apache.zookeeper.server.persistence.FileTxnLog;
import org.apache.zookeeper.server.persistence.FileTxnSnapLog;
import org.apache.zookeeper.server.DataTree;
import org.apache.zookeeper.txn.CreateTxn;
import org.apache.zookeeper.txn.TxnHeader;

/**
 * Production-wrapper check for TRUNC(0): a database with a snapshot and a
 * transaction log must contain no user nodes after truncateLog(0).
 */
public class TruncateZeroDbRepro {
    public static void main(String[] args) throws Exception {
        File dataDir = Files.createTempDirectory("truncate-zero-data").toFile();
        File snapDir = Files.createTempDirectory("truncate-zero-snap").toFile();
        FileTxnSnapLog files = new FileTxnSnapLog(dataDir, snapDir);

        DataTree snapshotTree = new DataTree();
        snapshotTree.lastProcessedZxid = 7;
        snapshotTree.createNode("/from-snapshot", new byte[0], ZooDefs.Ids.OPEN_ACL_UNSAFE,
                0L, 0, 7L, System.currentTimeMillis());
        new FileSnap(files.getSnapDir()).serialize(
            snapshotTree, new HashMap<>(), new File(files.getSnapDir(), "snapshot.00000007"), true);

        FileTxnLog log = new FileTxnLog(files.getDataLogDir());
        TxnHeader hdr = new TxnHeader(1, 0, 8L, 8L, ZooDefs.OpCode.create);
        log.append(new Request(1, 0, ZooDefs.OpCode.create, hdr,
            new CreateTxn("/from-txn-log", new byte[0], ZooDefs.Ids.OPEN_ACL_UNSAFE, false, 0), 8L));
        log.commit();
        log.close();

        ZKDatabase db = new ZKDatabase(files);
        long before = db.loadDataBase();
        System.out.println("loaded zxid: " + before);
        System.out.println("before truncate: snapshot="
            + (db.getDataTree().getNode("/from-snapshot") != null)
            + ", txnlog=" + (db.getDataTree().getNode("/from-txn-log") != null));
        if (!db.truncateLog(0)) {
            throw new AssertionError("truncateLog(0) returned false");
        }
        System.out.println("after truncate: snapshot="
            + (db.getDataTree().getNode("/from-snapshot") != null)
            + ", txnlog=" + (db.getDataTree().getNode("/from-txn-log") != null));
        if (db.getDataTree().getNode("/from-snapshot") != null
                || db.getDataTree().getNode("/from-txn-log") != null) {
            throw new AssertionError("truncateLog(0) retained user data");
        }
    }
}
