import java.lang.reflect.Field;
import java.util.concurrent.TimeUnit;
import org.apache.zookeeper.server.admin.Commands;
import org.apache.zookeeper.server.util.RateLimiter;

/**
 * Reproduction for the admin `snapshot` command rate-limit unit defect.
 *
 * Commands.SnapshotCommand builds its RateLimiter with TimeUnit.MICROSECONDS
 * while the property it reads is zookeeper.admin.rateLimiterIntervalInMS
 * (default 300000) and zookeeperAdmin.md documents "Defaults to 5 mins".
 * RateLimiter converts the interval with unit.toMillis(interval), so the
 * effective interval is 300000 microseconds = 300 ms instead of 300000 ms.
 *
 * RestoreCommand (same property, same default) uses TimeUnit.MILLISECONDS and
 * therefore does honour the documented 5 minutes.
 */
public class SnapshotRateLimitCheck {

    private static long intervalInMsOf(Object command) throws Exception {
        Field f = command.getClass().getDeclaredField("rateLimiter");
        f.setAccessible(true);
        RateLimiter rl = (RateLimiter) f.get(command);
        Field interval = RateLimiter.class.getDeclaredField("intervalInMs");
        interval.setAccessible(true);
        return (Long) interval.get(rl);
    }

    public static void main(String[] args) throws Exception {
        System.out.println("zookeeper.admin.rateLimiterIntervalInMS = "
                + System.getProperty("zookeeper.admin.rateLimiterIntervalInMS", "300000 (default)"));

        long snapshotInterval = intervalInMsOf(new Commands.SnapshotCommand());
        long restoreInterval = intervalInMsOf(new Commands.RestoreCommand());

        System.out.println("SnapshotCommand rate limiter intervalInMs = " + snapshotInterval);
        System.out.println("RestoreCommand  rate limiter intervalInMs = " + restoreInterval);

        System.out.println("same RateLimiter parameter as RestoreCommand? "
                + (snapshotInterval == restoreInterval));
        System.out.println("documented (5 min) interval honoured by snapshot? "
                + (snapshotInterval == TimeUnit.MINUTES.toMillis(5)));

        // Behavioural check: with the snapshot limiter a second call is accepted
        // again after ~300 ms, not after 5 minutes.
        RateLimiter snapshotLimiter = new RateLimiter(1, 300000, TimeUnit.MICROSECONDS);
        boolean first = snapshotLimiter.allow();
        boolean secondImmediately = snapshotLimiter.allow();
        Thread.sleep(400);
        boolean secondAfter400ms = snapshotLimiter.allow();
        System.out.println("snapshot limiter: first=" + first + " secondImmediately="
                + secondImmediately + " secondAfter400ms=" + secondAfter400ms);
    }
}
