#!/usr/bin/env python3
"""Emit draft/plan.json and draft/submission.json for the recovery-dispatch check."""
import json
from pathlib import Path

import gen_map

DRAFT = Path(__file__).resolve().parents[1]
HARNESS = "harness/epaxos_recovery_dispatch_test.go"

CLAIM_ID = "claim-recovery-trypreaccept-dispatch"
BIND_DISPATCH = "bind-epaxos-recovery-dispatch"
BIND_TRYPREACCEPT = "bind-epaxos-trypreaccept-entry"

RECOVERY_SOURCES = [
    "src-epaxos-recovery-entry",
    "src-epaxos-prepare-reply",
    "src-epaxos-subcase-comment",
    "src-epaxos-subcase-dispatch",
    "src-epaxos-subcase-actions",
    "src-epaxos-bcast-try",
    "src-epaxos-trypreaccept",
    "src-epaxos-tryreply",
    "src-epaxos-prepare-handler",
    "src-epaxos-preaccept",
    "src-replica-quorum",
    "src-epaxos-accept",
    "src-epaxos-bcasts",
    "src-epaxos-exec-loop",
    "src-epaxos-run",
]

DERIVATION = (
    "The recovery decision of handlePrepareReply is a dispatch over six documented sub-cases "
    "(epaxos/epaxos.go:1228-1236). Sub-case 3 is documented as 'pre-accepted > f (not including the leader) and allEqual' and sub-case 4 as "
    "'pre-accepted >= f/2 (not including the leader) and allEqual'; the actions attached to them differ: sub-case 3 moves the instance to ACCEPTED and "
    "broadcasts Accept (line 1300-1303), while sub-case 4 sets tryingToPreAccept and broadcasts TryPreAccept (line 1304-1306), the conflict re-validation "
    "round implemented by handleTryPreAccept/handleTryPreAcceptReply. In the coded condition both branches test "
    "preAcceptCount >= SlowQuorumSize()-1 && !lb.leaderResponded && allEqual (line 1270-1272), so sub-case 4 can never be selected. "
    "For a five-replica recovery quorum (SlowQuorumSize()=3) an instance whose owner does not answer and whose pre-accepts are held by one or two of the "
    "three reporting replicas satisfies the documented sub-case 4 condition (>= f/2 with f=2) but not the documented sub-case 3 threshold (> f): the "
    "implementation nevertheless accepts the recovered attributes directly (count 2) or restarts phase 1 (count 1), and never asks the acceptors whether "
    "adopting those attributes conflicts with what they already hold. The corrected EPaxos recovery requires exactly that conflict re-validation whenever "
    "the pre-accepts observed by the recovery quorum do not establish that the value was chosen by a fast quorum, so this dispatch deviation removes the "
    "protection the TryPreAccept round exists for."
)

APPLICABILITY = (
    "Applies to recovery phase 1 of an instance owned by another replica in a five-replica deployment with thrifty=true: the recovering replica has a "
    "slow quorum (three) of same-ballot prepare replies, the instance owner never answers, no reply reports ACCEPTED/COMMITTED, and the pre-accepted "
    "replies agree on (seq, deps) with vote ballot equal to the recovery ballot. The observation is the message the recovering replica actually "
    "broadcasts and the internal sub-case state it ends in; the end-to-end effect of the skipped conflict validation on a full deployment is out of scope."
)

