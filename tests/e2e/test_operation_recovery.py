"""Controller-level semantic commit recovery using the real task-aware local fixture."""
import pytest
from coverage_support import setup_workflow as setup
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.adapters.storage.files import Store


@pytest.mark.parametrize('operation',['derive','inquiry'])
def test_interrupted_semantic_commit_resumes_without_duplicate_revision(tmp_path,prepared,operation):
    repo,config,root,args=setup(tmp_path,prepared,wrong=True)
    class Interrupted(Engine):
        def graph_commit_hook(self,key):
            if key.startswith(operation+'-'):
                raise RuntimeError('Injected interruption after durable semantic operation')
    with pytest.raises(RuntimeError):Interrupted(config,root,*args).start(repo)
    before=Store(root).load()
    prepared_files=list((root/'graph-commits').glob(operation+'-*.json'))
    assert prepared_files
    count=before.usage['agent_calls']
    state=Engine(config,root,*args).resume()
    assert next(c for c in state.claims if c.id=='delivery_obligation').version==2
    assert len([r for r in state.revisions if r.kind=='F2' and r.status=='applied'])==1
    assert all(t.status=='completed' or t.stop_reason for t in state.inquiry_tasks)
    assert state.usage['agent_calls']>=count
    assert all(p.stem in state.applied_operations for p in prepared_files)
