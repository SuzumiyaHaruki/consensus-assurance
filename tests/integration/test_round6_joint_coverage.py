import pytest
from consensus_assurance.core.types import ReachabilityRequirement,CoveragePoint,ReviewIssue,SemanticReview,SemanticCheck
from consensus_assurance.core.proposals import ReviewReply
from consensus_assurance.workflow.artifacts import save_bundle,validate_bundle
from consensus_assurance.workflow.inquiry import review_unit,validate_review,task_context,semantic_limitations
from consensus_assurance.workflow.reviews import record_dispositions
from consensus_assurance.plugins.implementations.toy.adapter import ToyImplementation
from consensus_assurance.workflow.engine import Engine
from consensus_assurance.workflow.budget import BudgetTracker
from consensus_assurance.core.config import Config
from consensus_assurance.registry import assemble


@pytest.mark.real
@pytest.mark.parametrize('joint',[False,True])
def test_independent_points_do_not_prove_ordered_same_history(tlc,prepared,joint):
    verifier,runner=tlc;_,state,bundle,_=prepared;unit=state.units[0]
    bundle.behavior=r'''---- MODULE Behavior ----
EXTENDS Naturals
VARIABLE phase, context
vars == <<phase, context>>
Init == /\ phase = 0 /\ context = 1
Next == /\ phase = 0 /\ phase' \in {1,2} /\ UNCHANGED context
AtA == phase = 1
AtB == phase = 2
Identity == context
Obs == [value |-> phase]
====
'''
    if joint:bundle.behavior=bundle.behavior.replace("Next == /\\ phase = 0 /\\ phase' \\in {1,2} /\\ UNCHANGED context", "Next == /\\ phase < 2 /\\ phase' = phase+1 /\\ UNCHANGED context")
    bundle.properties='---- MODULE Properties ----\nEXTENDS Behavior\nSafe == phase <= 2\n====\n'
    bundle.checkers=[bundle.checker_specs()[0].model_copy(update={'invariant':'Safe'})];bundle.invariants=[];bundle.checked_claim_ids=[]
    reqs=[ReachabilityRequirement(id=name,operator=name,claim_ids=unit.obligation_ids,description='Synthetic point reachability') for name in ['AtA','AtB']]
    seq=ReachabilityRequirement(id='ordered',operator='AtB',sequence=['AtA','AtB'],identity_operator='Identity',claim_ids=unit.obligation_ids,description='Same history and identity')
    bundle.reachability=reqs+[seq]
    model=save_bundle(runner.root,state,unit,bundle,ToyImplementation())
    assert verifier.check(runner,model,20).outcome=='holds'
    results=[verifier.reachability(runner,model,bundle,r,20) for r in bundle.reachability]
    assert [r.status for r,c in results[:2]]==['reachable','reachable']
    assert results[-1][0].status==('reachable' if joint else 'unreachable'),results[-1][1]


@pytest.mark.real
def test_new_model_review_can_resolve_old_encoding_issue_after_actual_recheck(tlc,prepared):
    verifier,runner=tlc;_,state,bundle,_=prepared;unit=state.units[0]
    wrong=bundle.model_copy(deep=True);wrong.properties=wrong.properties.replace('value <= 3','value <= 2')
    old=save_bundle(runner.root,state,unit,wrong,ToyImplementation());check1=verifier.check(runner,old,20);state.checks.append(check1)
    assert check1.outcome=='counterexample'
    issue=ReviewIssue(review_id='oldreview',target_id=old.id,target_version=old.version,aspect='checker_correspondence',model_id=old.id,source_ids=state.claims[1].source_ids,explanation='The encoded bound is narrower than the actual specified bound',disposition='revision',reason='Re-encode the unchanged contract')
    state.review_issues.append(issue)
    new=save_bundle(runner.root,state,unit,bundle,ToyImplementation(),old,'Explicit controlled encoding correction')
    check2=verifier.check(runner,new,20);state.checks.append(check2);assert check2.outcome=='holds'
    cfg=Config(implementation='toy',agent_backend='mock');e=Engine(cfg,runner.root,*assemble(cfg),'');e.state=state;e.budget=BudgetTracker(cfg.budget,state)
    review_unit(e,unit,'after_search',new)
    task=next(t for t in state.inquiry_tasks if new.id in t.target_ids)
    assert issue.id in task.resolution_issue_ids
    from consensus_assurance.workflow.reviews import required_aspects
    from consensus_assurance.workflow.inquiry import objects
    available=objects(state)
    items=[SemanticCheck(target_id=id,aspect=a,status='no_issue_found',source_ids=issue.source_ids,explanation='The current encoding matches the supplied bound and was searched',alternatives='No claim or behavior change was needed',counterexample_reasoning='The prior bound excluded a permitted result') for id in task.target_ids for a in required_aspects(available[id])]
    reply=ReviewReply(items=items,limitations=[],resolves_issue_ids=[issue.id],resolution_rationale='Old and new predicates differ only in the literal matching the unchanged material; new actual TLC completed')
    validate_review(state,task,reply)
    review=SemanticReview(task_id=task.id,check_id='controlled-review',target_versions=task.target_versions,material_ids=task.material_ids,items=items,origin='mock',model_id=new.id,resolves_issue_ids=[issue.id])
    record_dispositions(state,review,reply,[])
    assert issue.resolved_by==review.id and issue.resolution_model_id==new.id
    assert issue.resolution_checks==[check2.id]
    assert not any('Open review issue' in text for text in semantic_limitations(state,new))


def test_model_goal_check_does_not_require_implementation_observations(prepared,tmp_path):
    _,state,bundle,_=prepared;u=state.units[0];u.goal_observable=True
    bundle.checkers=bundle.checker_specs()+[bundle.checker_specs()[0].model_copy(update={'invariant':'GoalSafe','claim_id':u.goal_ids[0]})]
    bundle.invariants=[];bundle.checked_claim_ids=[]
    bundle.properties=bundle.properties.replace('====================================================','GoalSafe == Safe\n====================================================')
    if 'GoalSafe ==' not in bundle.properties:
        lines=bundle.properties.splitlines();lines.insert(-1,'GoalSafe == Safe');bundle.properties='\n'.join(lines)
    assert not bundle.goal_observations
    validate_bundle(state,u,bundle,ToyImplementation())