QUESTION = {
    "disposition": "ready_for_check",
    "preferred_check": "direct_test",
    "question": (
        "When a five-replica EPaxos recovery quorum reports an instance only as pre-accepted - the instance owner silent, the agreeing pre-accepts held by "
        "fewer than the whole recovery quorum and no reply reporting ACCEPTED or COMMITTED - does the recovering replica route the decision through the "
        "TryPreAccept conflict-validation sub-case (its own documented sub-case 4), or does it take the direct-Accept/restart branches instead?"
    ),
    "importance": (
        "Recovery is the only path that transfers authority for an instance between replicas. If the conflict-validation round is never dispatched, a "
        "recovery can accept attributes that were pre-accepted by fewer than a fast quorum without checking them against the accepted state of the other "
        "instances, which is the guarantee the corrected EPaxos recovery relies on to keep conflicting commands ordered; the same dispatch gap also makes "
        "the restart-on-accepted-conflict rule and the defer-cycle bookkeeping unreachable."
    ),
    "source_ids": RECOVERY_SOURCES,
    "participants": ["recovering replica", "instance owner replica", "two further prepare respondents"],
    "objects": [
        "epaxos.Replica.startRecoveryForInstance",
        "epaxos.Replica.handlePrepareReply sub-case dispatch",
        "epaxos.Replica.bcastTryPreAccept",
        "epaxos.Replica.handleTryPreAccept/handleTryPreAcceptReply",
        "Epaxos.LeaderBookkeeping.prepareReplies/leaderResponded",
    ],
    "contexts": [
        "recovery phase 1 for instance (owner=1, instance) on a non-owner replica, ballot = recovering replica id + N",
        "N=5, f=2, thrifty=true, SlowQuorumSize=3, FastQuorumSize=3",
        "owner silent; agreeing pre-accepts held by 1 or 2 of the 3 reporting replicas",
    ],
    "event_paths": [
        "executeCommands grace timer -> instancesToRecover -> run loop -> startRecoveryForInstance -> bcastPrepare",
        "PrepareReply(bal, vbal, status, command, seq, deps) -> handlePrepareReply quorum and adoption loop -> sub-case selection -> bcastAccept | bcastTryPreAccept | startPhase1",
    ],
    "activity_classes": ["A3", "A2"],
    "behavior_ids": ["beh-epaxos-recovery-phase1", "beh-epaxos-recovery-trypreaccept"],
    "fact_ids": ["fact-recovery-decision"],
    "supporting_behavior_ids": {
        "beh-epaxos-ballot-context-guard": "supplies the context: the recovery ballot is the authority that would overwrite the instance, and the owner's silence is only observable through the prepare quorum.",
        "beh-epaxos-accept-phase": "would consume the dispatch result: the direct-accept sub-case hands the adopted attributes to the Accept broadcast.",
        "beh-epaxos-recovery-trigger": "supplies the prehistory: only the local grace-period timer produces recovery requests for a stalled instance.",
    },
    "obligation_relation_kind": "recovery",
    "counterevidence": [
        "If the intended sub-case 3 threshold were really count >= SlowQuorumSize()-1, the direct-Accept branch would be intentional for count=2 and the duplicate condition would only make the TryPreAccept action dead code; the comment block at 1228-1236 states 'pre-accepted > f' for sub-case 3 and reserves a lower threshold ('>= f/2') for sub-case 4.",
        "Independently of the dispatch, the TryPreAccept round as implemented still could not succeed: handleTryPreAccept records inst.bal but not inst.vbal and never sets ConflictStatus, while handleTryPreAcceptReply counts a confirmation only when VBallot == lb.lastTriedBallot and restarts phase 1 only when ConflictStatus >= ACCEPTED.",
    ],
    "unknowns": [
        "which of the two documented thresholds the implementation intends: the code condition (>= SlowQuorumSize()-1) matches neither '> f' nor '>= f/2' exactly for N=5",
        "whether restoring the sub-case 4 dispatch alone (without repairing the TryPreAccept acknowledgement fields) would let the round complete",
        "whether the skipped conflict validation can be turned into a committed ordering or agreement violation in a full deployment, which the dispatch-level check cannot show",
    ],
    "priority": 2,
    "trigger_rationale": (
        "Two independent discrepancies meet in this dispatch: a branch that the source itself documents as reachable is dead (identical conditions), and the "
        "conflict re-validation it would start is therefore never exercised during recovery. The capture already contains everything needed to observe the "
        "dispatch deterministically, so an in-process execution of the real handlers can establish the actual broadcast without a full deployment."
    ),
}

