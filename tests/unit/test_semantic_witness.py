import pytest
from consensus_assurance.core.proposals import ConsequenceObservation,ConsequenceWitnessEvent,EncodingRevision
from consensus_assurance.workflow.observations import consequence_witness_limitations
from consensus_assurance.workflow.encoding import validate_encoding
from consensus_assurance.workflow.artifacts import save_bundle
from consensus_assurance.adapters.runners.python import PythonBackend






@pytest.mark.parametrize('change',['valid','constant','behavior','meaning'])
def test_encoding_correction_preserves_meaning_and_behavior(tmp_path,prepared,change):
    _,state,bundle,_=prepared;u=state.units[0]
    old=save_bundle(tmp_path,state,u,bundle,PythonBackend())
    new=bundle.model_copy(deep=True)
    new.properties=new.properties.replace('value <= 3','value < 4')
    if change=='constant':new.properties='---- MODULE Properties ----\nEXTENDS Behavior\nSafe == TRUE\n====\n'
    if change=='behavior':new.behavior=new.behavior.replace('value < 3','value < 2')
    if change=='meaning':new.scope.assumptions.append('Exclude permitted delayed messages')
    revision=EncodingRevision(old_model_id=old.id,source_ids=state.claims[1].source_ids,rationale='The same source bound is expressed using the equivalent strict integer comparison')
    if change=='valid':validate_encoding(state,old,bundle,new,revision)
    else:
        with pytest.raises(ValueError):validate_encoding(state,old,bundle,new,revision)


def test_feedback_rejects_invalid_bundle_before_commit(prepared):
    from consensus_assurance.core.proposals import Feedback
    from consensus_assurance.workflow.investigation import validate_feedback
    _,state,bundle,_=prepared;unit=state.units[0]
    invalid=bundle.model_copy(deep=True)
    invalid.checked_claim_ids=['absent-obligation']
    feedback=Feedback(kind='F1',rationale='Recheck the actual mapping',evidence_ids=[],target_ids=[],relation_ids=[],
        new_basis='',graph=None,bundle=invalid)
    with pytest.raises(ValueError,match='Checker claims'):
        validate_feedback(state,unit,bundle,feedback,PythonBackend(),'F1')
    assert not state.revisions


@pytest.mark.parametrize('variation',['harness','unrelated','no_check'])
def test_old_issue_cannot_be_cleared_by_unrelated_or_unexecuted_model(tmp_path,prepared,variation):
    from consensus_assurance.core.types import ReviewIssue,InquiryTask,SemanticCheck
    from consensus_assurance.core.proposals import ReviewReply
    from consensus_assurance.workflow.reviews import validate_resolutions
    _,state,bundle,_=prepared;u=state.units[0];old=save_bundle(tmp_path,state,u,bundle,PythonBackend())
    updated=bundle.model_copy(deep=True)
    if variation=='harness':updated.harness.source+='\n# Formatting\n'
    else:updated.properties=updated.properties.replace('value <= 3','value < 4')
    new=save_bundle(tmp_path,state,u,updated,PythonBackend(),old if variation!='unrelated' else None)
    issue=ReviewIssue(review_id='oldreview',target_id=old.id,target_version=old.version,aspect='checker_correspondence',model_id=old.id,source_ids=state.claims[1].source_ids,explanation='The checker needs a correspondence investigation',disposition='blocked',reason='Actual correction and execution required')
    state.review_issues.append(issue)
    task=InquiryTask(kind='review',reason='Review the new artifact',trigger='test',target_ids=[new.id],target_versions={new.id:new.version},model_id=new.id,resolution_issue_ids=[issue.id])
    item=SemanticCheck(target_id=new.id,aspect='checker_correspondence',status='no_issue_found',source_ids=issue.source_ids,rationale='Candidate explanation' + "\n" + 'Alternative encodings' + "\n" + 'A claim of correctness does not replace actual rechecking')
    reply=ReviewReply(items=[item],resolves_issue_ids=[issue.id],resolution_rationale='Attempt to resolve without sufficient related execution',limitations=[])
    with pytest.raises(ValueError):validate_resolutions(state,task,reply)
    assert issue.resolved_by is None


@pytest.mark.parametrize('variation',['same','context','operation','unrelated_event','future'])
def test_R6_consequence_requires_correlated_participants(variation):
    from consensus_assurance.core.types import Grounding
    mapping=ConsequenceObservation(claim_id='broader_obligation',identity_fields=['operation','context'],required_participants=['a','b'],required_events=['accepted','returned'],binding_ids=['observed'],grounding=Grounding(),witness_events=[ConsequenceWitnessEvent(participant='a',event='accepted'),ConsequenceWitnessEvent(participant='b',event='returned')])
    events=[{'participant':'a','event':'accepted','operation':'x','context':1},{'participant':'b','event':'returned','operation':'x','context':1}];index=1
    if variation=='context':events[0]['context']=2
    if variation=='operation':events[0]['operation']='y'
    if variation=='unrelated_event':events[0]['event']='unrelated'
    if variation=='future':events.reverse();index=0
    assert bool(consequence_witness_limitations(mapping,events,[index])) is (variation!='same')
