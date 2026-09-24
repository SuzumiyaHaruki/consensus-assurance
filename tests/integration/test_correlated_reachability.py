import pytest
from consensus_assurance.core.types import ReachabilityRequirement,ReviewIssue,SemanticReview,SemanticCheck
from consensus_assurance.core.proposals import ReviewReply
from consensus_assurance.workflow.artifacts import save_bundle,validate_bundle

from consensus_assurance.adapters.runners.python import PythonBackend
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
    model=save_bundle(runner.root,state,unit,bundle,PythonBackend())
    assert verifier.check(runner,model,20).outcome=='holds'
    results=[verifier.reachability(runner,model,bundle,r,20) for r in bundle.reachability]
    assert [r.status for r,c in results[:2]]==['reachable','reachable']
    assert results[-1][0].status==('reachable' if joint else 'unreachable'),results[-1][1]
