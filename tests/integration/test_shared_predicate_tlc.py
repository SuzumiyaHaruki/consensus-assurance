import pytest
from consensus_assurance.core.proposals import ObservableProperty, Comparison, ObservationMap, FieldProjection
from consensus_assurance.workflow.artifacts import save_bundle
from consensus_assurance.adapters.runners.python import PythonBackend
from consensus_assurance.workflow.observations import monitor_support
from consensus_assurance.core.proposals import EventMonitor
from consensus_assurance.core.types import Grounding


@pytest.mark.real
@pytest.mark.parametrize('conflict',[False,True])
def test_shared_history_predicate_agrees_with_monitor_on_real_TLC(tlc,prepared,conflict):
    verifier,runner=tlc
    _,state,bundle,_=prepared
    prop=ObservableProperty(checker_id='Safe',kind='stable_support',trigger=Comparison(field='effective',value=True),assertion=Comparison(field='object'),identity_fields=['participant','context'],history_field='state.history',description='Synthetic finite two-event support history')
    bundle.observable_properties=[prop]
    bundle.properties='GENERATE_FROM_OBSERVABLE_PROPERTIES'
    bundle.observation=ObservationMap(fields=[FieldProjection(model_field='history',raw_field='history')],required_events=[],description='Complete finite synthetic history')
    obj='b' if conflict else 'a'
    bundle.behavior=r'''---------------- MODULE Behavior ----------------
EXTENDS Naturals, Sequences
VARIABLE history
vars == <<history>>
Entry(obj) == [participant |-> "n1", context |-> 1, effective |-> TRUE, object |-> obj]
Init == history = <<>>
Next == \/ /\ Len(history) = 0 /\ history' = Append(history, Entry("a"))
        \/ /\ Len(history) = 1 /\ history' = Append(history, Entry("OBJECT"))
Obs == [history |-> history]
====================================================
'''.replace('OBJECT',obj)
    model=save_bundle(runner.root,state,state.units[0],bundle,PythonBackend())
    result=verifier.check(runner,model,20)
    assert result.outcome==('counterexample' if conflict else 'holds'),result.reason
    m=EventMonitor(id='support',checker_id='Safe',event='support',binding_ids=['b'],grounding=Grounding())
    events=[{'event':'support','participant':'n1','context':1,'effective':True,'object':x} for x in ['a',obj]]
    assert monitor_support(events,m,prop)['outcome']==('violated' if conflict else 'holds')
