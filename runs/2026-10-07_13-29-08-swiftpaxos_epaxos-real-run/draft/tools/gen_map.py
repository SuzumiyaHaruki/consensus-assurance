#!/usr/bin/env python3
"""Generate the partial consensus map (audit-spec v1) for the EPaxos snapshot."""
import json
from pathlib import Path

DRAFT = Path(__file__).resolve().parents[1]


def src(id_, file, start, end, kind):
    return {"id": id_, "file": file, "start_line": start, "end_line": end, "kind": kind}


SOURCES = [
    src("src-epaxos-new", "epaxos/epaxos.go", 134, 197, "code_observation"),
    src("src-epaxos-durable-meta", "epaxos/epaxos.go", 199, 236, "code_observation"),
    src("src-epaxos-run", "epaxos/epaxos.go", 278, 383, "code_observation"),
    src("src-epaxos-exec-loop", "epaxos/epaxos.go", 385, 433, "code_observation"),
    src("src-epaxos-ballot-helpers", "epaxos/epaxos.go", 435, 467, "code_observation"),
    src("src-epaxos-bcasts", "epaxos/epaxos.go", 469, 611, "code_observation"),
    src("src-epaxos-bcast-try", "epaxos/epaxos.go", 528, 553, "code_observation"),
    src("src-epaxos-tables", "epaxos/epaxos.go", 619, 722, "code_observation"),
    src("src-epaxos-propose-phase1", "epaxos/epaxos.go", 724, 779, "code_observation"),
    src("src-epaxos-preaccept", "epaxos/epaxos.go", 781, 845, "code_observation"),
    src("src-epaxos-preaccept-reply", "epaxos/epaxos.go", 847, 972, "code_observation"),
    src("src-epaxos-accept", "epaxos/epaxos.go", 974, 1064, "code_observation"),
    src("src-epaxos-commit", "epaxos/epaxos.go", 1066, 1113, "code_observation"),
    src("src-epaxos-recovery-entry", "epaxos/epaxos.go", 1115, 1169, "code_observation"),
    src("src-epaxos-prepare-handler", "epaxos/epaxos.go", 1171, 1202, "code_observation"),
    src("src-epaxos-prepare-reply", "epaxos/epaxos.go", 1204, 1314, "code_observation"),
    src("src-epaxos-subcase-comment", "epaxos/epaxos.go", 1228, 1236, "document_statement"),
    src("src-epaxos-subcase-dispatch", "epaxos/epaxos.go", 1255, 1284, "code_observation"),
    src("src-epaxos-subcase-actions", "epaxos/epaxos.go", 1298, 1314, "code_observation"),
    src("src-epaxos-trypreaccept", "epaxos/epaxos.go", 1316, 1352, "code_observation"),
    src("src-epaxos-find-conflicts", "epaxos/epaxos.go", 1354, 1400, "code_observation"),
    src("src-epaxos-tryreply", "epaxos/epaxos.go", 1402, 1485, "code_observation"),
    src("src-exec", "epaxos/exec.go", 25, 158, "code_observation"),
    src("src-defs-acceptreply", "epaxos/defs.go", 500, 512, "code_observation"),
    src("src-defs-tryreply", "epaxos/defs.go", 1118, 1130, "code_observation"),
    src("src-replica-quorum", "replica/replica.go", 121, 135, "code_observation"),
    src("src-replica-send", "replica/replica.go", 215, 241, "code_observation"),
    src("src-replica-listen", "replica/replica.go", 416, 472, "code_observation"),
    src("src-replica-config", "replica/replica.go", 23, 62, "code_observation"),
    src("src-defs-ip", "replica/defs/latency.go", 228, 238, "code_observation"),
    src("src-run-epaxos", "run.go", 23, 70, "code_observation"),
    src("src-client-propose", "client/client.go", 175, 230, "code_observation"),
    src("src-client-wait", "client/buffer.go", 175, 197, "code_observation"),
    src("src-state-conflict", "state/state.go", 75, 146, "code_observation"),
    src("src-dlog", "dlog/dlog.go", 22, 58, "code_observation"),
    src("src-master-register", "master/master.go", 187, 260, "code_observation"),
    src("src-mset", "replica/mset.go", 1, 25, "code_observation"),
    src("src-hook", "hook/cond.go", 20, 45, "code_observation"),
    src("src-rpc", "rpc/rpc.go", 5, 20, "code_observation"),
]


def behavior(id_, activity, owner, context, trigger, sources, **kw):
    obj = {
        "id": id_,
        "primary_activity": activity,
        "execution_owner": owner,
        "protocol_context": context,
        "trigger": trigger,
        "source_ids": sources,
    }
    obj.update(kw)
    return obj


