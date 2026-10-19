import java.util.Arrays;
import org.apache.zookeeper.KeeperException.Code;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.server.DataTree;
import org.apache.zookeeper.txn.MultiTxn;
import org.apache.zookeeper.txn.Txn;
import org.apache.zookeeper.txn.TxnHeader;

/**
 * A malformed multi-op sub-transaction is not applied, but processTxn
 * currently returns rc.err == OK and advances lastProcessedZxid.
 */
public class MalformedMultiRepro {
    public static void main(String[] args) {
        DataTree tree = new DataTree();
        TxnHeader hdr = new TxnHeader(1, 0, 42, 42, ZooDefs.OpCode.multi);
        MultiTxn multi = new MultiTxn(
            Arrays.asList(new Txn(999, new byte[0])));
        System.out.println("lastProcessedZxid before: " + tree.lastProcessedZxid);
        DataTree.ProcessTxnResult result = tree.processTxn(hdr, multi);
        System.out.println("result error: " + result.err + " (OK=" + Code.OK.intValue() + ")");
        System.out.println("lastProcessedZxid after: " + tree.lastProcessedZxid);
        if (result.err == Code.OK.intValue() && tree.lastProcessedZxid == 42) {
            throw new AssertionError(
                "malformed multi-op was reported as successfully processed");
        }
    }
}
