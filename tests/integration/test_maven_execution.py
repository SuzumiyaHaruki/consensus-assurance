"""Offline Java execution and retained Surefire evidence."""
from pathlib import Path
import pytest
from consensus_assurance.adapters.runners.maven import MavenBackend
from consensus_assurance.adapters.runners.experiment import install_harness
from consensus_assurance.core.types import ExecutionStatus, Harness

@pytest.mark.real
def test_maven_offline_execution_selection_tcp_and_stale_report(tmp_path):
    import shutil
    from consensus_assurance.core.config import TargetConfig
    from consensus_assurance.adapters.runners.experiment import run_experiment, extract_events
    from consensus_assurance.adapters.runners.process import ProcessRunner
    if not all(shutil.which(name) for name in ('mvn','javac','bwrap')):pytest.skip('Maven, JDK and bubblewrap required')
    backend=MavenBackend(TargetConfig())
    if not (backend.cache/'org/junit/jupiter/junit-jupiter-engine/5.6.2/junit-jupiter-engine-5.6.2.jar').is_file():
        pytest.skip('Prepare the Maven test dependencies before this offline check')
    work=tmp_path/'workspace';work.mkdir()
    (work/'pom.xml').write_text('''<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion>
<groupId>example</groupId><artifactId>environment-check</artifactId><version>1</version>
<properties><maven.compiler.source>8</maven.compiler.source><maven.compiler.target>8</maven.compiler.target></properties>
<dependencies><dependency><groupId>org.junit.jupiter</groupId><artifactId>junit-jupiter-api</artifactId><version>5.6.2</version><scope>test</scope></dependency><dependency><groupId>org.junit.jupiter</groupId><artifactId>junit-jupiter-engine</artifactId><version>5.6.2</version><scope>test</scope></dependency></dependencies>
<build><plugins><plugin><artifactId>maven-resources-plugin</artifactId><version>3.1.0</version></plugin><plugin><artifactId>maven-compiler-plugin</artifactId><version>3.8.1</version></plugin><plugin><artifactId>maven-surefire-plugin</artifactId><version>2.22.1</version></plugin></plugins></build></project>''')
    harness=Harness(kind='java_test',source='''import org.junit.jupiter.api.Test;
public class AssuranceGeneratedTest {
  @Test public void localTcp() throws Exception {
    try (java.net.ServerSocket listener = new java.net.ServerSocket(0,1,java.net.InetAddress.getLoopbackAddress());
         java.net.Socket client = new java.net.Socket("127.0.0.1",listener.getLocalPort());
         java.net.Socket server = listener.accept()) {
      client.getOutputStream().write(73); if(server.getInputStream().read()!=73) throw new AssertionError();
    }
    System.out.println("CA_EVENT {\\"event\\":\\"roundtrip\\",\\"value\\":73}");
  }
  @Test public void unrelated() { throw new AssertionError("must not run"); }
}''',description='Synthetic localhost check',semantic_changes=[],test_names=['localTcp'])
    filename=backend.resolve_harness(harness,work,{'pom.xml':'fixture'})
    install_harness(work,filename,harness,{'pom.xml':'fixture'})
    runner=ProcessRunner(tmp_path)
    command=backend.experiment_command(harness.execution_package,filename,harness.test_names)
    check=run_experiment(runner,command,work,'synthetic-maven',60,'bwrap',adapter=backend)
    assert check.outcome=='tests_passed',Path(check.stdout).read_text()+Path(check.stderr).read_text()
    assert [t['name'] for t in check.parameters['test_selection']['observed']]==['localTcp']
    assert extract_events(check)[0]['value']==73
    (work/filename).write_text('invalid Java')
    failed=run_experiment(runner,command,work,'synthetic-maven',60,'bwrap',adapter=backend)
    assert failed.status==ExecutionStatus.ERROR and not failed.parameters['test_selection']['observed']
    assert all(Path(path).is_file() for path in check.artifacts)
