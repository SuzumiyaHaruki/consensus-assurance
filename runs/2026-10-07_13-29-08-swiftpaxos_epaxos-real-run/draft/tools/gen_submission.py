#!/usr/bin/env python3
"""Emit draft/submission.json for the current research product."""
import json
from pathlib import Path

import gen_map

DRAFT = Path(__file__).resolve().parents[1]


def write(name, obj):
    (DRAFT / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n")


def research_map_submission():
    return {
        "action": "research",
        "rationale": (
            "Record the first usable core map for the captured EPaxos snapshot: both core lines (formation/advancement and per-instance ballot context) and their connection through recovery, "
            "with sourced Behaviors, Facts and Surfaces plus retained local anomalies."
        ),
        "sources": gen_map.SOURCES,
        "map_path": "map-v1.json",
        "feedback": {
            "ref_ids": [
                "src-epaxos-prepare-reply",
                "src-epaxos-subcase-comment",
                "src-epaxos-subcase-dispatch",
                "src-epaxos-trypreaccept",
                "src-epaxos-tryreply",
            ],
            "answered": (
                "Initial understanding: EPaxos in this snapshot decides per instance. The owner allocates (owner, instance), computes (seq,deps) from its own conflict history and pre-accepts at ballot == owner; "
                "FastQuorumSize()-1 agreeing same-ballot replies let the leader commit directly, otherwise a majority of Accept replies plus a Commit carrying the command decides. "
                "Authority to overwrite a stored value is the per-instance ballot triple (inst.bal, inst.vbal, lb.lastTriedBallot): older PreAccept is dropped, older Accept/Prepare/Commit keep the command but re-report the current ballot, and only a higher ballot acquires authority over attributes. "
                "The connection between the lines is recovery: a blocked executor queues the instance after a 10s grace period, the recovering replica takes a fresh ballot, folds SlowQuorumSize() prepare replies by highest vote ballot, and either adopts the value or restarts phase 1."
            ),
            "remaining": [
                "The recovery sub-case dispatch inside handlePrepareReply: sub-cases 3 and 4 carry identical conditions, so the TryPreAccept broadcast at line 1306 is unreachable and the direct-accept sub-case fires for agreeing pre-accept counts that its own comment reserves for TryPreAccept.",
                "Producer/consumer agreement for the TryPreAccept round: handleTryPreAccept records bal but not vbal and never sets ConflictStatus, while handleTryPreAcceptReply counts confirmations by VBallot and restarts phase 1 on ConflictStatus >= ACCEPTED.",
                "Whether the skipped conflict re-validation can be turned into an executed ordering/agreement violation (needs a recovery scenario driven through the real handlers).",
            ],
            "rationale": (
                "The map is usable because both core paths and their connection are cited to actual code ranges; the anomalies above are retained as open details/surfaces rather than resolved, "
                "and they are the discriminators for the next focused investigation."
            ),
            "understanding": "updated",
        },
    }


if __name__ == "__main__":
    gen_map.main() if False else None
    (DRAFT / "map-v1.json").write_text(json.dumps(gen_map.MAP, indent=1, ensure_ascii=False) + "\n")
    write("submission.json", research_map_submission())
    print("wrote submission.json (research + map-v1.json)")
