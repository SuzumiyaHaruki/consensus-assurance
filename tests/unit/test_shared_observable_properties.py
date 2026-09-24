import shutil
from pathlib import Path

from ack_support import ROOT, setup_ack
from consensus_assurance.adapters.verifiers.observable import correspondence, properties_source
from consensus_assurance.core.proposals import Comparison, ObservableProperty, EventMonitor, EventRequirement
from consensus_assurance.workflow.observations import monitor_events


def test_generated_model_predicate_matches_shared_description(tmp_path):
    repo=tmp_path/'repo';shutil.copytree(ROOT/'fixtures/ack_service',repo)
    _,_,bundle=setup_ack(repo)
    monitor=bundle.monitors[0]
    assert correspondence(bundle,monitor) is None
    changed=bundle.model_copy(deep=True);changed.properties=changed.properties.replace('Obs.persisted = TRUE','TRUE')
    assert 'differs' in correspondence(changed,monitor)


def test_cross_event_support_monitor_preserves_identity_and_context():
    prop=ObservableProperty(checker_id='Support',kind='stable_support',trigger=Comparison(field='effective',value=True),assertion=Comparison(field='object'),identity_fields=['participant','context'],history_field='state.history',description='Candidate support cannot conflict within an applicable context')
    from consensus_assurance.core.types import Grounding
    m=EventMonitor(id='support',checker_id='Support',event='support',binding_ids=['b'],grounding=Grounding())
    first={'event':'support','participant':'n1','context':1,'effective':True,'object':'a'}
    second={**first,'object':'b'}
    assert monitor_events([first,second],m,prop)['outcome']=='violated'
    assert monitor_events([first,{**second,'context':2}],m,prop)['outcome']=='holds'
    assert monitor_events([first,{**second,'participant':'n2'}],m,prop)['outcome']=='holds'
    assert monitor_events([first,{k:v for k,v in second.items() if k!='context'}],m,prop)['outcome']=='unknown'


def test_v16_checker_correction_uses_one_way_success_requirement():
    from consensus_assurance.core.types import Grounding
    prop=ObservableProperty(checker_id='EligibleSupport',kind='event_implication',
        trigger=Comparison(field='event',value='verification_result'),
        antecedent=Comparison(field='success',value=True),
        assertion=Comparison(field='success',reference='input.expected_success'),
        identity_fields=['operation_id'],description='Successful verification requires eligible voter support')
    monitor=EventMonitor(id='eligibility',checker_id=prop.checker_id,event='verification_result',
        binding_ids=['b'],grounding=Grounding(),
        applicability_conditions=[Comparison(field='completed',value=True)])
    requirement=[EventRequirement(alias='input',event='contribution_completed')]
    def observed(success,eligible,completed=True):
        return [{'event':'contribution_completed','operation_id':'op','expected_success':eligible,'_ca_stream':'run'},
            {'event':'verification_result','operation_id':'op','success':success,'completed':completed,'_ca_stream':'run'}]
    assert monitor_events(observed(False,True),monitor,prop,requirement)['outcome']=='holds'
    assert monitor_events(observed(True,False),monitor,prop,requirement)['outcome']=='violated'
    assert monitor_events(observed(False,True,False),monitor,prop,requirement)['outcome']=='unknown'