BEHAVIORS = [
    behavior(
        "beh-epaxos-propose", "A1",
        "owner replica of the new instance (r.Id); run-loop goroutine handles the proposal batch",
        "per-instance ownership: instance (owner, crtInstance[owner]) with the owner's initial ballot = owner id",
        "client proposal reaches r.ProposeChan (or the batching fast clock releases it)",
        ["src-epaxos-propose-phase1", "src-epaxos-tables", "src-epaxos-new"],
        legal_preconditions=[
            "proposal is read from ProposeChan by the run loop, which is the only writer of crtInstance[r.Id]",
        ],
        implementation_guards=[
            "r.crtInstance[r.Id]++ assigns the next instance number before attributes are computed",
            "updateAttributes consults r.conflicts and r.maxSeqPerKey of this replica only",
        ],
        reads=["r.conflicts[q][key].last / lastWrite", "r.InstanceSpace[q][d].Seq", "r.maxSeqPerKey[key]", "r.crtInstance[r.Id]"],
        writes=["r.InstanceSpace[r.Id][instance] = new Instance(...)", "Instance.Cmds/Seq/Deps/Status=PREACCEPTED", "LeaderBookkeeping{cmds,deps,lastTriedBallot=ballot}", "r.conflicts[r.Id][key]", "r.maxSeqPerKey[key]"],
        durable_effects=["recordInstanceMetadata/recordCommands are no-ops while Durable=false (run.go passes durable=false)"],
        external_effects=["bcastPreAccept sends PreAccept to FastQuorumSize()-1 closest alive peers"],
        important_branches=["batchSize = len(ProposeChan)+1 collects queued proposals into one instance"],
        async_boundaries=["SendMsg takes r.M and writes on a per-peer bufio.Writer shared with the commit/reply paths"],
        produces_fact_ids=["fact-command-attributes"],
        existing_protections=["the instance number is allocated locally before any peer sees the command, so two proposals of one replica never share (owner,instance)"],
        unknowns=["proposal retry after a NOOP commit is re-injected through ProposeChan and re-acquires a fresh instance; the completion duty for the retried proposal is not traced here"],
    ),
    behavior(
        "beh-epaxos-preaccept-vote", "A1",
        "every replica that receives PreAccept (handlePreAccept in the run goroutine)",
        "instance (preAccept.Replica, preAccept.Instance) in the receiver's InstanceSpace, at the leader's ballot",
        "PreAccept message arrives on r.preAcceptChan",
        ["src-epaxos-preaccept", "src-epaxos-tables"],
        legal_preconditions=[
            "receiver has not stored a higher inst.bal for the instance (stale pre-accepts are dropped without a reply)",
        ],
        implementation_guards=[
            "preAccept.Ballot < inst.bal returns early and sends no reply",
            "inst.Cmds/Seq/Deps are overwritten with the sender's command and the locally merged attributes",
            "status is PREACCEPTED_EQ when updateAttributes reported no change, otherwise PREACCEPTED",
        ],
        reads=["inst.bal/Status/Cmds", "r.conflicts[q]", "r.maxSeqPerKey"],
        writes=["inst.Cmds", "inst.Seq", "inst.Deps", "inst.bal", "inst.vbal", "inst.Status", "r.crtInstance[preAccept.Replica]", "r.maxSeq"],
        external_effects=["PreAcceptReply carries inst.bal, inst.vbal, inst.Seq, inst.Deps, r.CommittedUpTo and inst.Status to the sender"],
        important_branches=["inst.Status >= ACCEPTED: the stored deps/seq/status are re-reported instead of merging the new command", "inst.Cmds == nil under an ACCEPTED/COMMITTED record writes the command into InstanceSpace[preAccept.LeaderId][Instance]"],
        produces_fact_ids=["fact-preaccept-vote"],
        consumes_fact_ids=["fact-command-attributes"],
        cross_activity_effects={"A6": "the receiver's conflict table is extended for the pre-accepted command, which fixes later attribute computations"},
        existing_protections=["the reply echoes inst.Seq/inst.Deps after local merging, so the leader can detect attribute disagreement without re-sending the command"],
        unknowns=["a PreAccept for an instance the receiver already holds at a higher ballot is answered with silence; the leader's recovery is left to the grace-period timer"],
    ),
    behavior(
        "beh-epaxos-leader-fast-path", "A1",
        "leader of the instance = owner replica running handlePreAcceptReply",
        "leader bookkeeping for the instance at the initial ballot (ballot == instance owner)",
        "PreAcceptReply arrives on r.preAcceptReplyChan with ballot equal to lb.lastTriedBallot",
        ["src-epaxos-preaccept-reply", "src-replica-quorum"],
        legal_preconditions=[
            "lb.status is PREACCEPTED or PREACCEPTED_EQ (a fresh proposal or a pre-accept round)",
            "reply ballot equals lb.lastTriedBallot; higher reply ballots only raise nacks",
        ],
        implementation_guards=[
            "preAcceptOKs counts only same-ballot replies",
            "allEqual is the conjunction of mergeAttributes over replies; for N<=3 with thrifty the equality test is skipped",
            "allCommitted is only computed for N>7; isInitialBallot requires ballot == instance owner",
            "commit requires preAcceptOKs >= FastQuorumSize()-1 together with the precondition",
        ],
        reads=["lb.status", "lb.lastTriedBallot", "lb.allEqual", "lb.committedDeps", "pareply.Ballot/VBallot/Seq/Deps/Status/CommittedDeps"],
        writes=["lb.seq", "lb.deps", "lb.ballot", "lb.status", "lb.preAcceptOKs", "inst.Status/bal/Cmds/Seq/Deps"],
        external_effects=["on commit: bcastCommit + client reply relay; otherwise bcastAccept"],
        important_branches=["precondition true -> COMMITTED at the fast quorum", "preAcceptOKs >= FastQuorumSize()-1 without precondition -> ACCEPTED and Accept broadcast", "reply with a higher ballot -> nacks; more than half raise the local ballot and start a prepare"],
        async_boundaries=["the leader replies to the client from the run goroutine only when !Dreply; with Dreply=true the reply waits for execution"],
        produces_fact_ids=["fact-fast-commit", "fact-committed-instance"],
        consumes_fact_ids=["fact-preaccept-vote", "fact-command-attributes"],
        existing_protections=["a fast quorum is a superset of a slow quorum for every captured N, so the transition to Accept waits for at least a majority of replicas"],
        unknowns=["whether skipping the equality test for N<=3 with thrifty can commit merged attributes that no FastQuorumSize member reported identically"],
    ),
    behavior(
        "beh-epaxos-accept-phase", "A1",
        "leader broadcasts Accept; each peer handleAccept installs the attributes and replies AcceptReply",
        "same instance context, ballot = lb.lastTriedBallot; Accept carries seq/deps but no command",
        "leader's Accept broadcast (slow path or recovery sub-case 2/3)",
        ["src-epaxos-accept", "src-epaxos-bcasts"],
        legal_preconditions=["the leader only broadcasts Accept after preAcceptOKs >= FastQuorumSize()-1 or a recovery decision"],
        implementation_guards=[
            "receiver overwrites inst.Deps/Seq/bal/vbal only while inst.Status < COMMITTED; it does not move inst.Status to ACCEPTED",
            "receiver always replies with inst.bal, even for a stale or already committed instance",
            "leader commits when acceptOKs+1 > N/2 and then broadcasts Commit",
        ],
        reads=["accept.Ballot/Deps/Seq", "inst.bal", "inst.Status", "lb.status", "lb.lastTriedBallot", "lb.acceptOKs"],
        writes=["inst.Deps", "inst.Seq", "inst.bal", "inst.vbal", "lb.acceptOKs", "inst.Status=COMMITTED on the leader"],
        external_effects=["AcceptReply to the leader; Commit broadcast and client relay on commit"],
        important_branches=["inst.Status >= COMMITTED: the value is kept and the current ballot is reported back", "stale reply ballot: ignored (nack bookkeeping is unreachable after the equality test)"],
        produces_fact_ids=["fact-accepted-value", "fact-committed-instance"],
        consumes_fact_ids=["fact-fast-commit", "fact-command-attributes"],
        existing_protections=["an acceptor that never saw the command still records (seq,deps,vbal), so the leader's Commit, not the Accept, carries the value"],
        unknowns=["a peer that only received Accept holds deps/seq with Status NONE and no command, so a later recovery sees no value from it"],
    ),
    behavior(
        "beh-epaxos-commit-install", "A1",
        "leader broadcasts Commit; every receiver runs handleCommit in its run goroutine",
        "instance (commit.Replica, commit.Instance) in the receiver; commit.Ballot orders the write against the stored ballot",
        "Commit message arrives on r.commitChan",
        ["src-epaxos-commit", "src-epaxos-bcasts"],
        legal_preconditions=["leader reached a majority (or the fast quorum) for the value before broadcasting"],
        implementation_guards=[
            "commit.Command/Seq/Deps/bal/vbal are installed and Status set to COMMITTED",
            "receiver ignores commits for an already-committed instance and commits with a ballot below inst.bal",
            "own instances that were committed as a single NOOP command re-inject their proposals into ProposeChan",
        ],
        reads=["inst.Status", "inst.bal", "inst.lb.clientProposals"],
        writes=["inst.Cmds/Seq/Deps/bal/vbal/Status", "r.conflicts[replica]", "r.CommittedUpTo[replica]", "r.crtInstance[commit.Replica]"],
        durable_effects=["recordInstanceMetadata/recordCommands are no-ops while Durable=false"],
        external_effects=["execution goroutine observes the newly committed instance and may reply to the client"],
        produces_fact_ids=["fact-committed-instance"],
        consumes_fact_ids=["fact-fast-commit", "fact-accepted-value"],
        cross_activity_effects={"A5": "commits the command and attributes that the executor later blocks on", "A6": "extends the conflict table and CommittedUpTo for this replica"},
        existing_protections=["Commit carries the command, so replicas that only saw Accept learn the value and can execute"],
        unknowns=["the re-propose branch dereferences inst.lb without a nil check; whether a legal history can deliver such a commit for a locally placeholder-created instance is not established"],
    ),
    behavior(
        "beh-epaxos-execute-scc", "A5",
        "each replica's executeCommands goroutine plus Exec.findSCC/strongconnect",
        "replica-local execution: per-owner ExecedUpTo watermark and the deps of committed instances",
        "poll loop wakes on every pass; executes when an instance is COMMITTED with a command",
        ["src-epaxos-exec-loop", "src-exec"],
        legal_preconditions=["every dependency instance in the interval (ExecedUpTo[q], Deps[q]] exists with a command and is COMMITTED or EXECUTED"],
        implementation_guards=[
            "instances with Status < COMMITTED or Cmds == nil block the scan and start the grace-period timer for that instance",
            "the SCC is executed in (Seq, owner replica, proposeTime) order and every member is marked EXECUTED",
            "the client reply is sent only when Dreply is true, the instance has leader bookkeeping and client proposals",
        ],
        reads=["InstanceSpace[q][inst].Status/Cmds/Deps/Seq/Index/Lowlink", "ExecedUpTo", "crtInstance", "Dreply", "lb.clientProposals"],
        writes=["Instance.Index/Lowlink", "Instance.Status=EXECUTED", "ExecedUpTo[q]", "r.State (command effects)"],
        external_effects=["ReplyProposeTS to the client writer; recovery requests into instancesToRecover after COMMIT_GRACE_PERIOD"],
        important_branches=["NOOP commands are executed as no-ops but still mark the instance EXECUTED", "unknown or uncommitted prefix aborts the whole scan"],
        async_boundaries=["recovery requests are queued on instancesToRecover and processed by the run goroutine"],
        produces_fact_ids=["fact-execution-order"],
        consumes_fact_ids=["fact-committed-instance"],
        cross_activity_effects={"A3": "the blocking instance and the 10s grace period are the trigger for recovery", "A7": "the deferred client reply is produced here"},
        existing_protections=["execution waits for the whole dependency prefix, so deps order is respected even when messages arrive out of order"],
        unknowns=["client-visible ordering across different instances is not reconstructible from this snapshot alone"],
    ),
    behavior(
        "beh-epaxos-ballot-context-guard", "A2",
        "every replica handling PreAccept/Accept/Prepare/Commit and every ballot-raising path",
        "per-instance ballot context: inst.bal is the authority of the stored value, inst.vbal the ballot at which it was last voted, r.maxRecvBallot the highest ballot observed anywhere",
        "any incoming protocol message or recovery attempt for an instance",
        ["src-epaxos-preaccept", "src-epaxos-accept", "src-epaxos-prepare-handler", "src-epaxos-commit", "src-epaxos-ballot-helpers"],
        legal_preconditions=["ballots are of the form round*N + replica; the instance owner's initial ballot equals its own replica id"],
        implementation_guards=[
            "PreAccept below inst.bal is dropped; Accept/Prepare/Commit below inst.bal keep the stored value and re-report inst.bal",
            "Prepare and Accept raise inst.bal to the sender's ballot; vbal is raised only by PreAccept and Accept",
            "makeBallot picks r.Id (plus one round for a foreign instance) and raises it above maxRecvBallot only when r.IsLeader is set",
        ],
        reads=["inst.bal", "inst.vbal", "inst.Status", "r.maxRecvBallot", "r.IsLeader"],
        writes=["inst.bal", "inst.vbal", "r.maxRecvBallot", "lb.lastTriedBallot"],
        important_branches=["higher-ballot Accept/Prepare overwrite deps/seq/vbal but never the command; a higher-ballot Commit also overwrites the command"],
        async_boundaries=["ballot state is only mutated inside the single run goroutine; replies are written under r.M"],
        produces_fact_ids=["fact-preaccept-vote"],
        consumes_fact_ids=["fact-command-attributes", "fact-accepted-value"],
        cross_activity_effects={"A3": "recovery acquires authority only by choosing a ballot above the observed maximum", "A1": "the leader's right to overwrite attributes is bounded by the stored ballot"},
        existing_protections=["every reply repeats the responder's current inst.bal, so a leader learns about a competing higher ballot through nacks even when its value is not overwritten"],
        unknowns=["r.IsLeader is set by the deployment master (BeTheLeader) and affects only ballot raising; the timing contract between that flag and concurrent recovery attempts is not traced here"],
    ),
    behavior(
        "beh-epaxos-recovery-phase1", "A3",
        "the replica that noticed the stalled instance, running startRecoveryForInstance/handlePrepare/handlePrepareReply in its run goroutine",
        "recovery context for an instance owned by another replica: fresh ballot, slow-quorum prepare replies, adopted value/status",
        "an instance id arrives on r.instancesToRecover, queued by the local executeCommands grace timer",
        ["src-epaxos-recovery-entry", "src-epaxos-prepare-handler", "src-epaxos-prepare-reply", "src-epaxos-subcase-comment"],
        legal_preconditions=[
            "the recovery replica has no committed value for the instance (a committed instance with a command short-circuits)",
            "prepare replies are collected until len(lb.prepareReplies) >= SlowQuorumSize() at the recovery ballot",
        ],
        implementation_guards=[
            "lb.prepareReplies is pre-seeded with the recovering replica's own state, so its own value/status counts in the quorum",
            "only replies whose Ballot equals lb.lastTriedBallot are appended; others only raise nacks",
            "the adopted value/status come from the reply with the highest VBallot (>= comparisons, last writer wins on ties)",
            "allEqual compares the adopted (seq,deps) against every reply that has the highest VBallot and a pre-accepted status",
        ],
        reads=["inst.Status/Cmds/Seq/Deps/vbal", "prepare reply Ballot/VBallot/Status/Command/Seq/Deps", "lb.leaderResponded"],
        writes=["lb.prepareReplies", "lb.ballot", "lb.seq", "lb.deps", "lb.status", "lb.cmds", "inst.bal", "inst.vbal", "inst.Status", "inst.Cmds/Seq/Deps"],
        external_effects=["bcastPrepare to all alive peers", "sub-case dispatch: Accept broadcast, TryPreAccept broadcast, or startPhase1"],
        important_branches=[
            "sub-case 1 committed: nothing further is sent",
            "sub-case 2 accepted: value re-accepted at the recovery ballot",
            "sub-case 3 (as coded): count >= SlowQuorumSize()-1 agreeing pre-accepts with a silent owner -> direct Accept",
            "sub-case 4 (as coded): same condition as 3, so the TryPreAccept broadcast is unreachable",
            "sub-case 5/6: startPhase1 re-proposes the adopted command (or NOOP) at the recovery ballot",
        ],
        async_boundaries=["each prepare reply is processed as a separate channel event; the decision runs on the reply that completes the quorum"],
        produces_fact_ids=["fact-recovery-decision", "fact-accepted-value"],
        consumes_fact_ids=["fact-recovery-request", "fact-preaccept-vote", "fact-accepted-value", "fact-committed-instance", "fact-conflict-verdict"],
        cross_activity_effects={"A2": "recovery re-establishes which ballot and which adopted value may overwrite the instance", "A1": "the adopted attributes become the input of a new Accept/pre-accept round"},
        existing_protections=["the pre-seeded self reply and the highest-VBallot selection keep the recovering replica from silently discarding a value that its own quorum reported"],
        unknowns=[
            "the documented sub-case 3 threshold (pre-accepted > f) and sub-case 4 threshold (pre-accepted >= f/2) cannot both hold with the coded condition; the intended boundary is unresolved",
        ],
    ),
    behavior(
        "beh-epaxos-recovery-trypreaccept", "A3",
        "recovery leader broadcasts TryPreAccept; acceptors answer in handleTryPreAccept and the leader folds replies in handleTryPreAcceptReply",
        "recovery context: the recovered attributes are validated against each acceptor's stored state before they are accepted",
        "sub-case 4 of handlePrepareReply (as coded, unreachable) or an equivalent conflict re-validation entry",
        ["src-epaxos-bcast-try", "src-epaxos-trypreaccept", "src-epaxos-find-conflicts", "src-epaxos-tryreply"],
        legal_preconditions=["the recovering replica holds a candidate value/attribute set from prepare replies"],
        implementation_guards=[
            "handleTryPreAccept records the candidate as PREACCEPTED at tpa.Ballot when the acceptor has no value for the instance and findPreAcceptConflicts reports no conflict",
            "the reply carries the acceptor's inst.bal, inst.vbal and the conflicting instance identity/status",
            "the leader counts a reply as a confirmation only when tpar.VBallot == lb.lastTriedBallot; otherwise it records a nack",
            "the leader restarts phase 1 when a slow quorum answered and tpar.ConflictStatus >= ACCEPTED",
        ],
        reads=["inst.Status/Cmds/Deps", "r.ExecedUpTo/crtInstance/InstanceSpace", "lb.lastTriedBallot", "tpar.VBallot/ConflictStatus/AcceptorId/ConflictReplica"],
        writes=["inst.bal", "inst.Cmds/Seq/Deps/Status", "lb.preAcceptOKs", "lb.nacks", "lb.possibleQuorum", "lb.tpaReps", "lb.tpaAccepted", "lb.tryingToPreAccept", "deferMap"],
        external_effects=["TryPreAcceptReply to the leader; on success the leader broadcasts Accept; on failure it defers or restarts phase 1"],
        important_branches=["tpar.VBallot == lastTriedBallot -> confirmation counted", "otherwise nack and possibleQuorum cleared", "conflicting instance already ACCEPTED -> abandon recovery and restart phase 1"],
        produces_fact_ids=["fact-conflict-verdict"],
        consumes_fact_ids=["fact-recovery-decision", "fact-preaccept-vote"],
        cross_activity_effects={"A1": "a successful round hands the recovered attributes to the Accept phase"},
        existing_protections=["an acceptor that already holds an ACCEPTED/COMMITTED value for the instance is reported as a conflict instead of being silently overwritten"],
        unknowns=[
            "the acceptor records bal but not vbal for the tried value, so a conflict-free confirmation is reported with the acceptor's previous ballot",
            "the reply's ConflictStatus field is never set by the producer, so the consumer's restart-on-accepted-conflict rule cannot fire",
        ],
    ),
    behavior(
        "beh-epaxos-recovery-trigger", "A3",
        "each replica's executeCommands goroutine; requests are consumed by the same replica's run goroutine",
        "liveness context: a locally visible instance gap blocks own execution and is re-examined after COMMIT_GRACE_PERIOD",
        "the scan repeatedly blocks on the same instance for >= COMMIT_GRACE_PERIOD (10s of accumulated sleeps)",
        ["src-epaxos-exec-loop", "src-epaxos-run"],
        legal_preconditions=["the blocked instance id lies between ExecedUpTo[q]+1 and crtInstance[q] for some owner q"],
        implementation_guards=[
            "timeout[q] accumulates only while problemInstance[q] is unchanged",
            "every instance from the blocking one up to crtInstance[q] is queued on instancesToRecover",
        ],
        reads=["ExecedUpTo", "crtInstance", "InstanceSpace[q][inst].Status/Cmds"],
        writes=["problemInstance", "timeout", "instancesToRecover"],
        external_effects=["startRecoveryForInstance executes in the run goroutine, not in a timer goroutine"],
        important_branches=["a new problem instance resets the per-owner timeout"],
        async_boundaries=["the request channel is buffered but the recovery work itself is serialized behind other run-loop events"],
        produces_fact_ids=["fact-recovery-request"],
        consumes_fact_ids=["fact-execution-order"],
        existing_protections=["recovery is not attempted before the grace period, so a slow but progressing dependency chain is not recovered"],
        unknowns=["recovery requests are queued from a non-running (unexecuted) replica as well; whether every replica can complete the queued recovery is not established here"],
    ),
    behavior(
        "beh-epaxos-client-completion", "A7",
        "replica that owns the instance (and any replica executing the committed instance with bookkeeping)",
        "client contract: one proposal per CommandId, reply carries the CommandId and the value of the executed command",
        "Dreply: reply after SCC execution on the instance that holds the client proposal; !Dreply: reply when the instance commits",
        ["src-epaxos-preaccept-reply", "src-epaxos-accept", "src-exec", "src-client-wait", "src-client-propose"],
        legal_preconditions=["the client sends the proposal to the closest replica only (Leaderless=true for epaxos), and waits for replies from that replica"],
        implementation_guards=[
            "ReplyProposeTS is called with inst.lb.clientProposals[i] under a per-client mutex",
            "a proposal whose instance was committed as a single NOOP is re-injected into ProposeChan instead of being answered",
            "the client stops reading replies after a non-TRUE OK flag",
        ],
        reads=["lb.clientProposals", "w.lb.clientProposals[idx].CommandId", "Dreply"],
        writes=["client writer (bufio.Writer) via ReplyProposeTS", "ProposeChan on NOOP re-proposal"],
        external_effects=["ProposeReplyTS frames are written to the client connection; multiple goroutines share r.M while writing"],
        important_branches=["NOOP command: no user-visible effect and no reply from this instance", "shouldRespond requires both Dreply and non-nil client proposals"],
        async_boundaries=["command execution, client reply and peer sends serialize on r.M, but each writer belongs to a different socket"],
        produces_fact_ids=["fact-client-reply"],
        consumes_fact_ids=["fact-execution-order", "fact-committed-instance"],
        existing_protections=["the client ignores reply values for correctness and only waits for the count of replies it issued"],
        unknowns=["no timeout or retransmission exists on the client side for a lost reply; the completion duty for a client whose replica stalls is not established here"],
    ),
    behavior(
        "beh-epaxos-membership", "A4",
        "run.go constructs the replica; master registers participants; replica.New sets N/F/Id/Alive/PreferredPeerOrder",
        "static deployment configuration: N replicas, f = (N-1)/2, one client co-located with each replica",
        "process start (runReplica) with the deployment config and master registration",
        ["src-run-epaxos", "src-replica-config", "src-master-register", "src-replica-quorum"],
        legal_preconditions=["N is read from the config, not from the master", "f = (len(ReplicaAddrs)-1)/2 is passed to the replica"],
        implementation_guards=[
            "quorum sizes are derived: FastQuorumSize = F+(F+1)/2, SlowQuorumSize = (N+1)/2, WriteQuorumSize = F+1, ReadQuorumSize = N-F",
            "broadcasts skip peers with Alive=false and use PreferredPeerOrder, whose last slot is the replica itself",
        ],
        reads=["c.ReplicaAddrs", "c.Noop", "r.Alive", "r.PreferredPeerOrder"],
        writes=["N", "F", "Id", "Alive", "PreferredPeerOrder", "Thrifty=true, Durable=false, batchWait=0, transconf=false"],
        external_effects=["master assigns replica ids/leader hints; the epaxos client uses its co-located replica instead of a leader"],
        important_branches=["protocol=epaxos forces Leaderless and non-fast client mode", "beacon/latency adaptation is disabled (Beacon=false, no -latency file)"],
        produces_fact_ids=["fact-membership"],
        existing_protections=["each participant learns the same peer list from the master before becoming ready, so instance ownership is globally consistent"],
        unknowns=["membership changes during a run are out of scope: transconf=false and no reconfiguration path is read"],
    ),
    behavior(
        "beh-epaxos-in-memory-history", "A6",
        "each replica's conflict table, sequence bookkeeping and optional stable store writes",
        "history of support: which instances touched a key, how far execution/commit have advanced, and what would be persisted when Durable=true",
        "every proposal, pre-accept, recovery adoption and commit updates the per-key tables",
        ["src-epaxos-tables", "src-epaxos-durable-meta", "src-state-conflict"],
        legal_preconditions=["the tables are only advanced by the run goroutine, so a read in another path must hold r.M or accept a stale view"],
        implementation_guards=[
            "conflicts[replica][key] tracks the last instance touching the key and the last instance writing it",
            "maxSeqPerKey stores the highest seq seen for the key",
            "updateCommitted advances CommittedUpTo only over a contiguous COMMITTED/EXECUTED prefix",
        ],
        reads=["r.conflicts", "r.maxSeqPerKey", "r.CommittedUpTo", "r.ExecedUpTo"],
        writes=["r.conflicts", "r.maxSeqPerKey", "r.maxSeq", "r.CommittedUpTo", "StableStore (only when Durable)"],
        durable_effects=["recordInstanceMetadata/recordCommands write to StableStore and sync only when Durable=true; the deployment passes durable=false"],
        important_branches=["recordInstanceMetadata writes inst.vbal over the slot first filled with inst.bal, so the byte layout keeps only vbal"],
        produces_fact_ids=["fact-preaccept-vote"],
        consumes_fact_ids=["fact-committed-instance"],
        existing_protections=["CommittedUpTo is only advanced contiguously, so a hole in the committed prefix cannot be silently skipped"],
        unknowns=["nothing in this snapshot reads StableStore back; crash recovery from durable metadata is not implemented in the captured source"],
    ),
]