CLAIM = {
    "id": CLAIM_ID,
    "kind": "obligation",
    "concern": "consensus_safety",
    "description": (
        "For an EPaxos instance whose recovery quorum reports only pre-accepted values, a recovering replica that does not observe the instance owner and "
        "whose agreeing pre-accepted replies are held by fewer than the whole recovery quorum must route the decision through the TryPreAccept "
        "conflict-validation sub-case before moving the instance to ACCEPTED or restarting phase 1; it must not take the direct-Accept sub-case with that "
        "evidence."
    ),
    "source_ids": RECOVERY_SOURCES,
    "scope": {
        "description": (
            "Recovery phase 1 dispatch of epaxos.Replica.handlePrepareReply for an instance owned by another replica, with a slow quorum of same-ballot "
            "prepare replies whose pre-accepted records agree and whose owner is silent."
        ),
        "assumptions": [
            "N=5, f=2, thrifty=true so SlowQuorumSize()=3 and FastQuorumSize()=3",
            "the recovering replica already holds its own candidate for the instance at the recovery ballot (an earlier recovery round re-proposed and locally pre-accepted it)",
            "the pre-accepts observed by the quorum come from fewer than FastQuorumSize replicas, so the value is not established as chosen",
            "no prepare reply reports ACCEPTED or COMMITTED for the instance",
        ],
        "excluded": [
            "the end-to-end consequence for a full deployment (whether a commit with unordered conflicts follows)",
            "durable metadata, client reply completion and execution ordering",
            "deployments with N>5 or with a quorum file",
        ],
        "parameters": {"n": 5, "f": 2, "slow_quorum": 3, "fast_quorum": 3, "thrifty": True},
    },
    "pending": [
        "confirm the intended sub-case thresholds from a normative source outside the snapshot, if one is available",
        "decide whether the TryPreAccept acknowledgement mismatch is the same obligation or a second one",
    ],
    "grounding": {
        "source_ids": ["src-epaxos-subcase-comment", "src-epaxos-subcase-dispatch", "src-epaxos-recovery-entry", "src-replica-quorum"],
        "expectation_ids": ["src-epaxos-subcase-actions", "src-epaxos-bcast-try"],
        "binding_ids": [BIND_DISPATCH, BIND_TRYPREACCEPT],
        "derivation": DERIVATION,
        "applicability": APPLICABILITY,
        "unresolved": [
            "the snapshot contains no TLA specification or design document; the sub-case thresholds come from the in-code comment block",
            "the exact threshold the implementation intends cannot be recovered from the duplicated condition",
        ],
        "conflicts": [],
        "alternatives": [
            "the direct-Accept sub-case may be intended to carry the weaker evidence, with the TryPreAccept action retained only for a case that no captured input can produce",
        ],
    },
}

BINDINGS = [
    {
        "id": BIND_DISPATCH,
        "material_id": "src-epaxos-prepare-reply",
        "symbol": "Replica.handlePrepareReply",
        "start_line": 1255,
        "end_line": 1284,
        "description": (
            "Sub-case selection of recovery phase 1: the identical conditions for sub-cases 3 and 4, the count/allEqual/leaderResponded tests, and the "
            "panic fallback. The range sits inside the handlePrepareReply declaration of the same material."
        ),
        "pending": [],
        "associations": [
            {
                "claim_id": CLAIM_ID,
                "source_ids": ["src-epaxos-subcase-dispatch", "src-epaxos-subcase-comment"],
                "rationale": (
                    "The two branches carry the same guard, so only the first (sub-case 3 -> ACCEPTED + Accept broadcast) can be selected; the documented "
                    "sub-case 4 threshold is never reached."
                ),
            }
        ],
    },
    {
        "id": BIND_TRYPREACCEPT,
        "material_id": "src-epaxos-bcast-try",
        "symbol": "Replica.bcastTryPreAccept",
        "start_line": 528,
        "end_line": 553,
        "description": (
            "The only producer of the TryPreAccept round: it is invoked from the sub-case 4 branch alone and fans the candidate attributes out to every alive peer."
        ),
        "pending": [],
        "associations": [
            {
                "claim_id": CLAIM_ID,
                "source_ids": ["src-epaxos-bcast-try", "src-epaxos-subcase-actions"],
                "rationale": "Its single call site is the dead sub-case 4 branch, so the conflict-validation round has no reachable producer.",
            }
        ],
    },
]

