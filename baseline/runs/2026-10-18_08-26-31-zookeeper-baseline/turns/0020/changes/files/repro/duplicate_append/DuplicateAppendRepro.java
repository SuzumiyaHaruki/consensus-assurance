import java.io.File;
import java.nio.file.Files;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.server.Request;
import org.apache.zookeeper.server.persistence.FileTxnLog;
import org.apache.zookeeper.server.persistence.TxnLog;
import org.apache.zookeeper.txn.CreateTxn;
import org.apache.zookeeper.txn.TxnHeader;

/**
 * A transaction log must not retain two entries with the same zxid.
 */
public class DuplicateAppendRepro {
    public static void main(String[] args) throws Exception {
        File dir = Files.createTempDirectory("duplicate-append").toFile();
        FileTxnLog log = new FileTxnLog(dir);
        System.out.println("first append: " + appendResult(log, 1));
        System.out.println("second append: " + appendResult(log, 1));
        log.commit();
        log.close();
        File[] files = dir.listFiles((d, name) -> name.startsWith("log."));
        System.out.println("log file lengths: " + files[0].length());

        int count = 0;
        try (FileTxnLog read = new FileTxnLog(dir);
             TxnLog.TxnIterator itr = read.read(0)) {
            while (itr.getHeader() != null) {
                System.out.println("logged zxid: " + itr.getHeader().getZxid());
                count++;
                if (!itr.next()) {
                    break;
                }
            }
        }
        System.out.println("txn count: " + count);
        if (count > 1) {
            throw new AssertionError("duplicate zxid was retained in the transaction log");
        }
    }

    private static void append(FileTxnLog log, long zxid) throws Exception {
        if (!appendResult(log, zxid)) {
            throw new AssertionError("append rejected");
        }
    }

    private static boolean appendResult(FileTxnLog log, long zxid) throws Exception {
        TxnHeader hdr = new TxnHeader(1, 0, zxid, zxid, ZooDefs.OpCode.create);
        CreateTxn txn = new CreateTxn("/d" + zxid, new byte[0],
                ZooDefs.Ids.OPEN_ACL_UNSAFE, false, 0);
        return log.append(new Request(1, 0, ZooDefs.OpCode.create, hdr, txn, zxid));
    }
}
