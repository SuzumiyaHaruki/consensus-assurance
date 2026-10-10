"""Scoped review follow-ups, handoffs and durable semantic mutations."""
import json
import shutil
import pytest
from consensus_assurance.core.config import Config

from consensus_assurance.workflow.transactions import commit_graph
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.workflow.budget import BudgetTracker
from consensus_assurance.registry import assemble
from consensus_assurance.adapters.storage.files import Store


def engine_for(tmp_path,state):
    cfg=Config(execution_backend='python',agent_backend='mock',allow_experiments=False)
    engine=Engine(cfg,tmp_path/'engine',*assemble(cfg))
    engine.state=state;engine.budget=BudgetTracker(cfg.budget,state)
    shutil.copytree(state.snapshot.repo,engine.root/'source')
    return engine


@pytest.mark.parametrize('interrupt',[False,True])
def test_semantic_transaction_failure_and_recovery_are_atomic(tmp_path,prepared,interrupt):
    _, state, _ = prepared;engine=engine_for(tmp_path,state);engine.checkpoint('initial')
    before=state.model_dump(mode='json')
    def invalid(proxy):
        proxy.state.claims[1].description='must never escape failed validation'
        raise ValueError('Injected validation failure')
    with pytest.raises(ValueError):commit_graph(engine,'invalid',{'operation':'bad'},invalid)
    assert state.model_dump(mode='json')==before
    def change(proxy):
        proxy.state.claims[1].version+=1
        proxy.state.current_submission={'phase':'accepted','operation_id':'change'}
    if interrupt:
        def crash(key):raise RuntimeError('Interrupted between manifest and state')
        engine.graph_commit_hook=crash
        with pytest.raises(RuntimeError):commit_graph(engine,'change',{'operation':'one'},change)
        assert state.claims[1].version==1
        engine.state=Store(engine.root).load();engine.budget=BudgetTracker(engine.config.budget,engine.state)
        engine.graph_commit_hook=lambda key:None
    commit_graph(engine,'change',{'operation':'one'},change)
    commit_graph(engine,'change',{'operation':'one'},change)
    assert engine.state.claims[1].version==2 and engine.state.current_submission['operation_id']=='change'
    assert 'change' in Store(engine.root).load().applied_operations


from consensus_assurance.core.diagnostics import DiagnosticError


def test_review_target_inheritance_and_contract_diagnostics(tmp_path,prepared):
    from consensus_assurance.core.submissions import ResultReview,AuditSubmission
    from consensus_assurance.core.types import SemanticCheck
    from consensus_assurance.workflow.direct_checks import save_plan
    from consensus_assurance.workflow.review_contract import validate_contract,target_contract
    from regression_support import setup
    engine,unit,plan=setup(tmp_path,prepared);artifact=save_plan(engine,unit,plan,'contract')
    raw=dict(action='research', review=dict(artifact_id=artifact.id,
            review_items=[dict(
        aspect='checker_correspondence',status='no_issue_found',source_ids=target_contract(engine.state,artifact)['required_material_ids'],rationale='The selected fixed local oracle agrees with its cited scope')]),
            rationale='Controlled review contract')
    product=ResultReview.model_validate(raw['review'])
    assert product.review_items[0].target_id==artifact.id
    validate_contract(engine.state,artifact.id,product.review_items)
    for fields,code in (({'target_id':plan.claim_id},'review_unknown_target'),
        ({'counterevidence':['The endpoint is disputed']},'review_contradictory_judgment'),
        ({'source_ids':['unacquired']},'review_unknown_source')):
        item=product.review_items[0].model_copy(update=fields)
        with pytest.raises(DiagnosticError) as caught:validate_contract(engine.state,artifact.id,[item])
        assert code in {d.code for d in caught.value.diagnostics}
    with pytest.raises(ValueError):SemanticCheck.model_validate(raw['review']['review_items'][0])
    assert 'target_id' not in AuditSubmission.model_json_schema()['$defs']['ArtifactReviewItem']['required']

    schema=AuditSubmission.model_json_schema()
    assert not {'challenged_components','out_of_scope_checker_ids'} & schema['$defs']['ArtifactReviewItem']['properties'].keys()
    assert 'ConditionDisposition' not in schema['$defs']
    assert set(schema['$defs']['IssueResolution']['properties'])=={'issue_id','source_ids','executions','rationale'}
    negative=product.review_items[0].model_copy(update={'status':'revision_needed','counterevidence':['Missing independent identity']})
    validate_contract(engine.state,artifact.id,[negative])