def fact(id_, meaning, identity, validity, representation, durability, recovery, sources, **kw):
    obj = {
        "id": id_,
        "meaning": meaning,
        "identity": identity,
        "validity_context": validity,
        "representation": representation,
        "durability": durability,
        "recovery": recovery,
        "source_ids": sources,
    }
    obj.update(kw)
    return obj


FACTS = [
    fact(
        "fact-command-attributes",
        "The (seq, deps) attribute set that an instance's owner computed for its command batch from its own conflict history, plus the command batch itself.",
        {"instance": "owner replica id and per-owner instance number", "commands": "the batch assigned to that instance", "ballot": "the owner's initial ballot"},
        "Valid while the instance is the owner's un-overwritten proposal; recomputed by updateAttributes at every replica that pre-accepts it.",
        ["Instance.Cmds", "Instance.Seq", "Instance.Deps", "LeaderBookkeeping.deps", "LeaderBookkeeping.seq"],
        "In memory only in this configuration (Durable=false in run.go), so the attributes do not survive a process restart.",
        "Recovery recomputes or adopts attributes from prepare replies; it does not recompute the owner's original local history.",
        ["src-epaxos-propose-phase1", "src-epaxos-tables", "src-epaxos-preaccept"],
        unknowns=["the freshness of another replica's conflict table at pre-accept time is not observable from this snapshot"],
    ),
    fact(
        "fact-preaccept-vote",
        "An acceptor's stored pre-accept record for one instance: command, merged (seq, deps), ballot, vote ballot and status (PREACCEPTED or PREACCEPTED_EQ).",
        {"instance": "owner replica id and instance number", "acceptor": "replying replica id", "ballot": "ballot carried in the PreAcceptReply"},
        "Valid for the ballot reported in the reply; superseded by a higher-ballot PreAccept/Accept/Commit or replaced by an adopted value during recovery.",
        ["Instance.Cmds", "Instance.Seq", "Instance.Deps", "Instance.bal", "Instance.vbal", "Instance.Status", "PreAcceptReply.Seq/Deps/Status"],
        "In memory only; recordInstanceMetadata would persist bal/vbal/status/seq/deps when Durable=true.",
        "Prepare replies report the record; the recovering replica adopts the highest-vbal record and may re-accept it at a new ballot.",
        ["src-epaxos-preaccept", "src-epaxos-prepare-handler", "src-epaxos-durable-meta"],
        invalidators=["beh-epaxos-accept-phase", "beh-epaxos-commit-install"],
        reinterpreters=["beh-epaxos-recovery-phase1"],
        unknowns=["a record installed by handleTryPreAccept keeps the old vbal, so its reported vote ballot does not identify the try-pre-accept ballot"],
    ),
    fact(
        "fact-fast-commit",
        "The leader's determination that an instance is committed on the strength of a pre-accept quorum alone, without an Accept round.",
        {"instance": "owner replica id and instance number", "ballot": "initial ballot of the instance (ballot == owner)"},
        "Valid only for the owner's initial ballot; requires FastQuorumSize()-1 same-ballot replies, agreeing attributes and, for N>7, committed dependencies.",
        ["LeaderBookkeeping.status", "LeaderBookkeeping.allEqual", "Instance.Seq", "Instance.Deps", "Stats[fast]"],
        "In memory only; the committed instance is re-learned by peers through Commit.",
        "A recovery that observes a committed/executed reply takes the committed value; a fast commit is not re-derivable from pre-accepts alone.",
        ["src-epaxos-preaccept-reply", "src-replica-quorum"],
        unknowns=["for N<=3 with thrifty the equality test is skipped; the effect on attribute agreement across replicas is not established here"],
    ),
    fact(
        "fact-accepted-value",
        "The value and attribute set held by a majority of acceptors at one ballot for an instance (Accept phase or recovery sub-case 2/3).",
        {"instance": "owner replica id and instance number", "ballot": "accept ballot"},
        "Valid while no higher-ballot value is accepted by a later quorum for the same instance.",
        ["Instance.Deps", "Instance.Seq", "Instance.bal", "Instance.vbal", "AcceptReply.Ballot", "LeaderBookkeeping.acceptOKs"],
        "In memory only.",
        "Prepare replies re-report (bal, vbal, seq, deps); a recovering replica adopts the highest-vbal value and re-accepts it, or restarts phase 1.",
        ["src-epaxos-accept", "src-epaxos-bcasts"],
        unknowns=["an acceptor that only saw Accept reports Status NONE and no command, so recovery cannot read a value from Accept alone"],
    ),
    fact(
        "fact-committed-instance",
        "A replica's record that instance (owner, instance) is COMMITTED, with the command, attributes, ballot and execution status of that replica.",
        {"instance": "owner replica id and instance number", "replica": "the replica holding the record"},
        "Valid once the leader reached a fast quorum or a majority of Accept replies and the Commit was delivered; CommittedUpTo only advances over a contiguous prefix.",
        ["Instance.Cmds", "Instance.Seq", "Instance.Deps", "Instance.bal", "Instance.Status", "CommittedUpTo", "ExecedUpTo"],
        "In memory only in this configuration.",
        "Recovery observes committed status through prepare replies and re-installs the value; a committed instance with a command short-circuits recovery.",
        ["src-epaxos-commit", "src-epaxos-tables", "src-epaxos-recovery-entry"],
        unknowns=["the commit record is never reconstructed from StableStore in the captured source"],
    ),
    fact(
        "fact-recovery-decision",
        "The recovering replica's outcome for one instance at one recovery ballot: adopted command/(seq, deps)/status, the allEqual verdict, and which sub-case was dispatched (commit, accept, try-pre-accept, phase-1 restart).",
        {"instance": "owner replica id and instance number", "ballot": "lb.lastTriedBallot of the recovery attempt", "quorum": "the set of prepare replies counted"},
        "Valid for the recovery ballot whose replies satisfied SlowQuorumSize(); invalidated by a later ballot, a commit, or a subsequent recovery attempt.",
        ["LeaderBookkeeping.cmds/seq/deps/status", "LeaderBookkeeping.prepareReplies", "LeaderBookkeeping.leaderResponded", "Instance.Status", "subCase local variable"],
        "In memory only.",
        "This is itself the recovery mechanism: sub-cases 1-6 decide whether the recovered value is adopted, must be conflict-checked, or must be re-proposed.",
        ["src-epaxos-recovery-entry", "src-epaxos-prepare-reply", "src-epaxos-subcase-dispatch", "src-epaxos-subcase-actions"],
        consumed_by=[],
        unknowns=[
            "which threshold the implementation intends for the direct-accept sub-case is unresolved: the code condition is count >= SlowQuorumSize()-1 while its own comment states pre-accepted > f",
        ],
    ),
    fact(
        "fact-recovery-request",
        "The list of stalled instance ids a replica queued for recovery after the commit grace period elapsed for a blocking instance.",
        {"replica": "the replica whose execution is blocked", "instance": "every id from the blocking instance up to crtInstance[owner]"},
        "Valid once the same instance stayed the blocking instance for COMMIT_GRACE_PERIOD; consumed by the run goroutine in queue order.",
        ["instancesToRecover", "problemInstance[q]", "timeout[q]"],
        "Not persisted.",
        "Feeds startRecoveryForInstance, which is the only entry into phase 1 from local observation.",
        ["src-epaxos-exec-loop", "src-epaxos-run"],
        unknowns=["the queue can contain ids for instances the replica never received a message about; whether each such recovery completes is not established here"],
    ),
    fact(
        "fact-conflict-verdict",
        "Whether adopting the recovered attributes conflicts with an acceptor's stored state for other instances, and whether a conflicting instance is already ACCEPTED/COMMITTED.",
        {"instance": "the instance being recovered", "acceptor": "replying replica", "conflict": "the conflicting instance identity and status"},
        "Valid for the try-pre-accept ballot; the leader treats a reply as a confirmation only when the reported vote ballot equals its own.",
        ["TryPreAcceptReply.VBallot", "TryPreAcceptReply.ConflictReplica", "TryPreAcceptReply.ConflictInstance", "TryPreAcceptReply.ConflictStatus", "LeaderBookkeeping.preAcceptOKs/nacks/tpaAccepted"],
        "Not persisted.",
        "Consumed by the recovery leader to decide between accepting the recovered attributes, restarting phase 1, or deferring the instance.",
        ["src-epaxos-trypreaccept", "src-epaxos-tryreply", "src-epaxos-find-conflicts"],
        unknowns=[
            "the consumer's confirmation test (VBallot == lastTriedBallot) is not supported by the producer, which records bal but not vbal when it tries the pre-accept",
            "ConflictStatus is always NONE, so the abandon-and-restart rule cannot fire",
            "the dispatch that would broadcast TryPreAccept is unreachable in the captured recovery code",
        ],
    ),
    fact(
        "fact-execution-order",
        "For one replica: the set of instances already executed, the ExecedUpTo watermark per owner, and the resulting application of the replicated commands.",
        {"replica": "the executing replica", "instance": "owner replica id and instance number"},
        "Valid for the executing replica's own scan; two replicas agree only if they hold the same committed values and dependencies.",
        ["ExecedUpTo", "Instance.Status == EXECUTED", "Instance.Index/Lowlink", "State.Store"],
        "Not persisted in this configuration; the application state is rebuilt by re-execution only.",
        "Execution blocks on missing or uncommitted dependencies and triggers recovery for the blocked prefix.",
        ["src-exec", "src-epaxos-exec-loop"],
        unknowns=["whether the deterministic (Seq, owner, proposeTime) order is identical across replicas for every committed dependency graph reachable in this snapshot is not established here"],
    ),
    fact(
        "fact-client-reply",
        "The reply frame owed to (and delivered to) a client for a proposal: OK flag, CommandId and the value returned by executing the command.",
        {"client": "client id of the connection", "command": "CommandId allocated by the client", "instance": "owner replica id and instance number that carries the proposal"},
        "Valid for one proposal; a NOOP-committed instance transfers the duty to a re-proposed instance instead of replying.",
        ["ProposeReplyTS.OK/CommandId/Value", "GPropose.Reply writer", "LeaderBookkeeping.clientProposals"],
        "Not persisted.",
        "A stalled instance is recovered, not re-replied; the client has no retransmission and waits for as many replies as it issued.",
        ["src-exec", "src-epaxos-accept", "src-epaxos-preaccept-reply", "src-client-wait", "src-epaxos-commit"],
        unknowns=["the consumer of the reply lives outside the snapshot (client binary), so observed completion is modelled only through the frames written by the replica"],
    ),
    fact(
        "fact-membership",
        "The static participant set and quorum parameters that decide how many replicas a message must reach and which peers are eligible for broadcasts.",
        {"replica": "replica id assigned by the master", "deployment": "config-derived N together with f and the derived quorum sizes"},
        "Valid for the process lifetime; no reconfiguration path is present (transconf=false).",
        ["Replica.N/F/Id", "Replica.Alive", "Replica.PreferredPeerOrder", "FastQuorumSize()/SlowQuorumSize()/WriteQuorumSize()/ReadQuorumSize()"],
        "Not persisted in the replica.",
        "A dead peer stays Alive=false in the sender, so broadcasts shrink to the preferred live peers until the peer list is rebuilt by process restart.",
        ["src-run-epaxos", "src-replica-config", "src-master-register", "src-replica-quorum"],
        unknowns=["the Alive flag is cleared by the per-peer reader goroutine on EOF but is never set again in the captured source"],
    ),
]


