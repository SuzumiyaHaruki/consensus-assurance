import java.io.File;
import java.nio.file.Files;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.server.Request;
import org.apache.zookeeper.server.ZKDatabase;
import org.apache.zookeeper.server.persistence.FileTxnSnapLog;
import org.apache.zookeeper.txn.CreateTxn;
import org.apache.zookeeper.txn.TxnHeader;

/**
 * ZKDatabase.clear is documented to clear the database state.  The
 * transaction counter and log-size accounting are also reset by rollLog,
 * and should not survive a clear/truncate/reload.
 */
public class ClearTxnCountRepro {
    public static void main(String[] args) throws Exception {
        File data = Files.createTempDirectory("clear-txn-count-data").toFile();
        File snap = Files.createTempDirectory("clear-txn-count-snap").toFile();
        FileTxnSnapLog files = new FileTxnSnapLog(data, snap);
        ZKDatabase db = new ZKDatabase(files);

        TxnHeader hdr = new TxnHeader(1, 0, 1, 1, ZooDefs.OpCode.create);
        Request request = new Request(1, 0, ZooDefs.OpCode.create, hdr,
            new CreateTxn("/txn", new byte[0], ZooDefs.Ids.OPEN_ACL_UNSAFE, false, 0), 1);
        if (!db.append(request)) {
            throw new AssertionError("append failed");
        }
        db.commit();
        System.out.println("txn count before clear: " + db.getTxnCount());
        System.out.println("log size before clear: " + db.getTxnSize());

        db.clear();
        System.out.println("txn count after clear: " + db.getTxnCount());
        System.out.println("log size after clear: " + db.getTxnSize());
        if (db.getTxnCount() != 0) {
            throw new AssertionError("txnCount survived ZKDatabase.clear()");
        }
    }
}
