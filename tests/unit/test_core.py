import pytest
from consensus_assurance.core.types import Analysis, CheckRun, ExecutionStatus
from consensus_assurance.core.config import Budget
from consensus_assurance.workflow.budget import BudgetTracker, BudgetExhausted
from consensus_assurance.adapters.storage.snapshot import capture
from consensus_assurance.adapters.storage.files import Store
from consensus_assurance.workflow.engine import FRAMEWORK_REVISION


def test_execution_transition_and_budget_limits(tmp_path):
    c=CheckRun(action='test',cwd=str(tmp_path),snapshot_id='source')
    with pytest.raises(ValueError):c.transition(ExecutionStatus.COMPLETED)
    c.transition(ExecutionStatus.RUNNING);c.transition(ExecutionStatus.COMPLETED)
    state=Analysis(mode='mock',framework_revision=FRAMEWORK_REVISION,config={},snapshot=capture(tmp_path))
    tracker=BudgetTracker(Budget(agent_calls=1,experiments=0,total_seconds=10),state)
    tracker.take('agent_calls')
    with pytest.raises(BudgetExhausted):tracker.take('agent_calls')
    with pytest.raises(BudgetExhausted):tracker.take('experiments')
    assert tracker.remaining()>0
    store=Store(tmp_path/'saved');store.save(state,'test')
    assert store.load()==state


@pytest.mark.parametrize('transitive',[False,True])
def test_comparison_diagnostic_identifies_actual_conflicting_chain(transitive):
    from types import SimpleNamespace
    from consensus_assurance.core.types import ExperimentBasis
    from consensus_assurance.core.diagnostics import DiagnosticError
    from consensus_assurance.workflow.experiments import validate_basis
    prerequisites=[dict(alias='plain',event='admitted'),dict(alias='unrelated',event='result')]
    if transitive:
        prerequisites.extend([
            dict(alias='producer_a',event='result'),dict(alias='producer_b',event='result'),
            dict(alias='middle',event='prepared',conditions=[
                dict(field='operation',reference='producer_a.operation'),
                dict(field='operation',reference='producer_b.operation')]),
            dict(alias='start',event='started',conditions=[dict(field='operation',reference='middle.operation')])])
    else:
        prerequisites.append(dict(alias='start',event='result'))
    basis=ExperimentBasis(harness={'kind':'test','source':'fixture','prerequisites':prerequisites},
        source_ids=['source'],scope={'description':'One local call'},prefix='Use observed producers.',
        comparisons=[dict(event='other',admission_alias='plain',identity_fields=['operation'],
                          assertion=dict(field='value',value=True)),
                     dict(event='result',admission_alias='start',identity_fields=['operation'],
                          assertion=dict(field='value',value=True))])
    with pytest.raises(DiagnosticError) as rejected:
        validate_basis(SimpleNamespace(materials=[SimpleNamespace(id='source')],knowledge=[]),
                       basis,SimpleNamespace(harness_kind='test'))
    diagnostic,=rejected.value.diagnostics
    assert diagnostic.paths==['/experiment/comparisons/1']
    assert diagnostic.details==dict(comparison_index=1,event='result',admission_alias='start',
        conflicting_aliases=['producer_a','producer_b'] if transitive else ['start'],
        prerequisite_aliases=['producer_a','producer_b','middle','start'] if transitive else ['start'])


@pytest.mark.parametrize('change',[
    {'assertion':dict(field='operation',value=True)},
    {'applicability_conditions':[dict(field='value',value=True)]},
    {'antecedent':dict(field='operation',value=True)},
    {'admission_alias':'missing'}])
def test_other_comparison_failures_keep_explicit_comparison_context(change):
    from types import SimpleNamespace
    from consensus_assurance.core.types import ExperimentBasis
    from consensus_assurance.core.diagnostics import DiagnosticError
    from consensus_assurance.workflow.experiments import validate_basis
    comparison=dict(event='result',admission_alias='start',identity_fields=['operation'],
                    assertion=dict(field='value',value=True))
    basis=ExperimentBasis(harness={'kind':'test','source':'fixture',
        'prerequisites':[dict(alias='start',event='admitted')]},source_ids=['source'],
        scope={'description':'One local call'},prefix='Use observed producers.',
        comparisons=[comparison,{**comparison,**change}])
    with pytest.raises(DiagnosticError) as rejected:
        validate_basis(SimpleNamespace(materials=[SimpleNamespace(id='source')],knowledge=[]),
                       basis,SimpleNamespace(harness_kind='test'))
    diagnostic,=rejected.value.diagnostics
    assert diagnostic.paths==['/experiment/comparisons/1']
    assert diagnostic.details==dict(comparison_index=1,event='result',
                                   admission_alias=change.get('admission_alias','start'))


def test_submitted_input_diagnostics_preserve_path_boundaries(tmp_path):
    from consensus_assurance.workflow.audit import Inputs
    draft=tmp_path/'draft';draft.mkdir()
    outside=tmp_path/'outside.py';outside.write_text('outside fixture')
    (draft/'linked.py').symlink_to(outside)
    (draft/'linked-dir').symlink_to(tmp_path,target_is_directory=True)
    inputs=Inputs(draft)
    for name in ('../outside.py',str(outside),'linked.py','linked-dir/outside.py','missing.py'):
        with pytest.raises(ValueError):inputs.read(name)
    assert inputs.contents=={}
    (draft/'check.py').write_text('fixture')
    assert inputs.read('check.py') == 'fixture'