def activity(class_id, applicability, purpose, realization, sources, entry_points=None, variants=None, unknowns=None):
    obj = {
        "class_id": class_id,
        "applicability": applicability,
        "purpose": purpose,
        "realization_summary": realization,
        "source_ids": sources,
    }
    if entry_points:
        obj["entry_points"] = entry_points
    if variants:
        obj["variants"] = variants
    if unknowns:
        obj["unknowns"] = unknowns
    return obj


ACTIVITIES = [
    activity(
        "A1", "applicable",
        "Qualified support for decision formation and legal advancement: which proposals may reach a decision for an instance and with which ordered attributes.",
        "EPaxos in the captured snapshot forms a decision per instance: the owner proposes through PreAccept, a fast quorum of agreeing pre-accepts commits directly (handlePreAcceptReply), otherwise Accept is broadcast to a majority and Commit follows (handleAccept/handleAcceptReply/handleCommit). Every replica keeps the resulting command and dependencies for execution.",
        ["src-epaxos-propose-phase1", "src-epaxos-preaccept", "src-epaxos-preaccept-reply", "src-epaxos-accept", "src-epaxos-commit"],
        entry_points=[
            "run.go: case \"epaxos\" -> epaxos.New", "epaxos.Replica.run select on ProposeChan/preAcceptChan/acceptChan/commitChan",
            "epaxos.Replica.handlePropose", "epaxos.Replica.startPhase1", "epaxos.Replica.handlePreAccept",
            "epaxos.Replica.handlePreAcceptReply", "epaxos.Replica.handleAccept", "epaxos.Replica.handleAcceptReply",
            "epaxos.Replica.handleCommit",
        ],
        variants=["thrifty=true (always in run.go): broadcasts target FastQuorumSize()-1 closest peers for PreAccept and N/2 peers for Accept"],
    ),
    activity(
        "A2", "applicable",
        "Context validity and acquisition, transfer or loss of authority inside a per-instance ownership model (no global leader or term exists).",
        "Authority for an instance is expressed by the ballot triple (inst.bal, inst.vbal, lb.lastTriedBallot): the instance owner starts at ballot == its own replica id, any replica may acquire authority by choosing a higher ballot in recovery, and every handler refuses or re-reports values from an older ballot. Higher-ballot Accept/Prepare overwrite attributes but not the command; a higher-ballot Commit overwrites both.",
        ["src-epaxos-ballot-helpers", "src-epaxos-preaccept", "src-epaxos-accept", "src-epaxos-prepare-handler", "src-epaxos-commit"],
        entry_points=[
            "epaxos.Replica.handlePreAccept (preAccept.Ballot < inst.bal)", "epaxos.Replica.handleAccept",
            "epaxos.Replica.handlePrepare", "epaxos.Replica.handleCommit", "epaxos.Replica.makeBallot", "epaxos.isInitialBallot",
        ],
        unknowns=["the deployment flag IsLeader (set by the master through Replica.BeTheLeader) is the only path that raises a ballot above r.maxRecvBallot"],
    ),
    activity(
        "A3", "applicable",
        "Recovery and resynchronization of eligible participation: restoring a stalled instance from a quorum of stored support.",
        "A replica whose execution blocks on a missing or uncommitted instance queues it after a 10s grace period; startRecoveryForInstance takes a fresh ballot, broadcasts Prepare, and handlePrepareReply folds a slow quorum of replies into one of six sub-cases that either adopt the recovered value (commit/accept/try-pre-accept) or restart phase 1. handleTryPreAccept/handleTryPreAcceptReply implement the conflict re-validation round and the defer-cycle bookkeeping.",
        ["src-epaxos-recovery-entry", "src-epaxos-prepare-reply", "src-epaxos-trypreaccept", "src-epaxos-tryreply", "src-epaxos-exec-loop"],
        entry_points=[
            "epaxos.Replica.executeCommands -> instancesToRecover", "epaxos.Replica.run case <-r.instancesToRecover",
            "epaxos.Replica.startRecoveryForInstance", "epaxos.Replica.handlePrepare", "epaxos.Replica.handlePrepareReply",
            "epaxos.Replica.bcastTryPreAccept", "epaxos.Replica.handleTryPreAccept", "epaxos.Replica.handleTryPreAcceptReply",
        ],
        unknowns=["the recovery sub-case that should broadcast TryPreAccept is unreachable in the captured code, so the conflict re-validation round has no producer"],
    ),
    activity(
        "A4", "applicable",
        "Configuration and participant eligibility: the static replica set, fault budget and the quorum sizes derived from them.",
        "run.go builds the replica from the deployment config with f=(N-1)/2; replica.New fixes N/F/Id, Alive and PreferredPeerOrder; the master assigns replica ids and the (unused for epaxos) leader hint; the epaxos client is leaderless and always talks to its co-located replica.",
        ["src-run-epaxos", "src-replica-config", "src-master-register", "src-replica-quorum"],
        entry_points=["run.go: runReplica", "master.Master.Register/GetReplicaList", "replica.New", "replica.Replica.SendMsg/bcast* Alive filters"],
        unknowns=["no membership change path exists in this snapshot (transconf=false)"],
    ),
    activity(
        "A5", "applicable",
        "Decision application and consumption: turning committed instances into an applied command order and a client-visible result.",
        "Exec.findSCC performs Tarjan strongly-connected-component search over the dependency graph of a committed instance, refuses to proceed while any dependency in the interval is missing or uncommitted, sorts each SCC by (Seq, owner replica, proposeTime), applies the commands to the in-memory store and marks the instances EXECUTED.",
        ["src-exec", "src-epaxos-exec-loop", "src-state-conflict"],
        entry_points=["epaxos.Replica.executeCommands", "epaxos.Exec.executeCommand", "epaxos.Exec.findSCC/strongconnect", "state.Command.Execute"],
    ),
    activity(
        "A6", "applicable",
        "History, persistence and reconstruction of support: the per-key conflict history and the durable metadata path that would preserve instance state.",
        "Each replica keeps conflicts[replica][key] = {last, lastWrite}, maxSeqPerKey, CommittedUpTo and ExecedUpTo in memory, and recordInstanceMetadata/recordCommands would append bal/vbal/status/seq/deps and commands to StableStore plus sync when Durable=true. The captured deployment never enables durability and no reader of StableStore exists in the snapshot.",
        ["src-epaxos-tables", "src-epaxos-durable-meta", "src-state-conflict"],
        entry_points=["epaxos.Replica.updateConflicts", "epaxos.Replica.updateAttributes", "epaxos.Replica.updateCommitted", "epaxos.Replica.recordInstanceMetadata/recordCommands/sync"],
        unknowns=["write-side layout only: recordInstanceMetadata writes vbal over the bal slot and nothing in the snapshot reads it back"],
    ),
    activity(
        "A7", "applicable",
        "Client contracts, invocation intervals and observed completion: how a proposal is admitted, when a reply frame is owed and what the client waits for.",
        "The client sends each proposal once to its closest (co-located) replica and waits for one ProposeReplyTS per issued command; the replica answers from the executor when Dreply=true, or at commit when !Dreply, and re-proposes a command whose instance was committed as a single NOOP. There is no client-side timeout, retransmission or deduplication window in the snapshot.",
        ["src-client-propose", "src-client-wait", "src-exec"],
        entry_points=["client.Client.SendProposal", "client.BufferClient.WaitReplies/Loop", "replica.Replica.clientListener", "epaxos.Replica.ReplyProposeTS"],
        unknowns=["client-side completion duty after a lost reply or a stalled replica is not implemented in the snapshot"],
    ),
]