PLAN = {
    "description": (
        "Discriminator: does the recovering replica broadcast TryPreAccept for a slow-quorum recovery whose agreeing pre-accepts are fewer than the whole "
        "quorum and whose instance owner is silent? The harness enters recovery of instance (1, k) on replica 0 through the real startRecoveryForInstance, "
        "then feeds the two remaining same-ballot PrepareReply messages of the slow quorum (owner 1 silent) while varying only the number of peers that "
        "carry an equal pre-accept at the recovery ballot: two peers (a full quorum of agreeing pre-accepts - control), one peer (two matching pre-accepts), "
        "no peer (only the recovering replica's own pre-accept). The observed dispatch comes from the byte actually written to the peer writers, so the "
        "checker compares the broadcast the implementation performs, not a predicted branch. Controls: the full-quorum scenario must still take the "
        "documented direct-accept sub-case."
    ),
    "claim_id": CLAIM_ID,
    "binding_ids": [BIND_DISPATCH, BIND_TRYPREACCEPT],
    "harness": {
        "kind": "go_test",
        "description": (
            "In-process execution of epaxos recovery dispatch: an epaxos.Replica is constructed without network setup, its own pre-accepted candidate is "
            "installed for instance (1,k), startRecoveryForInstance is called, and the remaining prepare replies are delivered directly to handlePrepareReply. "
            "Each scenario emits a recovery_quorum_gathered prerequisite event and a recovery_dispatch result event."
        ),
        "semantic_changes": [
            "the harness constructs epaxos.Replica with a struct literal instead of epaxos.New, which would start listeners and (through defs.IP) require an outbound route; no protocol field is altered",
            "recovery is entered by calling startRecoveryForInstance directly instead of waiting for the 10s grace-period timer",
            "the peer PrepareReplies of the recovery quorum are delivered as in-process values instead of socket frames, preserving ballot, vote ballot, status, command and (seq, deps)",
            "peer writes are captured in per-peer byte buffers so the broadcast the implementation performs can be observed without a network",
        ],
        "prerequisites": [
            {
                "alias": "quorum",
                "event": "recovery_quorum_gathered",
                "conditions": [{"field": "quorum_size", "op": "eq", "value": 3}],
            }
        ],
        "legality": {
            "source_ids": RECOVERY_SOURCES,
            "expectation_ids": ["src-epaxos-subcase-actions"],
            "binding_ids": [BIND_DISPATCH, BIND_TRYPREACCEPT],
            "derivation": (
                "Each scenario is a legal prefix of recovery phase 1: the recovering replica already pre-accepted its candidate during an earlier recovery round "
                "at the same ballot (startPhase1 broadcasts PreAccept at lb.lastTriedBallot), the owner never answered, and exactly the two further same-ballot "
                "PrepareReply messages needed to reach SlowQuorumSize()=3 are supplied; the peer that carries no record reports ballot equal to the recovery "
                "ballot and vote ballot -1, which is what handlePrepare leaves behind."
            ),
            "applicability": APPLICABILITY,
            "unresolved": [
                "the check observes the dispatch decision only; downstream commit/ordering effects of the skipped conflict validation are not exercised",
            ],
            "conflicts": [],
            "alternatives": [],
        },
    },
    "monitors": [
        {
            "id": "mon-recovery-dispatch-partial",
            "checker_id": "chk-recovery-dispatch-partial",
            "event": "recovery_dispatch",
            "binding_ids": [BIND_DISPATCH, BIND_TRYPREACCEPT],
            "admission_alias": "quorum",
            "applicability_conditions": [{"field": "owner_replied", "op": "eq", "value": False}],
            "grounding": {
                "source_ids": ["src-epaxos-subcase-dispatch", "src-epaxos-subcase-comment"],
                "expectation_ids": ["src-epaxos-subcase-actions"],
                "binding_ids": [BIND_DISPATCH, BIND_TRYPREACCEPT],
                "derivation": (
                    "The result event reports the message the recovering replica actually broadcast and the sub-case state it ended in; the requirement being "
                    "checked is the documented sub-case 4 dispatch for partially agreeing pre-accepts."
                ),
                "applicability": APPLICABILITY,
                "unresolved": ["the intent of the duplicated condition remains unresolved in the captured source"],
                "conflicts": [],
                "alternatives": [],
            },
        },
        {
            "id": "mon-recovery-dispatch-full",
            "checker_id": "chk-recovery-dispatch-full",
            "event": "recovery_dispatch",
            "binding_ids": [BIND_DISPATCH],
            "admission_alias": "quorum",
            "applicability_conditions": [],
            "grounding": {
                "source_ids": ["src-epaxos-subcase-dispatch"],
                "expectation_ids": ["src-epaxos-subcase-actions"],
                "binding_ids": [BIND_DISPATCH],
                "derivation": (
                    "Control scenario: with every slow-quorum reply carrying an equal pre-accept, the implementation's documented sub-case 3 applies and the "
                    "dispatch must be the Accept broadcast; observing it shows the harness reaches the intended boundary."
                ),
                "applicability": (
                    "Applies to the five-replica scenario in which the recovering replica and both answering peers all hold an equal pre-accept at the recovery ballot."
                ),
                "unresolved": [],
                "conflicts": [],
                "alternatives": [],
            },
        },
    ],
    "observable_properties": [
        {
            "checker_id": "chk-recovery-dispatch-partial",
            "kind": "event_assertion",
            "trigger": {"field": "evidence_class", "op": "eq", "value": "partial_preaccepted_owner_silent"},
            "assertion": {"field": "dispatch", "op": "eq", "value": "try_preaccept"},
            "identity_fields": ["instance_replica", "instance_id"],
            "description": (
                "For a recovery quorum whose agreeing pre-accepted replies are fewer than the whole quorum, with the instance owner silent, the recovering "
                "replica dispatches the TryPreAccept conflict-validation sub-case (its documented sub-case 4) instead of broadcasting Accept or restarting "
                "phase 1."
            ),
        },
        {
            "checker_id": "chk-recovery-dispatch-full",
            "kind": "event_assertion",
            "trigger": {"field": "evidence_class", "op": "eq", "value": "full_preaccepted_owner_silent"},
            "assertion": {"field": "dispatch", "op": "eq", "value": "accept"},
            "identity_fields": ["instance_replica", "instance_id"],
            "description": (
                "Control: when every reply of the slow quorum carries an equal pre-accept at the recovery ballot, the implementation takes its documented "
                "direct-accept sub-case and broadcasts Accept."
            ),
        },
    ],
    "uncertainties": [
        "the obligation uses the in-code sub-case description as the statement of the intended dispatch; no design document or TLA specification is in the snapshot",
        "the check establishes the dispatch decision only, not the full-deployment consequence of skipping the conflict re-validation",
    ],
}


def submission():
    return {
        "action": "check",
        "rationale": (
            "Escalate the recovery sub-case question into one obligation and check it directly: the in-process harness drives the real recovery dispatch and "
            "reports which message the recovering replica broadcasts for partially agreeing, owner-silent prepare quorums."
        ),
        "sources": gen_map.SOURCES,
        "plan_path": "plan.json",
        "harness_path": HARNESS,
        "files": {},
        "candidate": {
            "action": "obligation",
            "rationale": (
                "The recovered decision is the principal Fact of the A3/A2 connection: the dispatch fixes which ballot and which adopted value may overwrite "
                "the instance. Sub-case 4 is documented but unreachable, so the obligation is the required dispatch itself."
            ),
            "map_path": "map-v1.json",
            "question": QUESTION,
            "obligation": CLAIM,
            "bindings": BINDINGS,
        },
    }


if __name__ == "__main__":
    (DRAFT / "plan.json").write_text(json.dumps(PLAN, indent=1, ensure_ascii=False) + "\n")
    (DRAFT / "submission.json").write_text(json.dumps(submission(), indent=1, ensure_ascii=False) + "\n")
    print("wrote plan.json and submission.json (check + obligation)")
