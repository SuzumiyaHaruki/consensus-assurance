import java.io.File;
import java.nio.file.Files;
import java.util.HashMap;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.server.Request;
import org.apache.zookeeper.server.ZKDatabase;
import org.apache.zookeeper.server.DataTree;
import org.apache.zookeeper.server.persistence.FileSnap;
import org.apache.zookeeper.server.persistence.FileTxnLog;
import org.apache.zookeeper.server.persistence.FileTxnSnapLog;
import org.apache.zookeeper.txn.CreateTxn;
import org.apache.zookeeper.txn.TxnHeader;

/**
 * Truncating a database to zxid 5 must not restore snapshot.00000007 or
 * retain a zxid-8 transaction.
 */
public class TruncateNonzeroDbRepro {
    public static void main(String[] args) throws Exception {
        File data = Files.createTempDirectory("truncate-nonzero-data").toFile();
        File snap = Files.createTempDirectory("truncate-nonzero-snap").toFile();
        FileTxnSnapLog files = new FileTxnSnapLog(data, snap);

        DataTree tree = new DataTree();
        tree.lastProcessedZxid = 7;
        tree.createNode("/snapshot-7", new byte[0], ZooDefs.Ids.OPEN_ACL_UNSAFE,
            0L, 0, 7L, System.currentTimeMillis());
        new FileSnap(files.getSnapDir()).serialize(
            tree, new HashMap<>(), new File(files.getSnapDir(), "snapshot.00000007"), true);

        FileTxnLog log = new FileTxnLog(files.getDataLogDir());
        TxnHeader hdr = new TxnHeader(1, 0, 8L, 8L, ZooDefs.OpCode.create);
        log.append(new Request(1, 0, ZooDefs.OpCode.create, hdr,
            new CreateTxn("/txn-8", new byte[0], ZooDefs.Ids.OPEN_ACL_UNSAFE, false, 0), 8L));
        log.commit();
        log.close();

        ZKDatabase db = new ZKDatabase(files);
        db.loadDataBase();
        if (!db.truncateLog(5)) {
            throw new AssertionError("truncateLog(5) returned false");
        }
        boolean snapNode = db.getDataTree().getNode("/snapshot-7") != null;
        boolean txnNode = db.getDataTree().getNode("/txn-8") != null;
        System.out.println("after truncateLog(5): snapshot7=" + snapNode + ", txn8=" + txnNode);
        if (snapNode || txnNode) {
            throw new AssertionError("truncateLog(5) retained data newer than zxid 5");
        }
    }
}