def surface(entry, disposition, reason, sources, behavior_ids=None, high=False):
    obj = {"entry_point": entry, "disposition": disposition, "reason": reason, "source_ids": sources, "high_consequence": high}
    if behavior_ids:
        obj["behavior_ids"] = behavior_ids
    return obj


SURFACES = [
    surface("epaxos.Replica.bcastTryPreAccept", "mapped",
            "Mapped to the conflict re-validation behavior, but its only call site (sub-case 4) is unreachable; see the recovery sub-case surface.",
            ["src-epaxos-bcast-try"], ["beh-epaxos-recovery-trypreaccept"], high=True),
    surface("epaxos.Replica.handlePrepareReply sub-case dispatch", "UNCLASSIFIED_PROTOCOL_RESPONSIBILITY",
            "Sub-cases 3 and 4 carry identical conditions, so the TryPreAccept dispatch is unreachable and the direct-accept sub-case fires with fewer agreeing pre-accepts than its own comment ('pre-accepted > f') requires.",
            ["src-epaxos-subcase-comment", "src-epaxos-subcase-dispatch", "src-epaxos-subcase-actions"], high=True),
    surface("epaxos.Replica.handleTryPreAccept reply fields", "UNCLASSIFIED_PROTOCOL_RESPONSIBILITY",
            "The producer records the tried value as PREACCEPTED at tpa.Ballot but leaves inst.vbal, and never sets ConflictStatus; the consumer counts confirmations by VBallot and tests ConflictStatus >= ACCEPTED, so both consumer rules are unsatisfiable from this producer.",
            ["src-epaxos-trypreaccept", "src-epaxos-tryreply"], ["beh-epaxos-recovery-trypreaccept"], high=True),
    surface("epaxos.Replica.recordInstanceMetadata", "deferred",
            "Durable metadata writer: the second PutUint32 writes inst.vbal over the slot already filled with inst.bal, and no reader of StableStore exists in this snapshot, so durable reconstruction cannot be assessed here.",
            ["src-epaxos-durable-meta"]),
    surface("epaxos.Replica.handleAccept state update", "mapped",
            "Accept installs deps/seq/bal/vbal but neither the command nor ACCEPTED status, leaving the stored record readable only through its ballot; a peer that only saw Accept therefore reports no value to recovery.",
            ["src-epaxos-accept"], ["beh-epaxos-accept-phase"]),
    surface("epaxos/defs.go Marshal/Unmarshal size metadata", "infrastructure",
            "Wire format is length-prefixed per message; the BinarySize methods (AcceptReply reports 13 bytes for a 12-byte body, TryPreAcceptReply 26 for a 29-byte body) are not called anywhere in the captured source, so they cannot affect framing.",
            ["src-defs-acceptreply", "src-defs-tryreply", "src-rpc"]),
    surface("replica.MsgSet", "infrastructure",
            "Generic message-set quorum helper; the epaxos handlers do not use it (they count fields in LeaderBookkeeping directly), so its accept/free bookkeeping is outside this map.",
            ["src-mset"]),
    surface("hook.CondF/OptCondF", "infrastructure",
            "Conditional-callback helpers used by other protocols; no epaxos path references them in the captured source.",
            ["src-hook"]),
    surface("dlog.Logger", "infrastructure",
            "Logging wrapper; Println/Printf/Fatal continue to dereference l after handling the nil case, so a nil logger would panic, but every captured construction path passes a real logger.",
            ["src-dlog"]),
    surface("master.Master", "deferred",
            "Deployment service: assigns replica ids and leader hints and answers GetReplicaList/GetLeader. For epaxos the client ignores the leader and uses its co-located replica; the IsLeader flag only affects ballot raising in recovery and was not traced end to end.",
            ["src-master-register"]),
    surface("replica/defs/latency.go:IP", "deferred",
            "replica.New and client.Connect evaluate defs.IP() before NewLatencyTable checks its own configuration; IP() ignores the Dial error and dereferences the connection, so a deployment without an outbound route panics during construction instead of reporting the missing latency configuration. Not a protocol decision path, but it constrains how any in-process harness may build a Replica.",
            ["src-defs-ip", "src-replica-config"]),
]


