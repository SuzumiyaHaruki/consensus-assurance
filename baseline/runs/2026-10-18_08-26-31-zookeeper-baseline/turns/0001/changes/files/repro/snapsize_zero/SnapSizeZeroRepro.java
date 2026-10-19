import org.apache.zookeeper.server.SyncRequestProcessor;
import org.apache.zookeeper.server.ZooKeeperServer;

/**
 * Repro for zookeeper.snapSizeLimitInKb=0, which the documentation and
 * ZooKeeperServer#getSnapSizeInBytes describe as disabling the size-based
 * snapshot trigger.
 *
 * Run with -Dzookeeper.snapSizeLimitInKb=0 so the static field in
 * SyncRequestProcessor is initialized from the documented setting.
 */
public class SnapSizeZeroRepro {
    public static void main(String[] args) throws Exception {
        if (!"0".equals(System.getProperty("zookeeper.snapSizeLimitInKb"))) {
            throw new IllegalStateException("run with -Dzookeeper.snapSizeLimitInKb=0");
        }

        ZooKeeperServer server = new ZooKeeperServer();
        SyncRequestProcessor processor = new SyncRequestProcessor(server, null);
        Thread t = new Thread(processor, "sync-repro");
        t.start();
        t.join(1000);

        System.out.println("sync thread alive after startup: " + t.isAlive());
        if (!t.isAlive()) {
            throw new AssertionError(
                "SyncRequestProcessor exited during startup with snapshot size disabled");
        }

        processor.shutdown();
        t.join(5000);
    }
}
