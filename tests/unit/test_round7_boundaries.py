"""Project-level failure reproductions before interface and reading policy changes."""
import pytest
from consensus_assurance.core.types import InquiryTask,SemanticCheck
from consensus_assurance.core.proposals import ReviewReply
from consensus_assurance.core.config import Budget
from consensus_assurance.workflow.inquiry import validate_review
from consensus_assurance.workflow.materials import ReadingPlan,add_reads


def test_review_interface_error_is_actionable(prepared):
    _,state,_,_=prepared;b=state.bindings[0]
    task=InquiryTask(kind='review',reason='Check binding usage',trigger='test',target_ids=[b.id],target_versions={b.id:b.version})
    item=SemanticCheck(target_id=b.id,aspect='applicability',status='disputed',source_ids=[state.materials[0].id],explanation='The intended usage is unclear',alternatives='Inspect the actual consumer',counterexample_reasoning='Position alone does not establish the responsibility')
    before=state.model_dump()
    with pytest.raises(ValueError) as caught:validate_review(state,task,ReviewReply(items=[item],limitations=[]))
    assert getattr(caught.value,'diagnostics',None)
    assert caught.value.diagnostics[0].paths
    assert state.model_dump()==before


def test_read_batch_does_not_partially_commit_before_invalid_range(prepared):
    repo,state,_,_=prepared;state.materials=[];before=state.model_dump()
    plan=ReadingPlan(requests=[{'file':'limits.py','start_line':1,'end_line':2,'reason':'Actual small input'},{'file':'counter.py','start_line':1,'end_line':999,'reason':'Invalid proposed bound'}],rationale='Read dependencies')
    with pytest.raises(ValueError):add_reads(state,repo,plan,Budget())
    assert state.model_dump()==before


def test_overlap_uses_unique_material_accounting(prepared):
    from consensus_assurance.workflow import materials
    repo,state,_,_=prepared;state.materials=[]
    for a,b in [(1,5),(4,8),(1,8)]:add_reads(state,repo,ReadingPlan(requests=[{'file':'counter.py','start_line':a,'end_line':b,'reason':'Inspect actual range'}],rationale='Read'),Budget())
    assert hasattr(materials,'material_usage')
    usage=materials.material_usage(state)
    lines=(repo/'counter.py').read_text().splitlines()
    assert usage['unique_chars']==sum(len(line)+1 for line in lines[:8])
    assert usage['unique_chunks']==1


def test_breadth_reading_preserves_local_dependency_capacity(prepared):
    from consensus_assurance.workflow import materials
    assert hasattr(materials,'material_allowance')
    _,state,_,_=prepared;state.materials=[]
    budget=Budget(material_chars=1000)
    allowance=materials.material_allowance(state,budget,'breadth')
    assert 0<allowance['available_chars']<1000
    assert allowance['reserved_for_other_chars']>0