CORE_OVERVIEW = {
    "formation": {
        "explanation": (
            "Formation is per instance and per owner. The owner allocates instance (owner, crtInstance[owner]++), computes (seq, deps) from its own conflict history, and broadcasts PreAccept with ballot == its own replica id. "
            "Each receiver merges its own conflict history into the attributes and stores a pre-accept vote, replying with ballot, vote ballot, seq, deps and status. "
            "The owner commits without a second round once FastQuorumSize()-1 same-ballot replies agree (allEqual, committed dependencies for N>7, initial ballot); otherwise it collects a majority of Accept replies and broadcasts Commit. "
            "Commit carries the command, so replicas that never pre-accepted still learn the value."
        ),
        "behavior_ids": ["beh-epaxos-propose", "beh-epaxos-preaccept-vote", "beh-epaxos-leader-fast-path", "beh-epaxos-accept-phase", "beh-epaxos-commit-install"],
        "fact_ids": ["fact-command-attributes", "fact-preaccept-vote", "fact-fast-commit", "fact-accepted-value", "fact-committed-instance"],
        "source_ids": ["src-epaxos-propose-phase1", "src-epaxos-preaccept", "src-epaxos-preaccept-reply", "src-epaxos-accept", "src-epaxos-commit", "src-replica-quorum"],
    },
    "context": {
        "explanation": (
            "The context that qualifies support is the ballot triple on a per-instance record, not a global term or leader: inst.bal is the ballot of the stored value, inst.vbal the ballot at which the value was last voted, and r.maxRecvBallot the highest ballot this replica has seen anywhere. "
            "A PreAccept below inst.bal is dropped silently; Accept, Prepare and Commit below inst.bal keep the stored value but re-report the current ballot, which is how a leader learns through nacks that it lost authority. "
            "Higher-ballot Accept and Prepare acquire authority over the attributes (deps/seq/vbal) but never over the command, while a higher-ballot Commit installs command and attributes. Recovery acquires authority only by choosing a ballot above the observed maximum (raised above r.maxRecvBallot when the deployment marked the replica as leader)."
        ),
        "behavior_ids": ["beh-epaxos-ballot-context-guard", "beh-epaxos-preaccept-vote", "beh-epaxos-commit-install"],
        "fact_ids": ["fact-preaccept-vote", "fact-committed-instance"],
        "source_ids": ["src-epaxos-ballot-helpers", "src-epaxos-preaccept", "src-epaxos-accept", "src-epaxos-prepare-handler", "src-epaxos-commit"],
    },
    "connection": {
        "explanation": (
            "The two lines meet in recovery, which is also the only place where authority is transferred between replicas. A replica whose executor blocks on an instance queues that instance (and the rest of the owner's visible prefix) after the 10s grace period; the recovering replica takes a fresh ballot, pre-seeds its own prepare reply, and waits for SlowQuorumSize() same-ballot replies. "
            "Support stays eligible across the ballot transition through vbal: the adopted value/status is the one with the highest vote ballot, and only replies that carry the highest vote ballot are compared for attribute equality. The adopted attributes are then either accepted at the recovery ballot, conflict-checked through TryPreAccept, or re-proposed from scratch with startPhase1. "
            "Pending work constrains subsequent formation because the adopted (seq, deps) are re-installed on the instance at lb.lastTriedBallot before any new round is broadcast, and because execution keeps blocking on the same instance until a committed value with a command exists."
        ),
        "behavior_ids": ["beh-epaxos-ballot-context-guard", "beh-epaxos-recovery-phase1", "beh-epaxos-recovery-trypreaccept", "beh-epaxos-accept-phase", "beh-epaxos-commit-install"],
        "fact_ids": ["fact-recovery-decision", "fact-conflict-verdict", "fact-accepted-value", "fact-committed-instance", "fact-preaccept-vote"],
        "source_ids": ["src-epaxos-recovery-entry", "src-epaxos-prepare-reply", "src-epaxos-bcast-try", "src-epaxos-accept", "src-epaxos-commit", "src-epaxos-exec-loop", "src-epaxos-preaccept", "src-epaxos-prepare-handler", "src-epaxos-trypreaccept", "src-epaxos-tryreply"],
    },
    "open_details": [
        "epaxos/epaxos.go:1270-1272 - the conditions for sub-cases 3 and 4 of handlePrepareReply are textually identical, so sub-case 4 (line 1304-1306, bcastTryPreAccept) is unreachable and the direct-accept sub-case is taken for count >= SlowQuorumSize()-1 (for N=5 that is 2 agreeing pre-accepts) although the comment block at 1228-1236 reserves 'pre-accepted > f' for it and routes 'pre-accepted >= f/2' to TryPreAccept.",
        "epaxos/epaxos.go:1328-1348 - handleTryPreAccept sets inst.bal = tpa.Ballot and records the candidate value, but never sets inst.vbal, so the reply reports the acceptor's previous vote ballot; the consumer at 1425 counts a confirmation only when tpar.VBallot == lb.lastTriedBallot.",
        "epaxos/epaxos.go:1330-1348 - ConflictStatus is initialised to NONE and never recomputed from the conflicting instance, so the consumer's restart-from-phase-1 rule at 1449-1456 cannot fire.",
        "epaxos/epaxos.go:990-1001 - handleAccept records deps/seq/bal/vbal but leaves inst.Cmds and inst.Status untouched, so Accept-only replicas report no value to recovery.",
        "epaxos/epaxos.go:807-813 - the ACCEPTED branch of handlePreAccept writes the incoming command into InstanceSpace[preAccept.LeaderId][preAccept.Instance] rather than into the instance being handled; the branch is only reachable when the stored record has Status >= ACCEPTED and Cmds == nil, which the read handlers do not currently produce.",
        "epaxos/epaxos.go:204-206 - recordInstanceMetadata fills the ballot slot with inst.bal and immediately overwrites it with inst.vbal, and nothing in the snapshot reads StableStore.",
        "epaxos/defs.go:506 and 1124 - AcceptReply.BinarySize reports 13 bytes for a 12-byte body and TryPreAcceptReply reports 26 for a 29-byte body; BinarySize is not called in the captured source.",
        "dlog/dlog.go:42-49 - Logger.Println/Printf/Fatal fall through to l.verbose after the nil check, so a nil receiver panics; all captured construction paths pass a non-nil logger.",
        "epaxos/epaxos.go:1109-1111 - handleCommit re-proposes own NOOP-committed instances through inst.lb without checking lb != nil; no legal history producing a nil bookkeeping entry at that point was established.",
    ],
    "core_gaps": [],
    "status": "usable",
    "rationale": (
        "Representative work is followed end to end: proposal allocation and attribute computation, pre-accept merging and vote storage, the fast-quorum commit, the Accept majority path, Commit installation, SCC execution and client completion, together with the ballot context that qualifies all of it. "
        "Both core lines and their connection through recovery are cited to the captured source. Local anomalies that remain unexplained are retained in open_details rather than promoted to core gaps, so the overview is usable for focused investigation."
    ),
}


