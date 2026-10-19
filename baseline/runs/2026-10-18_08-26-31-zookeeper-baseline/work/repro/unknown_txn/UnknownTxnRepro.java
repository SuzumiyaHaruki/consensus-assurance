import org.apache.zookeeper.KeeperException.Code;
import org.apache.zookeeper.server.DataTree;
import org.apache.zookeeper.txn.TxnHeader;

/**
 * An unknown top-level txn type must not be silently treated as successfully
 * applied while moving lastProcessedZxid forward.
 */
public class UnknownTxnRepro {
    public static void main(String[] args) {
        DataTree tree = new DataTree();
        TxnHeader hdr = new TxnHeader(1, 0, 43, 43, 999);
        DataTree.ProcessTxnResult result = tree.processTxn(hdr, null);
        System.out.println("result error: " + result.err + " (OK=" + Code.OK.intValue() + ")");
        System.out.println("lastProcessedZxid after: " + tree.lastProcessedZxid);
        if (result.err == Code.OK.intValue() && tree.lastProcessedZxid == 43) {
            throw new AssertionError(
                "unknown top-level txn type was silently accepted and advanced the watermark");
        }
    }
}
