import json
r=json.load(open('../research.json'));m=json.load(open(r['audit_spec_path']))
sources=[]
def add(i,f,a,b,k='code_observation'):
 sources.append(dict(id=i,file=f,start_line=a,end_line=b,kind=k))
add('S-applied-publication','internal/rsm/statemachine.go',664,709)
add('S-node-events','node.go',1111,1167)
add('S-session-update','internal/rsm/statemachine.go',1001,1049)
add('S-session-cache','internal/rsm/session.go',57,130)
add('S-session-manager','internal/rsm/sessionmanager.go',43,151)
add('S-session-save','internal/rsm/lrusession.go',89,122)
add('S-session-order-test','internal/rsm/lrusession_test.go',120,191,'test_expectation')
add('S-rsm-snapshot-preparation','internal/rsm/statemachine.go',603,634)
add('S-result-interface','statemachine/rsm.go',136,149,'interface_statement')
add('S-result-export','request.go',199,204,'interface_statement')
add('S-result-notify','request.go',1162,1178)
add('S-propose-duties','nodehost.go',808,836,'interface_statement')
changes={}
def change(i,why,ss):
 changes[i]=dict(impact='clarification',rationale=why,source_ids=ss,preserves='C-read-context retains its requirement, fixed-membership dependency basis and Peer readiness observation scope. These explanations neither alter the principal Fact nor extend that result to client/application consequences.',challenges={})
for b in m['behaviors']:
 if b['id']=='B-read-confirm':
  b['unknowns']=[]
  b['important_branches']=['For a confirmed prefix with distinct contexts, each returned status retains its own ctx; local-origin readiness preserves it, while remote response emission selects the triggering heartbeat context for every returned remote status.']
  change(b['id'],'Replace resolved context-propagation question with the conditional source relationship.', ['S-read-response','S-read-queue'])
 if b['id']=='B-read-deliver':
  b['unknowns']=[]
  b['external_effects']=['Remote responses for earlier statuses in a confirmed prefix carry the triggering heartbeat context, and the originating follower publishes that received context/index through ReadyToRead. This does not itself complete the exact-key NodeHost batch.']
  change(b['id'],'Record actual context selection and follower propagation without an obsolete execution reminder.', ['S-read-response','S-follower-read','S-client-batches'])
 if b['id']=='B-membership':
  b['source_ids']+=['S-applied-publication','S-node-events']
  b['existing_protections']=['RSM configChange updates its internal index before the node callback, but the public lastApplied index is published only after handleEntry returns. node.updateAppliedIndex reads that public index, so the local ordering does not expose the just-applied configuration index before the callback updates raft membership.']
  b['unknowns']=['Pending readIndex confirmation maps are not explicitly pruned on removal; the applicability of retained support requires accounting for read invocation, prior configuration commitment and subsequent quorum authority in one legal history.']
  change(b['id'],'Differentiate internal applied index from public applied-index publication; retain the independent pending-support premise.', ['S-rsm-config','S-rsm-apply','S-applied-publication','S-node-events','S-membership','S-read-queue'])
 if b['id']=='B-apply':
  b['source_ids']+=['S-session-update','S-session-cache','S-session-manager','S-node-events']
  b['important_branches']=['For session-managed entries, unknown client is rejected; already acknowledged series is ignored; cached unacknowledged series returns the prior result without another application update; otherwise application Update runs and its result is cached.','A skipped/ignored entry does not always call node.ApplyUpdate; StateMachine.Handle publishes lastApplied and signals StepReady, and node.handleEvents invokes pendingReadIndexes.applied for the public applied index.']
  b['unknowns']=['Ownership and mutation constraints for Result.Data shared between session history and client-visible results remain unclear.','On-disk state-machine session bypass and recovery variants need deeper tracing.']
  change(b['id'],'Replace generic session/deduplication gap with sourced replay branches and the precise result-buffer ownership question; record alternative applied-index continuation.', ['S-session-update','S-session-cache','S-session-manager','S-rsm-work','S-rsm-apply','S-node-events'])
m['core_overview']['open_details']=['Remote confirmed-prefix response emission uses the triggering context for earlier remote requests; NodeHost client and application consequences remain outside the checked endpoint.','Pending confirmation support spanning membership changes requires an authority/timing history; local membership publication ordering is protected.','Result.Data ownership across session-history caching and client-visible responses is unresolved.','Logdb crash atomicity and on-disk application variants remain unread details.']
change('core_overview','Replace answered propagation and generic session questions with sourced conditional relationships and remaining concrete premises.', ['S-read-response','S-client-batches','S-session-update','S-result-export','S-result-interface','S-applied-publication'])
for surf in m['surfaces']:
 if surf['entry_point']=='raft.handleReadIndexLeaderConfirmation':surf['reason']='How does the established remote context substitution affect a complete NodeHost client interval? The scoped Peer identity result does not measure this endpoint.'
 if surf['entry_point']=='raft.handleNodeConfigChange/readIndex.confirm':surf['reason']='Determine whether retained confirmations across legal configuration changes violate an applicable authority condition after accounting for configuration commitment timing and permitted earlier linearization.'
m['surfaces'].append(dict(entry_point='StateMachine.update -> Session.addResponse -> RequestResult.GetResult',disposition='UNCLASSIFIED_PROTOCOL_RESPONSIBILITY',reason='Result.Data is a slice stored in session history and returned by value through completion; determine who owns its backing bytes and whether legal application/client reuse can change replay or checkpointed response contents.',source_ids=['S-session-update','S-session-cache','S-result-interface','S-result-export','S-result-notify'],high_consequence=True))
json.dump(m,open('map2.json','w'),indent=2)
s=dict(action='research',rationale='Incorporate the accepted scoped finding and investigation of composed membership/application protections; retain a precise result-buffer ownership Surface rather than infer a defect from slice aliasing.',sources=sources,map_path='map2.json',map_changes=changes,feedback=dict(ref_ids=['a118363ef443443ca4bcfe8f5be0f751','b5f3cb2c346040a9b22ca064ee24a691','B-read-confirm','B-read-deliver','B-membership','B-apply','S-applied-publication','S-node-events','S-session-update','S-result-export'],answered='The accepted assessment confirms C-read-context in its Peer-only scope. Source investigation also excludes a proposed local configuration-publication race: configChange\'s setApplied updates the internal index; public lastApplied is published after the callback, and node reads the latter for campaign suppression. Session replay has explicit rejection/ignore/cache-hit branches, and skipped per-entry completion is supplemented by public applied-index publication, StepReady and node.handleEvents. These explanations supply no universal membership/read safety result.',remaining=['For retained read confirmations across membership changes, distinguish stale ineligible counts from an actual authority failure with a legal invocation/configuration-commit history.','Investigate Result.Data ownership before claiming that aliasing session history and exported responses violates a contract.','Full NodeHost consequences of the confirmed Peer context mismatch remain unmeasured and are not needed to retain the existing result.'],understanding='updated',rationale='Resolved source premises replace generic unknowns. The next useful step is contract/ownership tracing, not execution of arbitrary buffer mutation or a invented membership history.'))
json.dump(s,open('submission5.json','w'),indent=2)