MAP = {
    "version": 1,
    "target_profile": {
        "system_boundary": (
            "The captured Go module github.com/imdea-software/swiftpaxos, restricted to the EPaxos variant: the epaxos package (protocol), replica (peer transport, quorum sizes, client listener), client (leaderless proposal/reply), state (in-memory key-value store), master/config/dlog/hook/rpc as deployment support. "
            "A deployment runs one master, N replicas and one client per co-located replica; run.go for protocol 'epaxos' passes exec=!Noop, beacon=false, durable=false, batchWait=0, transconf=false, f=(N-1)/2, and the client is Leaderless with Fast=false."
        ),
        "protocol_contexts": [
            "EPaxos: per-instance ownership, ballot = owner id for a fresh proposal, quorum-based agreement with dependency (seq, deps) attributes",
            "leaderless client mode: a client proposes to its closest replica and waits for that replica's replies only",
            "thrifty=true: PreAccept is sent to FastQuorumSize()-1 closest alive peers, Accept to N/2 peers",
        ],
        "external_interfaces": [
            "replica peer connections: 1-byte RPC code + marshalled message (Prepare, PreAccept, Accept, Commit, TryPreAccept and replies)",
            "client connection: PROPOSE/STATS frames in, ProposeReplyTS frames out",
            "master net/rpc: Register, GetReplicaList, GetLeader",
        ],
        "ownership": [
            "instance (owner, n) is created and numbered only by its owner replica",
            "per-instance authority is the ballot (inst.bal, inst.vbal); there is no global leader, term or shared log",
            "each replica owns its own InstanceSpace rows for execution and its conflict table",
        ],
        "selection_injection": [
            "deployment config selects the replica set and size (f derived as (N-1)/2)",
            "run.go selects protocol behaviour: exec/beacon/durable/batchWait/transconf and leaderless client",
            "master may mark a replica as leader (Replica.BeTheLeader), which only affects makeBallot raising above r.maxRecvBallot",
        ],
        "variants": ["N=3 with thrifty skips the attribute-equality check on the fast path", "N>7 propagates committedDeps before committing"],
        "source_ids": ["src-run-epaxos", "src-replica-config", "src-epaxos-new", "src-replica-quorum", "src-client-propose"],
        "unknowns": ["no captured evidence of runs with N>7 or with a quorum file (the captured quorum.conf is not read by epaxos)"],
    },
    "activities": ACTIVITIES,
    "behaviors": BEHAVIORS,
    "facts": FACTS,
    "surfaces": SURFACES,
    "core_overview": CORE_OVERVIEW,
}


if __name__ == "__main__":
    (DRAFT / "map-v1.json").write_text(json.dumps(MAP, indent=1, ensure_ascii=False) + "\n")
    (DRAFT / "sources.json").write_text(json.dumps(SOURCES, indent=1) + "\n")
    print("wrote map-v1.json with", len(BEHAVIORS), "behaviors,", len(FACTS), "facts,", len(ACTIVITIES), "activities,", len(SURFACES), "surfaces")
