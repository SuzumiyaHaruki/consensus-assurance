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
