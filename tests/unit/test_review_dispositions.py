"""The existing operation-identity transaction stays atomic across the ownership change."""
import pytest
from audit_support import engine_for, first
from consensus_assurance.workflow.transactions import commit_update
from consensus_assurance.workflow.audit import Inputs, prepare_submission
from consensus_assurance.core.submissions import AuditSubmission


@pytest.mark.parametrize('interrupt',[False,True])
def test_semantic_transaction_failure_and_recovery_are_atomic(tmp_path,interrupt):
    e,repo=engine_for(tmp_path,[]);e.start(repo,plan_only=True)
    draft=e.root/'draft';draft.mkdir()
    submission=AuditSubmission.model_validate(first({})[0])
    def accept(proxy):return prepare_submission(proxy,submission,Inputs(draft),'op')()
    def hook(key):
        if interrupt:raise KeyboardInterrupt('After durable preparation')
    e.semantic_commit_hook=hook
    if interrupt:
        with pytest.raises(KeyboardInterrupt):commit_update(e,'op',submission.model_dump(mode='json'),accept)
        assert not e.state.investigations
        assert (e.root/'semantic-commits/op.json').is_file()
    e.semantic_commit_hook=lambda key:None
    commit_update(e,'op',submission.model_dump(mode='json'),accept)
    assert len(e.state.investigations)==1
    commit_update(e,'op',submission.model_dump(mode='json'),accept)
    assert len(e.state.investigations)==1
    with pytest.raises(ValueError,match='identity reused'):commit_update(e,'op',{},accept)


def test_invalid_whole_update_never_partially_commits(tmp_path):
    e,repo=engine_for(tmp_path,[]);e.start(repo,plan_only=True)
    draft=e.root/'draft';draft.mkdir()
    sub=first({})[0];sub['gaps']=[dict(investigation_id='missing',question='Invalid reference')]
    product=AuditSubmission.model_validate(sub)
    before=e.state.model_dump(mode='json')
    with pytest.raises(ValueError):
        commit_update(e,'bad',sub,lambda p:prepare_submission(p,product,Inputs(draft),'bad')())
    assert e.state.model_dump(mode='json')==before
    assert not (e.root/'semantic-commits/bad.json').exists()
