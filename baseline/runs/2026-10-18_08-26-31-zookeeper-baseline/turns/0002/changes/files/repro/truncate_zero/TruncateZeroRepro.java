import java.io.File;
import java.nio.file.Files;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.server.Request;
import org.apache.zookeeper.server.persistence.FileTxnLog;
import org.apache.zookeeper.txn.CreateTxn;
import org.apache.zookeeper.txn.TxnHeader;

/**
 * Truncating a non-empty transaction log to zxid 0 should remove every
 * transaction.  This is the state a follower receives when it must discard
 * all entries and synchronize from an empty leader.
 */
public class TruncateZeroRepro {
    public static void main(String[] args) throws Exception {
        File dir = Files.createTempDirectory("truncate-zero-repro").toFile();
        FileTxnLog log = new FileTxnLog(dir);
        append(log, 1);
        append(log, 2);
        log.commit();
        log.close();

        FileTxnLog trunc = new FileTxnLog(dir);
        if (!trunc.truncate(0)) {
            throw new AssertionError("truncate(0) returned false");
        }
        trunc.close();

        long last = new FileTxnLog(dir).getLastLoggedZxid();
        System.out.println("last logged zxid after truncate(0): " + last);
        if (last > 0) {
            throw new AssertionError(
                "transaction log still contains zxid " + last + " after truncate(0)");
        }
    }

    private static void append(FileTxnLog log, long zxid) throws Exception {
        TxnHeader hdr = new TxnHeader(1, 0, zxid, zxid, ZooDefs.OpCode.create);
        CreateTxn txn = new CreateTxn("/z" + zxid, new byte[0],
                ZooDefs.Ids.OPEN_ACL_UNSAFE, false, 0);
        log.append(new Request(1, 0, ZooDefs.OpCode.create, hdr, txn, zxid));
    }
}
