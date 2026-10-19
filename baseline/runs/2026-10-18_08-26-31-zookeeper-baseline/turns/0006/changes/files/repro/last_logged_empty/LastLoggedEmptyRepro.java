import java.io.File;
import java.io.RandomAccessFile;
import java.util.Arrays;
import java.util.Comparator;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.server.Request;
import org.apache.zookeeper.server.persistence.FileTxnLog;
import org.apache.zookeeper.txn.CreateTxn;
import org.apache.zookeeper.txn.TxnHeader;

/**
 * If the newest transaction-log file is empty, getLastLoggedZxid must report
 * the last transaction actually present in the older log, not the empty
 * file's name.
 */
public class LastLoggedEmptyRepro {
    public static void main(String[] args) throws Exception {
        File dir = java.nio.file.Files.createTempDirectory("last-logged-empty").toFile();
        FileTxnLog.setTxnLogSizeLimit(-1);
        FileTxnLog log = new FileTxnLog(dir);
        append(log, 1);
        log.rollLog();
        append(log, 2);
        log.commit();
        log.close();

        File[] logs = dir.listFiles((d, name) -> name.startsWith("log."));
        Arrays.sort(logs, Comparator.comparing(File::getName));
        File newest = logs[logs.length - 1];
        try (RandomAccessFile raf = new RandomAccessFile(newest, "rw")) {
            raf.setLength(0);
        }
        System.out.println("newest log cleared: " + newest.getName());

        long last = new FileTxnLog(dir).getLastLoggedZxid();
        System.out.println("reported last logged zxid: " + last);
        if (last != 1) {
            throw new AssertionError(
                "empty tail made getLastLoggedZxid report " + last + " instead of 1");
        }
    }

    private static void append(FileTxnLog log, long zxid) throws Exception {
        TxnHeader hdr = new TxnHeader(1, 0, zxid, zxid, ZooDefs.OpCode.create);
        CreateTxn txn = new CreateTxn("/l" + zxid, new byte[0],
                ZooDefs.Ids.OPEN_ACL_UNSAFE, false, 0);
        log.append(new Request(1, 0, ZooDefs.OpCode.create, hdr, txn, zxid));
    }
}
