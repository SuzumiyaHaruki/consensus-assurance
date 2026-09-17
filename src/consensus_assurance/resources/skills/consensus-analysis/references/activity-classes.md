# Seven parallel CFT responsibility coordinates

These are neither execution stages nor disjoint code partitions. No leader, log, majority, fixed term field, pre-election, joint consensus or contact-loss stepdown is assumed.

| Class | Responsibility | Boundary questions |
| --- | --- | --- |
| A1 Decision Formation & Progression | Admit/establish candidate operations or values; produce and consume support; advance decisions. | What exact fact does a successful reply establish? Which request/context owns progress? |
| A2 Authority & Protocol Context Transition | Acquire, change, lose or transfer authority and interpret old work. | What actual term/view/ballot/epoch/round or per-instance context exists? Is transition requested or completed? |
| A3 Replica Recovery & Resynchronization | Restore lagging, restarted, disconnected or newly joined participants to legal participation. | Which retained representation is consumed, and how does incremental processing resume? |
| A4 Configuration & Participant Change | Propose, decide, activate and consume participant/configuration versions. | Which version governs each consumer? Static membership may be not_applicable with evidence. |
| A5 Decision Application | Turn decisions into state-machine/service effects via scheduling, batching, filtering and execution. | Which identity survives queues and restore interactions? A low-level primitive may externalize this. |
| A6 History & Recovery-Evidence Lifecycle | Produce, persist, publish, replace, truncate, compact, reclaim and reconstruct protocol history. | When is representation usable? What may be reclaimed afterwards? Normal-path persistence belongs here too. |
| A7 Client Operation Semantics | Admission, identity, redirect, retry, cancel, completion, reads/barriers and applicable deduplication. | What does the caller learn? Distinguish committed, scheduled, executed and completed; deduplication may belong to the caller. |

A2 authority and A4 active configuration can feed A1; A1 decisions feed A5; A6 recovery evidence feeds A3; A5 state feeds A6 capture; A1/A2/A5 effects feed A7. These are questions, not mandatory edges. One behavior can affect several classes.

Every class is applicable, externalized, not_applicable or unknown, with source/boundary reasoning and named missing material. Record behavior/fact/handoff understanding as unknown, partial or recovered; recovered is understanding, not verified correctness. Preserve UNCLASSIFIED_PROTOCOL_RESPONSIBILITY when the taxonomy does not explain an important protocol responsibility.

Reverse coverage starts from APIs, handlers, timers/loops, durable reads/writes/deletion, startup/recovery, membership interfaces, application callbacks and injected adapters. Do not fill a class merely to claim coverage. CFT includes crash/restart, permitted message loss/delay/duplication/reordering, timeout, stale results, concurrent work, persistence errors, optional variants and partial completion; it is not happy-path analysis.
