"""Synthetic context isolation via object ownership, without a familiar epoch guard."""
import pytest
import shutil,runpy
from pathlib import Path
from consensus_assurance.core.proposals import ContextScenario
from consensus_assurance.core.types import ReachabilityRequirement
from consensus_assurance.workflow.artifacts import save_bundle,validate_bundle
from consensus_assurance.adapters.runners.python import PythonBackend


@pytest.mark.real
@pytest.mark.parametrize('isolated',[True,False])
def test_old_operation_completes_on_owned_context_not_current_object(prepared,tlc,isolated):
    _,state,bundle,_=prepared;unit=state.units[0];verifier,runner=tlc
    # The paired model is grounded in a real, explicitly synthetic mechanism.
    source=Path(__file__).resolve().parents[1]/'fixtures/context_handoff.py'
    target=Path(state.snapshot.repo)/'context_handoff.py';shutil.copyfile(source,target)
    obj=runpy.run_path(str(target))['Contexts']();obj.start();original_owner=obj.pending_owner['identity'];obj.switch();obj.complete(isolated)
    assert (obj.completed_on==original_owner)==isolated
    from consensus_assurance.adapters.storage.snapshot import capture
    from consensus_assurance.workflow.materials import read_material
    from consensus_assurance.core.types import ReadRequest
    state.snapshot=capture(Path(state.snapshot.repo))
    material=read_material(Path(state.snapshot.repo),state.snapshot,ReadRequest(file='context_handoff.py',start_line=2,end_line=len(target.read_text().splitlines()),reason='Controlled callback ownership scenario'))
    state.materials.append(material)
    binding=state.bindings[0]
    binding.file=material.file;binding.start_line=material.start_line;binding.end_line=material.end_line;binding.content_digest=material.content_digest
    binding.symbol='Contexts';binding.anchor=None;binding.excerpt=material.text
    for association in binding.associations:association.source_ids=[material.id]
    state.claims[0].description='A completed callback changes only the object that accepted the operation'
    state.claims[1].description='Completion uses the retained object identity after the current context changes'
    for claim in state.claims[:2]:
        claim.source_ids=[material.id];claim.grounding.behavior_ids=[material.id]
    bundle.constraints=[]
    bundle.behavior=r'''---- MODULE Behavior ----
EXTENDS Naturals
VARIABLE current, owner, phase, completedOn
vars == <<current, owner, phase, completedOn>>
Init == /\ current = 1 /\ owner = 0 /\ phase = 0 /\ completedOn = 0
Start == /\ phase = 0 /\ owner' = current /\ phase' = 1 /\ UNCHANGED <<current,completedOn>>
Switch == /\ phase = 1 /\ current' = 2 /\ phase' = 2 /\ UNCHANGED <<owner,completedOn>>
Complete == /\ phase = 2 /\ completedOn' = OWNER /\ phase' = 3 /\ UNCHANGED <<current,owner>>
Next == Start \/ Switch \/ Complete
Started == phase = 1
Switched == phase = 2
Completed == phase = 3
Operation == 1
Obs == [value |-> phase]
====
'''.replace('OWNER','owner' if isolated else 'current')
    bundle.properties='---- MODULE Properties ----\nEXTENDS Behavior\nSafe == phase = 3 => completedOn = owner\n====\n'
    bundle.actions=['Start','Switch','Complete'];bundle.variables=['current','owner','phase','completedOn']
    bundle.reachability=[ReachabilityRequirement(id='same-operation',operator='Completed',sequence=['Started','Switched','Completed'],identity_operator='Operation',claim_ids=unit.obligation_ids,description='Same pending operation survives a context change and completes')]
    bundle.context_analysis=[ContextScenario(description='Synthetic callback retains object ownership while another object becomes current; completion is allowed without testing a term field',mode='cross_context',binding_ids=unit.binding_ids,variables=bundle.variables,actions=bundle.actions,checker_ids=['Safe'],reachability_ids=['same-operation'],excluded=['No disk recovery, network or production implementation claim; context is object identity'])]
    model=save_bundle(runner.root,state,unit,bundle,PythonBackend())
    check=verifier.check(runner,model,20)
    assert check.outcome==('holds' if isolated else 'counterexample'),check
    reach,execution=verifier.reachability(runner,model,bundle,bundle.reachability[0],20)
    assert reach.status=='reachable',execution
    assert execution.action=='reachability' and check.action=='model_check'


def test_context_prose_cannot_replace_joint_history_and_actual_actions(prepared):
    _,s,b,_=prepared;u=s.units[0]
    scenario=ContextScenario(description='Claimed crossing',mode='cross_context',binding_ids=u.binding_ids,variables=b.variables,actions=b.actions,checker_ids=[b.checker_specs()[0].invariant],reachability_ids=[],excluded=[])
    b.actions=['Next'];scenario.actions=['Next']
    b.context_analysis=[scenario]
    with pytest.raises(ValueError,match='same-history'):validate_bundle(s,u,b,PythonBackend())
    scenario.mode='local';scenario.excluded=['This arithmetic unit has one immutable instance; network contexts are outside scope']
    validate_bundle(s,u,b,PythonBackend())
    scenario.actions=['InventedAction']
    with pytest.raises(ValueError):validate_bundle(s,u,b,PythonBackend())
