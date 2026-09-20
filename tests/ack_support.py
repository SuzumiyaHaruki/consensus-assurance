import json
from pathlib import Path
from consensus_assurance.core.types import *
from consensus_assurance.core.proposals import *
from consensus_assurance.core.config import Config
from consensus_assurance.adapters.storage.snapshot import capture
from consensus_assurance.workflow.materials import read_material, ReadRequest

ROOT=Path(__file__).resolve().parent


def setup_ack(repo, mode='durable', partial=False):
    snapshot=capture(repo)
    materials=[read_material(repo,snapshot,ReadRequest(file=f,start_line=1,end_line=len((repo/f).read_text().splitlines()),reason='Controlled contract evidence')) for f in ['counter.py','README.md']]
    code,document=materials
    scope=Scope(description='Synthetic serial acknowledgement, one participant and operation, no faults',excluded=['Production implementations','General crash semantics'])
    basis=Grounding(behavior_ids=[code.id],expectation_ids=[document.id],binding_ids=['ack-code'],derivation='The selected configuration defines whether return promises memory acceptance or persistence',applicability='The emitted mode and fault metadata identify the exercised configuration')
    claims=[Claim(id='memory',kind='obligation',description='Return implies memory acceptance',scope=scope,source='Synthetic contract',source_ids=[document.id],grounding=basis),Claim(id='durable',kind='obligation',description='Return implies persistence in durable mode',scope=scope,source='Synthetic contract',source_ids=[document.id],grounding=basis)]
    if mode=='conflict': claims[1].grounding=basis.model_copy(update={'conflicts':['Conflicting guarantees remain unresolved']})
    state=Analysis(mode='real',analysis_mode='regression',snapshot=snapshot,config=Config(execution_backend='python',protocol='none').model_dump(mode='json'),materials=materials,claims=claims)
    state.bindings=[Binding(id='ack-code',material_id=code.id,claim_id='durable',file=code.file,symbol='execute',start_line=1,end_line=code.end_line,snapshot_id=snapshot.id,content_digest=code.content_digest,basis='code_observation',description='Actual state changes and response event',excerpt=code.text)]
    unit=AuditUnit(id='ack',obligation_ids=['memory','durable'],binding_ids=['ack-code'],relation_ids=[],scope=scope,rationale='Controlled finite contract test')
    state.units=[unit]
    behavior=r'''---------------- MODULE Behavior ----------------
EXTENDS Naturals
VARIABLE accepted, persisted, returned
vars == <<accepted, persisted, returned>>
Init == /\ accepted = FALSE /\ persisted = FALSE /\ returned = FALSE
Next == \/ /\ ~accepted /\ accepted' = TRUE /\ UNCHANGED <<persisted, returned>>
        \/ /\ accepted /\ ~returned /\ returned' = TRUE /\ UNCHANGED <<accepted, persisted>>
        \/ /\ returned /\ ~persisted /\ persisted' = TRUE /\ UNCHANGED <<accepted, returned>>
Obs == [accepted |-> accepted, persisted |-> persisted, returned |-> returned]
===================================================
'''
    if partial:
        behavior=behavior.replace('returned\' = TRUE /\\ UNCHANGED <<accepted, persisted>>',"returned' = TRUE /\\ persisted' \\in BOOLEAN /\\ UNCHANGED accepted")
        behavior=behavior.replace('persisted |-> persisted, ','')
    properties='''---------------- MODULE Properties ----------------
EXTENDS Behavior
MemoryAck == ~returned \\/ accepted
DurableAck == ~returned \\/ persisted
====================================================
'''
    fields=['accepted','returned'] if partial else ['accepted','persisted','returned']
    harness='''import json
from counter import execute

def emit(event):
    PARTIAL
    print('CA_EVENT '+json.dumps(event))

execute(MODE, emit)
'''.replace('PARTIAL',"event['state'].pop('persisted',None)" if partial else 'pass').replace('MODE',repr(mode))
    prereqs=[EventRequirement(alias='accepted',event='accepted'),EventRequirement(alias='returned',event='returned',conditions=[Comparison(field=f,reference='accepted.'+f) for f in ['operation','participant','context']])]
    checker='MemoryAck' if mode=='memory' else 'DurableAck'
    monitor=EventMonitor(id='ack-monitor',checker_id=checker,event='returned',identity_fields=['operation','participant','context'],assertion=Comparison(field='state.accepted' if mode=='memory' else 'state.persisted',value=True),binding_ids=['ack-code'],grounding=basis,applicability_conditions=[Comparison(field='metadata.mode',value=mode)])
    bundle=Bundle(description='Controlled acknowledgement semantics',behavior=behavior,properties=properties,constants='',checkers=[CheckerSpec(invariant='MemoryAck',claim_id='memory',scope=scope),CheckerSpec(invariant='DurableAck',claim_id='durable',scope=scope)],initial_state='No acceptance, durability or response',variables=['accepted','persisted','returned'],actions=['accept','return','persist'],constraints=[ConstraintSource(constraint='Return precedes persistence in actual fixture',source_kind='code_observation',source_ids=[code.id],binding_ids=['ack-code'],justification='Calls observe before setting persisted')],scope=scope,observation=ObservationMap(fields=[FieldProjection(model_field=f,raw_field=f) for f in fields],required_events=['initial','accepted','returned','persisted'],description='Actual mutable state snapshots'),harness=Harness(kind='python',source=harness,description='Calls the actual synthetic service',prerequisite_events=[],prerequisites=prereqs,semantic_changes=[],legality=basis,legal_conditions=[Comparison(field='metadata.fault',value='none')]),uncertainties=[],monitors=[monitor])
    if mode=='memory': bundle.checkers=[bundle.checkers[0]]
    properties = [ObservableProperty(checker_id=c.invariant, trigger=Comparison(field='state.returned',value=True),
        assertion=Comparison(field='state.accepted' if c.invariant=='MemoryAck' else 'state.persisted',value=True), description='Controlled response implication') for c in bundle.checkers]
    bundle.observable_properties = properties
    monitor.property = next(p for p in properties if p.checker_id==checker)
    monitor.conditions = [monitor.property.trigger]
    if not partial:
        from consensus_assurance.adapters.verifiers.observable import properties_source
        bundle.properties = properties_source(properties,bundle.observation)
    return state,unit,bundle
