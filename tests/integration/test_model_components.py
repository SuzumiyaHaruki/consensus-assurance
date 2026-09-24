"""Staged artifacts retain all model evidence boundaries without placeholder harnesses."""
import pytest
from consensus_assurance.core.proposals import ModelDraft
from consensus_assurance.workflow.artifacts import save_bundle,load_model
from consensus_assurance.workflow.modeling import validate_technical_repair
from consensus_assurance.adapters.runners.python import PythonBackend


def draft_of(bundle):
    data=bundle.model_dump(mode='json',exclude={'harness','observation'})
    return ModelDraft(**data,pending_work=[{'component':'harness','reason':'Assembly source required'},{'component':'observation','reason':'No real observations collected yet'}])


@pytest.mark.real
@pytest.mark.parametrize('negative',[False,True])
def test_model_only_tool_result_is_not_a_calibrated_implementation(prepared,tlc,negative):
    _,state,bundle,_=prepared;verifier,runner=tlc;draft=draft_of(bundle)
    if negative:draft.properties=draft.properties.replace('value <= 3','value <= 2')
    model=save_bundle(runner.root,state,state.units[0],draft,None)
    assert model.stage=='model_only' and not model.harness_path and not model.mapping_path
    assert isinstance(load_model(model),ModelDraft)
    syntax=verifier.syntax(runner,model,20)
    assert syntax.status.value=='completed' and syntax.outcome=='not_applicable'
    result=verifier.check(runner,model,20)
    assert result.outcome==('counterexample' if negative else 'holds')
    assert not state.calibrations and not state.evidence


def test_missing_tools_and_core_dependencies_never_complete_a_draft(tmp_path,prepared):
    from consensus_assurance.adapters.verifiers.tlc import TLCVerifier
    from consensus_assurance.adapters.runners.process import ProcessRunner
    _,state,bundle,_=prepared;draft=draft_of(bundle);impl=PythonBackend()
    model=save_bundle(tmp_path/'models-run',state,state.units[0],draft,impl)
    missing=TLCVerifier(None).syntax(ProcessRunner(tmp_path/'runner'),model,1)
    assert missing.status.value=='tool_missing' and missing.outcome=='unknown'
    from consensus_assurance.core.proposals import ComponentWork
    draft.pending_work.append(ComponentWork(component='behavior',reason='Producer source is unavailable'))
    with pytest.raises(ValueError,match='Unfinished core'):
        save_bundle(tmp_path/'unfinished',state,state.units[0],draft,None)
    assert len(state.models)==1 and not (tmp_path/'unfinished').exists()
    assert not state.checks


def test_stage_schemas_and_technical_repairs_do_not_authorize_semantic_edits(prepared):
    _,state,bundle,_=prepared;draft=draft_of(bundle)
    changed=draft.model_copy(deep=True);changed.properties=changed.properties.replace('value <= 3','TRUE')
    with pytest.raises(ValueError,match='property text'):
        validate_technical_repair(draft,changed,'search')


def test_tlc_help_exit_is_capability_information_not_a_property_verdict(tmp_path):
    from consensus_assurance.core.types import CheckRun,ExecutionStatus
    from consensus_assurance.adapters.verifiers.tlc import TLCVerifier
    jar=tmp_path/'controlled.jar';jar.write_bytes(b'Controlled capability fixture; never executed')
    class Runner:
        root=tmp_path
        def run(self,command,cwd,action,snapshot,timeout):
            log=tmp_path/(action+'.log');log.write_text('openjdk version "17"' if action=='java_probe' else 'TLC2 Version 2.19\nUsage: TLC -help\n')
            return CheckRun(action=action,cwd=str(cwd),snapshot_id=snapshot,status=ExecutionStatus.COMPLETED,
                exit_code=0 if action=='java_probe' else 1,stdout=str(log))
    result=TLCVerifier(str(jar)).probe(Runner())
    assert result['available'] and all(c.outcome=='unknown' for c in result['checks'])
    assert not any(c.action=='model_check' for c in result['checks'])
    from consensus_assurance.reporting.chinese import execution_summary
    assert '工具可用' in execution_summary(result['checks'][-1])[1]
    syntax=result['checks'][-1].model_copy(update={'action':'model_syntax','outcome':'not_applicable','exit_code':0})
    assert '未检查性质' in execution_summary(syntax)[2]
    from types import SimpleNamespace
    verifier=TLCVerifier(str(jar));verifier.available=True
    # A successful subprocess exit with unrelated output is not a TLA diagnostic.
    failed=verifier.syntax(Runner(),SimpleNamespace(path=str(tmp_path/'Properties.tla'),snapshot_id='fixture',id='model',artifact_digests={}),1)
    assert failed.status==ExecutionStatus.ERROR and failed.reason.startswith('SANY execution failed')
