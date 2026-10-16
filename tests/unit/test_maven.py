"""Maven selection and completed-case evidence, without remote model calls."""
from pathlib import Path
import pytest
from consensus_assurance.adapters.runners.maven import MavenBackend
from consensus_assurance.core.types import CheckRun, ExecutionStatus, Harness
from consensus_assurance.adapters.runners.experiment import install_harness


@pytest.mark.parametrize('result,exit_code,status,outcome', [
    ('<testcase classname="AssuranceGeneratedTest" name="measured"/>',0,'completed','tests_passed'),
    ('<testcase classname="AssuranceGeneratedTest" name="measured"><failure/></testcase>',1,'completed','tests_failed'),
    ('<testcase classname="AssuranceGeneratedTest" name="measured"><skipped/></testcase>',0,'completed','not_applicable'),
    ('',0,'completed','not_applicable'), ('',1,'completed','unknown'),
    ('<testcase classname="AssuranceGeneratedTest" name="measured"/>',None,'timeout','unknown'),
])
def test_maven_requires_actual_cases_and_retains_raw_reports(tmp_path,result,exit_code,status,outcome):
    work=tmp_path/'work'; reports=work/'module/target/surefire-reports'; reports.mkdir(parents=True)
    report=reports/'TEST-AssuranceGeneratedTest.xml'; report.write_text('<testsuite>'+result+'</testsuite>')
    log=tmp_path/'logs/stdout.log'; log.parent.mkdir(); log.write_text('raw Maven output')
    check=CheckRun(action='experiment',cwd=str(work),snapshot_id='synthetic',stdout=str(log),
        command=['mvn','-pl','./module','-Dtest=AssuranceGeneratedTest#measured'],exit_code=exit_code,status=status)
    backend=object.__new__(MavenBackend)
    backend.parse_test_result(check,'raw Maven output')
    assert check.outcome==outcome
    assert check.parameters['test_selection']['unobserved']==([] if result else ['measured'])
    assert Path(check.artifacts[0]).read_bytes()==report.read_bytes()
    if exit_code==1 and not result:assert check.status==ExecutionStatus.ERROR


def test_maven_selection_and_build_inputs_cannot_escape(tmp_path):
    backend=object.__new__(MavenBackend)
    backend.package='./module';backend.harness_filename='module/src/test/java/AssuranceGeneratedTest.java';backend.maven=Path('/opt/maven/bin/mvn')
    (tmp_path/'module').mkdir();(tmp_path/'module/pom.xml').write_text('<project/>')
    harness=Harness(kind='java_test',source='class AssuranceGeneratedTest {}',description='Synthetic',semantic_changes=[],test_names=['measured'])
    files={'module/pom.xml':'captured'}
    filename=backend.resolve_harness(harness,tmp_path,files)
    command=backend.experiment_command(harness.execution_package,filename,harness.test_names)
    assert '-Dtest=AssuranceGeneratedTest#measured' in command and '-am' in command and '-o' in command
    for names in (['*'],['measured,Other'],['--flag'],['measured','measured']):
        with pytest.raises(ValueError):backend.experiment_command(harness.execution_package,filename,names)
    for name in ('pom.xml','module/pom.xml','.mvn/extensions.xml'):
        with pytest.raises(ValueError,match='dependency definitions'):
            install_harness(tmp_path,filename,harness.model_copy(update={'files':{name:'changed'}}),files,write=False)
    with pytest.raises(ValueError):backend.destination('./module','module/src/test/java/../Escape.java')


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
