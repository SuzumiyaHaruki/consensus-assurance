# Reproduction Notes

The captured source is unchanged. From the run working directory:

```bash
mvn -o -q -pl zookeeper-server -am -DskipTests -Dcheckstyle.skip=true \
  -Dspotbugs.skip=true -Drat.skip=true test-compile

CP="zookeeper-server/target/classes:zookeeper-jute/target/classes:$(find /home/nitro/.m2/repository -name '*.jar' | paste -sd: -)"
```

Each finding's report section gives the source file, expected behavior, observed output,
and the exact `javac`/`java` command. The reproduction directories contain their source,
compiled classes, and `output.txt` files.  Do not depend on the run's `.runtime` directory;
it is disposable and is not retained.

Some network-facing repros (for example the `Leader` constructor case) must run through the
provided isolated execution environment; the report notes this where applicable.
